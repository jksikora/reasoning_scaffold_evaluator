"""Analiza wyników: metryki per krok, test Wilcoxona z korektą Holma, wykresy, raport.

Użycie: python -m src.analysis results/<przebieg>
Tworzy w tym katalogu: steps.csv, z.csv, report.md, plot_*.png.
"""
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from scipy.stats import wilcoxon  # noqa: E402

from src import dataset, metrics  # noqa: E402

MAIN = "requirement_satisfaction"
COMPARISONS = [("B1", "M1"), ("B1", "M2"), ("B2", "M1"), ("B2", "M2"), ("M1", "M2")]
ORDER = ["B1", "B2", "M1", "M2", "M1_noscript", "M2_noscript"]
# Polskie nazwy do raportu (identyfikatory w kodzie i CSV są angielskie).
LABELS = {
    "requirement_satisfaction": "spełnienie wymagań", "precision": "precyzja", "recall": "czułość", "f1": "F1",
    "fully_correct": "w pełni poprawny", "add_coverage": "pokrycie dodań", "delete_coverage": "pokrycie usunięć",
    "functional_regressions": "regresje funkcjonalne", "structural_regressions": "regresje strukturalne",
    "hallucinations": "halucynacje", "unnecessary_changes": "zmiany zbędne", "model_issues": "problemy modelu",
    "strict_hallucinations": "halucynacje ścisłe", "scaffold_justified_errors": "błędy uzasadnione scaffoldem",
    "unjustified_decisions": "decyzje bez uzasadnienia", "script_conflicts": "konflikty wykryte przez skrypt",
    "script_blocked": "zmiana zablokowana przez skrypt", "diff_rejected": "diff odrzucony",
    "unnecessary_outside_zone": "zmiany zbędne poza strefą wpływu", "conflict_detected": "zgłoszony konflikt",
    "conflict_step_correct": "krok konfliktowy poprawny", "conflict_list_jaccard": "zgodność listy konfliktu",
    "llm_calls": "wywołania LLM", "retries": "ponowienia", "tokens": "tokeny", "seconds": "czas [s]",
    "new_rule": "nowa reguła", "new_dependency": "nowa zależność", "transition_change": "zmiana przejścia",
    "removal": "usunięcie", "contradiction": "sprzeczność",
}
# Stała kolejność kolorów kategorycznych: wariant ma zawsze ten sam kolor.
COLORS = {"B1": "#2a78d6", "B2": "#eb6834", "M1": "#1baf7a", "M2": "#eda100",
          "M1_noscript": "#e87ba4", "M2_noscript": "#008300"}


def read_jsonl(path, key):
    """Wczytuje rekordy; przy powtórzonym kluczu (wznowiony przebieg) obowiązuje ostatni."""
    if not path.exists():
        return []
    records = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line:
            r = json.loads(line)
            records[key(r)] = r
    return list(records.values())


def mean(values):
    values = [float(v) for v in values if v is not None]
    return statistics.mean(values) if values else None


def fmt(x):
    if x is None:
        return "–"
    return f"{x:.3f}" if isinstance(x, float) else str(x)


def table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(fmt(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def variants_of(rows):
    present = {r["variant"] for r in rows}
    return [v for v in ORDER if v in present]


def step_rows(records, systems):
    by_run = defaultdict(dict)
    for r in records:
        by_run[(r["system"], r["variant"], r["rep"])][r["step"]] = r
    rows = []
    for (system, variant, rep), steps in sorted(by_run.items()):
        gold = dataset.gold_steps(systems[system])
        for k in sorted(steps):
            m = metrics.step_metrics(systems[system], gold, k, steps[k], steps.get(k - 1))
            rows.append({"system": system, "variant": variant, "rep": rep, "step": k,
                         "type": steps[k]["type"], "kind": gold[k]["kind"], "result": steps[k]["result"], **m})
    return rows


def write_csv(path, rows):
    if not rows:
        return
    fields = list(dict.fromkeys(f for r in rows for f in r))
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def holm(pvalues):
    """Korekta Holma; None (brak testu) pozostaje None."""
    idx = sorted((p, i) for i, p in enumerate(pvalues) if p is not None)
    adjusted, running = [None] * len(pvalues), 0.0
    for rank, (p, i) in enumerate(idx):
        running = max(running, min(1.0, (len(idx) - rank) * p))
        adjusted[i] = running
    return adjusted


def rank_biserial(diffs):
    """Wielkość efektu dla testu Wilcoxona: (suma rang dodatnich - ujemnych) / suma rang."""
    nonzero = [d for d in diffs if d != 0]
    if not nonzero:
        return 0.0
    ordered = sorted(abs(d) for d in nonzero)
    rank = {v: statistics.mean(i + 1 for i, x in enumerate(ordered) if x == v) for v in ordered}
    pos = sum(rank[abs(d)] for d in nonzero if d > 0)
    neg = sum(rank[abs(d)] for d in nonzero if d < 0)
    return (pos - neg) / (pos + neg)


def confirmatory(rows):
    """Część potwierdzająca: średnia metryki głównej z kroków 1-5 per system, Wilcoxon + Holm."""
    per_system = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r["step"] >= 1:
            per_system[r["variant"]][r["system"]].append(r[MAIN])
    means = {v: {s: mean(vals) for s, vals in d.items()} for v, d in per_system.items()}

    results = []
    for a, b in COMPARISONS:
        common = sorted(set(means.get(a, {})) & set(means.get(b, {})))
        diffs = [means[b][s] - means[a][s] for s in common
                 if means[a][s] is not None and means[b][s] is not None]
        p = None
        if len(diffs) >= 2:
            p = 1.0 if all(d == 0 for d in diffs) else float(wilcoxon(diffs).pvalue)
        results.append([f"{a} vs {b}", len(diffs), statistics.median(diffs) if diffs else None,
                        rank_biserial(diffs) if diffs else None, p])
    for row, adj in zip(results, holm([r[4] for r in results])):
        row.append(adj)
    return means, results


def detection(rows, z_records):
    """Wykrywanie konfliktów: sekwencje i zestaw Z (łącznie i per rodzaj)."""
    out = []
    for v in variants_of(rows + z_records):
        seq = [r for r in rows if r["variant"] == v]
        z = [r for r in z_records if r["variant"] == v]
        hits = [(r["kind"], r["conflict_detected"]) for r in seq if r["conflict_expected"]]
        hits += [(r["kind"], r["result"] == "CONFLICT") for r in z if r["kind"] != "trap"]
        tp = sum(d for _, d in hits)
        fp_seq = sum(r["conflict_detected"] for r in seq if not r["conflict_expected"])
        traps = [r["result"] == "CONFLICT" for r in z if r["kind"] == "trap"]
        row = [v, metrics.ratio(tp, len(hits))]
        for kind in ("state", "transitive", "ordering"):
            row.append(metrics.ratio(sum(d for k, d in hits if k == kind), sum(1 for k, _ in hits if k == kind)))
        row += [metrics.ratio(tp, tp + fp_seq + sum(traps)),
                f"{fp_seq}/{sum(not r['conflict_expected'] for r in seq)}",
                f"{sum(traps)}/{len(traps)}",
                mean(r["conflict_step_correct"] for r in seq if r["conflict_expected"]),
                mean(r["conflict_list_jaccard"] for r in seq if r["conflict_expected"])]
        out.append(row)
    return out


def plot_by_step(rows, metric, title, path):
    fig, ax = plt.subplots(figsize=(7, 4))
    for v in variants_of(rows):
        steps = sorted({r["step"] for r in rows if r["variant"] == v})
        ys = [mean(r[metric] for r in rows if r["variant"] == v and r["step"] == k) for k in steps]
        ax.plot(steps, ys, color=COLORS[v], linewidth=2, marker="o", markersize=6, label=v)
        if ys and ys[-1] is not None:
            ax.annotate(v, (steps[-1], ys[-1]), xytext=(6, 0), textcoords="offset points",
                        va="center", fontsize=9, color="#52514e")
    ax.set_title(title, loc="left", fontsize=11)
    ax.set_xlabel("krok")
    ax.set_ylim(0, 1.05)
    ax.grid(axis="y", color="#e5e4e0", linewidth=0.8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(frameon=False, ncol=len(variants_of(rows)), loc="lower left", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main(out):
    out = Path(out)
    config = json.loads((out / "config.json").read_text(encoding="utf-8"))
    systems = {s["system"]: s for s in dataset.load_systems(config["data"])}
    records = read_jsonl(out / "sequences.jsonl", lambda r: (r["system"], r["variant"], r["rep"], r["step"]))
    z_records = read_jsonl(out / "z.jsonl", lambda r: (r["system"], r["case"], r["variant"], r["rep"]))
    rows = step_rows(records, systems)
    z_rows = [{k: r[k] for k in ("system", "case", "kind", "variant", "rep", "result")}
              | {"conflicting": " ".join(r["conflicting"])} | metrics.cost(r) for r in z_records]
    write_csv(out / "steps.csv", rows)
    write_csv(out / "z.csv", z_rows)

    variants = variants_of(rows + z_rows)
    llm = config["llm"]
    report = [f"# Raport: {out.name}", "",
              f"Model: `{llm['model']}` (digest `{llm['digest'][:12]}`), temperatura {llm['temperature']}, "
              f"powtórzenia: {config['reps']}, dane: `{config['data']}`, systemy: {len({r['system'] for r in rows})}.", ""]

    if rows:
        means, results = confirmatory(rows)
        report += ["## Część potwierdzająca", "",
                   "Metryka: spełnienie wymagań, średnia z kroków 1–5 i powtórzeń, per system. "
                   "Różnica = drugi wariant − pierwszy; r = korelacja rangowo-dwuseryjna.", "",
                   table(["system"] + variants,
                         [[s] + [means.get(v, {}).get(s) for v in variants] for s in sorted(systems)
                          if any(s in means.get(v, {}) for v in variants)]), "",
                   table(["porównanie", "n systemów", "mediana różnicy", "r", "p (Wilcoxon)", "p (Holm)"], results), ""]
        if all(r[4] is None for r in results):
            report += ["Za mało systemów do testu Wilcoxona (potrzeba co najmniej 2).", ""]

        numeric = [k for k, v in rows[0].items() if k not in ("system", "variant", "rep", "step", "type", "kind",
                                                              "result", "conflict_expected")]
        numeric += [k for k in ("strict_hallucinations", "scaffold_justified_errors", "unjustified_decisions",
                                "script_conflicts", "script_blocked",
                                "diff_rejected", "unnecessary_outside_zone") if k not in numeric]
        later = [r for r in rows if r["step"] >= 1]
        report += ["## Część eksploracyjna", "", "### Średnie metryk (kroki 1–5)", "",
                   table(["metryka"] + variants,
                         [[LABELS.get(k, k)] + [mean(r.get(k) for r in later if r["variant"] == v) for v in variants]
                          for k in numeric]), ""]

        first = [r for r in rows if r["step"] == 0]
        report += ["### Krok 0 (model początkowy)", "",
                   table(["wariant", "spełnienie wymagań", "F1", "w pełni poprawny"],
                         [[v] + [mean(r[k] for r in first if r["variant"] == v)
                                 for k in (MAIN, "f1", "fully_correct")] for v in variants]), ""]

        types = sorted({r["type"] for r in later})
        report += ["### Według typu zmiany (spełnienie wymagań / pokrycie dodań / pokrycie usunięć)", "",
                   table(["typ zmiany"] + variants,
                         [[LABELS.get(t, t)] + [" / ".join(fmt(mean(r[k] for r in later if r["variant"] == v and r["type"] == t))
                                            for k in (MAIN, "add_coverage", "delete_coverage"))
                                 for v in variants] for t in types]), ""]

        spread = []
        for v in variants:
            per = defaultdict(lambda: defaultdict(list))
            for r in later:
                if r["variant"] == v:
                    per[r["system"]][r["rep"]].append(r[MAIN])
            sds = [statistics.stdev(ms) for reps in per.values()
                   if len(ms := [m for m in (mean(x) for x in reps.values()) if m is not None]) >= 2]
            spread.append([v, mean(sds)])
        report += ["### Powtarzalność", "", "Odchylenie standardowe metryki głównej między powtórzeniami "
                   "(średnia po systemach).", "", table(["wariant", "odch. std."], spread), ""]

        for metric, title in ((MAIN, "Spełnienie wymagań w kolejnych krokach"), ("f1", "F1 w kolejnych krokach")):
            plot_by_step(rows, metric, title, out / f"plot_{metric}.png")
            report += [f"![{title}](plot_{metric}.png)", ""]

    if rows or z_rows:
        report += ["## Wykrywanie konfliktów", "",
                   "Czułość na sekwencjach i zestawie Z łącznie; fałszywe alarmy osobno na krokach bez "
                   "konfliktu w sekwencjach i na pułapkach Z.", "",
                   table(["wariant", "czułość", "stanowy", "przechodni", "kolejności", "precyzja",
                          "fałszywe alarmy (sekw.)", "fałszywe alarmy (pułapki)", "krok konfl. poprawny",
                          "zgodność listy (Jaccard)"], detection(rows, z_rows)), ""]

        all_runs = rows + z_rows
        report += ["## Koszt", "",
                   table(["wariant", "przebiegi", "wywołania", "ponowienia", "tokeny", "czas [s]"],
                         [[v, sum(r["variant"] == v for r in all_runs)]
                          + [sum(r[k] for r in all_runs if r["variant"] == v)
                             for k in ("llm_calls", "retries", "tokens")]
                          + [round(sum(r["seconds"] for r in all_runs if r["variant"] == v), 1)]
                          for v in variants]), ""]

    (out / "report.md").write_text("\n".join(report), encoding="utf-8")
    print(f"Zapisano {out / 'report.md'}")


if __name__ == "__main__":
    main(sys.argv[1])
