"""Uruchamianie eksperymentu: sekwencje zmian i zestaw sprzeczności Z.

Przykład:
  python -m src.run --data data/main --out results/proba --variants B1 B2 M1 M2 --reps 5
Opcje --systems i --steps pozwalają ograniczyć przebieg (np. do próby integracyjnej).
Wyniki: <out>/config.json, <out>/sequences.jsonl, <out>/z.jsonl (jedna linia na krok/przypadek).
Przerwany przebieg można wznowić tym samym poleceniem: zapisane linie są pomijane.
"""
import argparse
import json
from pathlib import Path

from src import dataset, graph, llm, prompts, square
from src import model as sm
from src import scaffold as sc

VARIANTS = ["B1", "B2", "M1", "M2", "M1_noscript", "M2_noscript"]  # *_noscript: ablacja bez skryptu Γ


def ask_json(name, prompt, schema, shape_errors):
    """Wywołanie z odpowiedzią w JSON; najwyżej 1 ponowienie przy niepoprawnym JSON-ie."""
    log = {"name": name, "prompt": prompt, "attempts": []}
    for _ in range(2):
        r = llm.chat(prompt, schema)
        log["attempts"].append(r)
        try:
            data = json.loads(r["text"])
            errors = shape_errors(data)
        except json.JSONDecodeError as e:
            data, errors = None, [f"niepoprawny JSON: {e}"]
        r["errors"] = errors
        if not errors:
            return data, log
    return None, log


def ask_text(name, prompt):
    r = llm.chat(prompt)
    return r["text"], {"name": name, "prompt": prompt, "attempts": [r]}


def b_result_errors(data):
    if not isinstance(data, dict) or data.get("result") not in ("OK", "CONFLICT"):
        return ["brak pola 'result' (OK/CONFLICT)"]
    if data["result"] == "OK":
        return sm.shape_errors(data.get("model"))
    return [] if isinstance(data.get("conflicting"), list) else ["brak listy 'conflicting'"]


def m_model_errors(data):
    return sm.shape_errors(data.get("model")) if isinstance(data, dict) else ["odpowiedź nie jest obiektem"]


def gamma(variant, scaffold):
    """Konflikty wykryte przez Γ danego typu scaffoldu."""
    if variant == "M1":
        return square.check(scaffold)[0]
    return graph.check(scaffold)


def run_step(variant, system, ctx, requirements, change, initial, generate_model=True):
    """Jeden krok jednego wariantu.

    generate_model=False (zestaw Z, warianty M*): po walidacji scaffoldu nie generujemy modelu,
    bo w zestawie Z oceniamy tylko wykrywanie konfliktów.
    ctx: stan wariantu między krokami {"model", "scaffold", "analysis"}; aktualizowany w miejscu,
    gdy wynik zostaje zatwierdzony. Zwraca rekord do zapisania w wynikach.
    """
    vocab = system["vocabulary"]
    base = dict(system=system, requirements=requirements, model=ctx["model"], change=change, initial=initial)
    rec = {"result": None, "conflicting": [], "calls": []}

    if variant in ("B1", "B2"):
        section = "b1"
        extra = {}
        if variant == "B2":
            analysis, log = ask_text("analysis", prompts.render(
                "b2_analysis", previous=ctx["analysis"] or "(brak)", **base))
            rec["calls"].append(log)
            ctx["analysis"] = analysis
            section, extra = "b2_model", {"analysis": analysis}
        data, log = ask_json("model", prompts.render(section, **base, **extra), prompts.B_RESULT, b_result_errors)
        rec["calls"].append(log)
        if data is None:
            rec["result"] = "ERROR"
        elif data["result"] == "CONFLICT":
            rec.update(result="CONFLICT", conflicting=data["conflicting"])
        else:
            rec["result"] = "OK"
            ctx["model"] = data["model"]
        rec["model"] = ctx["model"]
        rec["model_issues"] = sm.semantic_issues(ctx["model"], vocab)
        return rec

    kind, strict = variant[:2], not variant.endswith("_noscript")
    requirement_ids = {r["id"] for r in dataset.apply_change(requirements, change)}
    diff, log = ask_json("scaffold", prompts.render(
        f"{kind.lower()}_scaffold", scaffold=json.dumps(ctx["scaffold"], ensure_ascii=False), **base),
        prompts.diff_schema(kind), sc.diff_shape_errors)
    rec["calls"].append(log)
    rec["diff"] = diff
    if diff is None:
        rec["result"] = "ERROR"
    else:
        new, errors, changed = sc.apply_diff(ctx["scaffold"], diff, kind, vocab, requirement_ids, strict)
        rec["diff_errors"] = errors
        conflicts = gamma(kind, new) if strict else []
        rec["gamma_conflicts"] = conflicts
        if strict and errors:
            rec["result"] = "REJECTED"  # skrypt odrzucił diff (nieistniejące ID, elementy spoza słownika)
        elif conflicts:
            rec["result"] = "CONFLICT"  # zmiana 'pending', scaffold i model zostają bez zmian
            rec["conflicting"] = sorted({
                r for c in conflicts for r in sc.requirements_of(c["items"], new, requirement_ids)})
        else:
            if kind == "M2":
                rec["zone"] = sorted(graph.influence_zone(new, changed))
            ctx["scaffold"] = new
            if not generate_model:
                rec["result"] = "OK"
                return rec
            data, log = ask_json("model", prompts.render(
                "m_model", scaffold=json.dumps(new, ensure_ascii=False), **base), prompts.M_MODEL, m_model_errors)
            rec["calls"].append(log)
            # Scaffold zatwierdzony przez Γ jest przyjmowany także wtedy, gdy model się nie udał.
            if data is None:
                rec["result"] = "ERROR"
            else:
                rec["result"] = "OK"
                ctx["model"] = data["model"]
    rec["scaffold"] = ctx["scaffold"]
    rec["model"] = ctx["model"]
    rec["model_issues"] = sm.semantic_issues(ctx["model"], vocab)
    return rec


def new_context():
    return {"model": sm.EMPTY_MODEL, "scaffold": sc.EMPTY_SCAFFOLD, "analysis": ""}


def run_sequence(system, variant, rep, max_steps, write):
    ctx = new_context()
    gold = dataset.gold_steps(system)
    for k, step in enumerate(system["steps"][:max_steps]):
        requirements = gold[k - 1]["requirements"] if k > 0 else []
        print(f"  {system['system']} {variant} powt.{rep} krok {k} ({step['type']})", flush=True)
        rec = run_step(variant, system, ctx, requirements, step, initial=(k == 0))
        write({"system": system["system"], "variant": variant, "rep": rep, "step": k, "type": step["type"], **rec})


def run_z_case(system, case, variant, rep):
    """Przypadek z zestawu Z: B* dostają wzorcowy model kroku 0, M* najpierw budują scaffold."""
    initial = system["steps"][0]
    requirements = dataset.apply_change([], initial)
    ctx = new_context()
    calls = []
    if variant.startswith("M"):
        rec = run_step(variant, system, ctx, [], initial, initial=True, generate_model=False)
        calls = rec["calls"]
        if rec["result"] != "OK":
            return {"result": "SCAFFOLD_ERROR", "conflicting": rec["conflicting"], "calls": calls}
    ctx["model"] = dataset.gold_model(system, dataset.tuples(initial["W"]))
    rec = run_step(variant, system, ctx, requirements, case, initial=False, generate_model=False)
    rec["calls"] = calls + rec["calls"]
    return rec


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", default="data/main", help="katalog z podkatalogami systems/ i conflicts/")
    p.add_argument("--out", required=True)
    p.add_argument("--variants", nargs="+", default=["B1", "B2", "M1", "M2"], choices=VARIANTS)
    p.add_argument("--reps", type=int, default=5)
    p.add_argument("--systems", nargs="*", help="tylko te systemy (domyślnie wszystkie)")
    p.add_argument("--steps", type=int, default=None, help="tylko pierwsze N kroków sekwencji")
    p.add_argument("--part", choices=["all", "sequences", "z"], default="all")
    args = p.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    systems = [s for s in dataset.load_systems(args.data) if not args.systems or s["system"] in args.systems]
    config = {"data": args.data, "variants": args.variants, "reps": args.reps, "llm": llm.model_info()}
    (out / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    def done_keys(path, key):
        if not path.exists():
            return set()
        return {key(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line}

    def writer(path):
        def write(record):
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=list) + "\n")
        return write

    if args.part in ("all", "sequences"):
        path = out / "sequences.jsonl"
        n_steps = args.steps or 6
        # Sekwencję wznawiamy tylko w całości (kolejne kroki zależą od poprzednich).
        done = done_keys(path, lambda r: (r["system"], r["variant"], r["rep"], r["step"]))
        for system in systems:
            last = min(n_steps, len(system["steps"])) - 1
            for variant in args.variants:
                for rep in range(args.reps):
                    if (system["system"], variant, rep, last) not in done:
                        run_sequence(system, variant, rep, n_steps, writer(path))

    if args.part in ("all", "z"):
        path = out / "z.jsonl"
        done = done_keys(path, lambda r: (r["system"], r["case"], r["variant"], r["rep"]))
        conflicts = dataset.load_conflicts(args.data)
        for system in systems:
            for case in conflicts.get(system["system"], []):
                for variant in args.variants:
                    for rep in range(args.reps):
                        key = (system["system"], case["id"], variant, rep)
                        if key in done:
                            continue
                        print(f"  Z {key}", flush=True)
                        rec = run_z_case(system, case, variant, rep)
                        writer(path)({"system": system["system"], "case": case["id"], "kind": case["kind"],
                                      "variant": variant, "rep": rep, **rec})


if __name__ == "__main__":
    main()
