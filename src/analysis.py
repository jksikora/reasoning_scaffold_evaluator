"""Analiza wyników: metryki per krok, test Wilcoxona z korektą Holma, wykresy, raport.

Użycie: python -m src.analysis results/<przebieg>
Tworzy w tym katalogu: steps.csv, z.csv, report.md, plot_*.png.
"""
import csv
import json
import statistics
import sys
import warnings
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from scipy.stats import wilcoxon  # noqa: E402

from src import dataset, experiment, metrics  # noqa: E402

MAIN = "requirement_satisfaction"
COMPARISONS = [("B1", "M1"), ("B1", "M2"), ("B2", "M1"), ("B2", "M2"), ("M1", "M2")]
ORDER = ["B1", "B2", "M1", "M2", "M1_noscript", "M2_noscript"]
# Polskie nazwy do raportu (identyfikatory w kodzie i CSV są angielskie).
LABELS = {
    "model_valid": "poprawna maszyna stanów", "model_validation_errors": "błędy walidacji maszyny",
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
    "state": "stanowy", "transitive": "przechodni", "ordering": "kolejności",
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


def finish_plot(fig, path, synthetic=False):
    if synthetic:
        fig.text(0.99, 0.01, "DEMO — odpowiedzi syntetyczne, bez LLM", ha="right", fontsize=8, color="#666666")
    fig.tight_layout(rect=(0, 0.035 if synthetic else 0, 1, 1))
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_by_step(rows, metric, title, path, synthetic=False):
    fig, ax = plt.subplots(figsize=(9, 5))
    for v in variants_of(rows):
        steps = sorted({r["step"] for r in rows if r["variant"] == v})
        ys, spreads, counts = [], [], []
        for k in steps:
            groups = defaultdict(list)
            for r in rows:
                if r["variant"] == v and r["step"] == k and r.get(metric) is not None:
                    groups[r["system"]].append(r[metric])
            values = [mean(vals) for vals in groups.values()]
            ys.append(mean(values))
            spreads.append(statistics.stdev(values) if len(values) >= 2 else None)
            counts.append(sum(len(vals) for vals in groups.values()))
        count_label = str(counts[0]) if min(counts) == max(counts) else f"{min(counts)}–{max(counts)}"
        label = f"{v} (n={count_label} rekordów / krok)"
        style = {"B1": ("-", "o"), "B2": ("--", "s"), "M1": ("-.", "^"), "M2": (":", "D")}
        line, marker = style.get(v, ("--", "x"))
        ax.plot(steps, ys, color=COLORS[v], linewidth=2, marker=marker, linestyle=line,
                markerfacecolor="white", label=label)
        # Brak pasma przy mniej niż dwóch systemach; braki rozdzielają pasmo.
        low = [max(0, y - sd) if y is not None and sd is not None else float("nan")
               for y, sd in zip(ys, spreads)]
        high = [min(1, y + sd) if y is not None and sd is not None else float("nan")
                for y, sd in zip(ys, spreads)]
        ax.fill_between(steps, low, high, color=COLORS[v], alpha=0.12)
    ax.set_title(title, loc="left")
    ax.set_xlabel("krok; średnie po systemach, pasmo ±SD między systemami (przycięte do 0–1)", fontsize=9)
    ax.set_ylabel("udział")
    ax.set_ylim(-0.02, 1.05)
    ax.set_xticks(sorted({r["step"] for r in rows}))
    ax.grid(axis="y", alpha=0.2)
    ax.legend(frameon=False, fontsize=8, ncol=2, loc="best")
    finish_plot(fig, path, synthetic)


def detection_counts(rows, z_rows):
    """Oddzielne próby: sekwencje startują z własnego modelu, Z z modelu wzorcowego."""
    result = []
    for part, records in (("sekwencje", rows), ("Z", z_rows)):
        for v in variants_of(records):
            selected = [r for r in records if r["variant"] == v]
            for kind in ("łącznie", "state", "transitive", "ordering", "bez konfliktu"):
                subset = []
                for r in selected:
                    expected = r["conflict_expected"] if part == "sekwencje" else r["kind"] != "trap"
                    if ((kind == "łącznie" and expected) or (kind == "bez konfliktu" and not expected)
                            or (kind in ("state", "transitive", "ordering") and expected and r["kind"] == kind)):
                        subset.append(r)
                hits = sum(r["result"] == "CONFLICT" for r in subset)
                result.append({"part": part, "variant": v, "kind": kind, "hits": hits,
                               "n": len(subset), "rate": metrics.ratio(hits, len(subset))})
    return result


def plot_overview(rows, z_rows, out, synthetic=False):
    records = rows + z_rows
    variants = variants_of(records)
    statuses = ("OK", "CONFLICT", "REJECTED", "ERROR", "SCAFFOLD_ERROR")
    fig, ax = plt.subplots(figsize=(9, 5))
    bottom = [0] * len(variants)
    for status, color in zip(statuses, ("#1baf7a", "#2a78d6", "#eda100", "#c44e52", "#8053a3")):
        counts = [sum(r["variant"] == v and r["result"] == status for r in records) for v in variants]
        ax.bar(variants, counts, bottom=bottom, label=status, color=color)
        bottom = [a + b for a, b in zip(bottom, counts)]
    ax.set_ylabel("liczba rekordów")
    ax.set_title("Statusy odpowiedzi — sekwencje i Z", loc="left")
    ax.set_ylim(0, max(bottom, default=1) * 1.12)
    for i, total in enumerate(bottom):
        ax.text(i, total + max(bottom, default=1) * 0.02, str(total), ha="center", fontsize=9)
    ax.legend(frameon=False, fontsize=8, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.08))
    finish_plot(fig, out / "plot_statuses.png", synthetic)

    counts = detection_counts(rows, z_rows)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    for ax, part in zip(axes, ("sekwencje", "Z")):
        for offset, kind, label, color in ((-0.18, "łącznie", "czułość", "#2a78d6"),
                                           (0.18, "bez konfliktu", "fałszywe alarmy", "#eb6834")):
            for i, v in enumerate(variants):
                c = next((c for c in counts if c["part"] == part and c["variant"] == v and c["kind"] == kind), None)
                if c and c["n"]:
                    ax.bar(i + offset, c["rate"], width=0.34, color=color, label=label if i == 0 else None)
                    ax.text(i + offset, c["rate"] + 0.03, f"{c['hits']}/{c['n']}", ha="center", fontsize=8)
                else:
                    ax.text(i + offset, 0.04, "–", ha="center")
        ax.set_xticks(range(len(variants)), variants)
        ax.set_title(part)
        ax.set_ylim(0, 1.22)
        ax.set_ylabel("udział; – oznacza brak obserwacji")
        ax.legend(handles=[Patch(color="#2a78d6", label="czułość"),
                           Patch(color="#eb6834", label="fałszywe alarmy")],
                  frameon=False, fontsize=8, loc="upper center")
    fig.suptitle("Wykrywanie konfliktów w dwóch trybach eksperymentu")
    finish_plot(fig, out / "plot_conflicts.png", synthetic)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for ax, key, label in zip(axes, ("seconds", "tokens"), ("czas [s] / rekord", "tokeny / rekord")):
        vals = [mean(r[key] for r in records if r["variant"] == v) for v in variants]
        ax.bar(variants, vals, color=[COLORS[v] for v in variants])
        ax.set_ylabel(label)
        ax.set_title("Średni koszt ocenionego rekordu", fontsize=11, loc="left")
    finish_plot(fig, out / "plot_cost.png", synthetic)


def completeness(config, systems, conflicts, records, z_records):
    expected_seq, expected_z = experiment.expected_keys(config, systems, conflicts)
    actual_seq = {(r["system"], r["variant"], r["rep"], r["step"]) for r in records}
    actual_z = {(r["system"], r["case"], r["variant"], r["rep"]) for r in z_records}
    complete = expected_seq == actual_seq and expected_z == actual_z
    summary = [["sekwencje", len(expected_seq), len(actual_seq), len(expected_seq - actual_seq), len(actual_seq - expected_seq)],
               ["Z", len(expected_z), len(actual_z), len(expected_z - actual_z), len(actual_z - expected_z)]]
    return complete, summary


def mean_n(values):
    values = [v for v in values if v is not None]
    return f"{fmt(mean(values))} (n={len(values)})"


def main(out):
    out = Path(out)
    config = json.loads((out / "config.json").read_text(encoding="utf-8"))
    legacy = "schema_version" not in config
    if legacy:
        warning = "Starszy przebieg: brak snapshotu i gwarancji zgodności danych; wyniki tylko eksploracyjne."
        warnings.warn(warning, stacklevel=2)
        loaded, conflicts = dataset.validated_load(config["data"])
    else:
        snapshot = experiment.frozen_data(out, config)
        loaded, conflicts = snapshot["systems"], snapshot["conflicts"]
    systems = {s["system"]: s for s in loaded}
    records = read_jsonl(out / "sequences.jsonl", lambda r: (r["system"], r["variant"], r["rep"], r["step"]))
    z_records = read_jsonl(out / "z.jsonl", lambda r: (r["system"], r["case"], r["variant"], r["rep"]))
    if any(r["system"] not in systems for r in records + z_records):
        raise ValueError("Logi wskazują system spoza danych przebiegu; stare logi wymagają zgodnej historycznej wersji danych.")
    rows = step_rows(records, systems)
    z_rows = [{k: r[k] for k in ("system", "case", "kind", "variant", "rep", "result")}
              | {"conflicting": " ".join(r["conflicting"])} | metrics.cost(r) for r in z_records]
    write_csv(out / "steps.csv", rows)
    write_csv(out / "z.csv", z_rows)
    complete, coverage = completeness(config, systems, conflicts, records, z_records)
    pilot = config.get("purpose") == "pilot" or any(s.get("purpose") == "pilot" for s in loaded)
    eligible = (complete and not legacy and not pilot and len(systems) >= 10
                and {"B1", "B2", "M1", "M2"} <= set(config["variants"])
                and all(len(s["steps"][:config.get("steps") or 6]) == 6 for s in loaded)
                and config.get("part", "all") in ("all", "sequences"))
    variants = variants_of(rows + z_rows)
    info = config["llm"]
    report = [f"# Raport: {out.name}", "",
              f"Model: `{info['model']}` (digest `{info['digest'][:12]}`), temperatura {info['temperature']}.", "",
              f"Dane: `{config['data']}`; systemy: {len(systems)}; planowane powtórzenia: {config['reps']}; "
              f"zapisane powtórzenia: {len({r['rep'] for r in records + z_records})}; "
              f"zapisane kroki: {', '.join(str(k) for k in sorted({r['step'] for r in records})) or 'brak'}.", "",
              f"**Status: {'PILOTAŻ; ' if pilot else ''}{'KOMPLETNY' if complete else 'NIEPEŁNY / NIEZGODNY'}.**", ""]
    if info["model"].startswith("MOCK"):
        report += ["**DEMONSTRACJA OFFLINE — zaplanowane odpowiedzi; to nie są wyniki rzeczywistego LLM.**", ""]
    if legacy:
        report += [warning, ""]
    report += ["## Kompletność", "", table(["część", "oczekiwane", "zapisane", "brakujące", "nadmiarowe"], coverage), "",
               "Zapisane rekordy po deduplikacji; przy powtórzonym kluczu obowiązuje ostatni zapis.", "",
               "Metryka główna to surowy odsetek testów wymagań. Wysoki wynik może współistnieć z niepoprawną "
               "maszyną. Poprawność maszyny raportujemy osobno; nieosiągalne stany są ostrzeżeniem. "
               "W pełni poprawny model musi być poprawną maszyną i spełniać W ⊆ T ⊆ W ∪ P.", ""]
    if rows:
        if eligible:
            means, results = confirmatory(rows)
            report += ["## Część potwierdzająca", "",
                       "Spełnienie wymagań: średnia z kroków 1–5 i powtórzeń per system. "
                       "Różnica = drugi wariant − pierwszy; r = korelacja rangowo-dwuseryjna.", "",
                       table(["system"] + variants, [[name] + [means.get(v, {}).get(name) for v in variants]
                                                     for name in sorted(systems)]), "",
                       table(["porównanie", "n systemów", "mediana różnicy", "r", "p (Wilcoxon)", "p (Holm)"], results), ""]
        else:
            report += ["Analiza wyłącznie eksploracyjna. Testy potwierdzające wymagają kompletnego przebiegu "
                       "co najmniej 10 systemów, czterech wariantów B1/B2/M1/M2 i sześciu kroków, "
                       "z wersjonowanym manifestem, poza datasetem pilotażowym.", ""]
        numeric = list(dict.fromkeys(k for r in rows for k, value in r.items()
                                    if isinstance(value, (float, int, bool))
                                    and k not in ("rep", "step", "conflict_expected")))
        later = [r for r in rows if r["step"] >= 1]
        report += ["## Część eksploracyjna", "", "### Średnie metryk (dostępne kroki 1–5)", "",
                   "Każda komórka podaje średnią i liczbę niepustych obserwacji n.", "",
                   table(["metryka"] + variants,
                         [[LABELS.get(k, k)] + [mean_n(r.get(k) for r in later if r["variant"] == v) for v in variants]
                          for k in numeric]), ""]
        first = [r for r in rows if r["step"] == 0]
        report += ["### Krok 0", "", table(["wariant", "spełnienie wymagań", "F1", "poprawna maszyna", "w pełni poprawny"],
                   [[v] + [mean_n(r[k] for r in first if r["variant"] == v)
                           for k in (MAIN, "f1", "model_valid", "fully_correct")] for v in variants]), ""]
        types = sorted({r["type"] for r in later})
        report += ["### Według typu zmiany — spełnienie wymagań", "",
                   table(["typ zmiany"] + variants,
                         [[LABELS.get(t, t)] + [mean_n(r[MAIN] for r in later if r["variant"] == v and r["type"] == t)
                                               for v in variants] for t in types]), ""]
        spread = []
        for v in variants:
            per = defaultdict(lambda: defaultdict(list))
            for r in later:
                if r["variant"] == v:
                    per[r["system"]][r["rep"]].append(r[MAIN])
            sds = [statistics.stdev(ms) for reps in per.values()
                   if len(ms := [m for m in (mean(x) for x in reps.values()) if m is not None]) >= 2]
            spread.append([v, mean_n(sds)])
        report += ["### Powtarzalność", "", "Odchylenie standardowe metryki głównej między powtórzeniami, średnia po systemach.", "",
                   table(["wariant", "odch. std."], spread), ""]
        for metric, title in ((MAIN, "Spełnienie wymagań w kolejnych krokach"), ("f1", "F1 w kolejnych krokach"),
                              ("model_valid", "Udział poprawnych maszyn stanów")):
            plot_by_step(rows, metric, title, out / f"plot_{metric}.png", info["model"].startswith("MOCK"))
            report += [f"![{title}](plot_{metric}.png)", ""]
    if rows or z_rows:
        all_runs = rows + z_rows
        report += ["## Statusy odpowiedzi", "",
                   table(["wariant", "OK", "CONFLICT", "REJECTED", "ERROR", "SCAFFOLD_ERROR"],
                         [[v] + [sum(r["variant"] == v and r["result"] == status for r in all_runs)
                                 for status in ("OK", "CONFLICT", "REJECTED", "ERROR", "SCAFFOLD_ERROR")]
                          for v in variants]), "", "![Statusy odpowiedzi](plot_statuses.png)", "",
                   "## Wykrywanie konfliktów", "",
                   "Sekwencje i Z są oceniane osobno. CONFLICT na przypadku bez konfliktu oznacza fałszywy alarm. "
                   "ERROR, REJECTED i SCAFFOLD_ERROR na konflikcie liczą się jako niewykrycie.", "",
                   table(["część", "wariant", "rodzaj", "zgłoszenia / przypadki", "udział"],
                         [[c["part"], c["variant"], LABELS.get(c["kind"], c["kind"]),
                           f"{c['hits']}/{c['n']}", c["rate"]] for c in detection_counts(rows, z_rows)]), "",
                   "![Wykrywanie konfliktów](plot_conflicts.png)", "", "## Koszt", "",
                   "Koszt deduplikowanych rekordów obejmuje ponowienia odpowiedzi, ale nie wszystkie wcześniejsze "
                   "próby zastąpione przy wznowieniu ani przerwane wywołania bez rekordu.", "",
                   table(["wariant", "rekordy", "wywołania", "ponowienia", "tokeny", "czas [s]", "tokeny / rekord", "s / rekord"],
                         [[v, sum(r["variant"] == v for r in all_runs)]
                          + [sum(r[k] for r in all_runs if r["variant"] == v)
                             for k in ("llm_calls", "retries", "tokens", "seconds")]
                          + [mean(r[k] for r in all_runs if r["variant"] == v) for k in ("tokens", "seconds")]
                          for v in variants]), "", "![Koszt](plot_cost.png)", ""]
        plot_overview(rows, z_rows, out, info["model"].startswith("MOCK"))
    (out / "report.md").write_text("\n".join(report), encoding="utf-8")
    print(f"Zapisano {out / 'report.md'}")


if __name__ == "__main__":
    main(sys.argv[1])
