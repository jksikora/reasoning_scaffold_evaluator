"""Wczytywanie i sprawdzanie datasetu.

Użycie: python -m src.dataset data/example   (sprawdza systems/*.json i conflicts/*.json)
"""
import json
import sys
from pathlib import Path

from src import model as sm

CHANGE_TYPES = {"initial", "new_rule", "new_dependency", "transition_change", "removal", "contradiction"}
CONFLICT_KINDS = {"state", "transitive", "ordering", "trap"}


def load_system(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_systems(directory):
    return [load_system(p) for p in sorted(Path(directory, "systems").glob("*.json"))]


def load_conflicts(directory):
    """Zestaw Z: słownik nazwa_systemu -> lista przypadków."""
    result = {}
    for p in sorted(Path(directory, "conflicts").glob("*.json")):
        data = load_system(p)
        result[data["system"]] = data["cases"]
    return result


def apply_change(requirements, change):
    """Lista wymagań po zmianie: 'remove' usuwa ID, 'add' dodaje lub podmienia wymaganie o tym ID."""
    removed = set(change.get("remove", [])) | {r["id"] for r in change.get("add", [])}
    kept = [r for r in requirements if r["id"] not in removed]
    return kept + change.get("add", [])


def tuples(items):
    return {tuple(t) for t in items}


def gold_steps(system):
    """Wzorzec dla kolejnych kroków sekwencji.

    Każdy element: requirements (zatwierdzone po kroku), W, P, conflict, conflicting, affects.
    W kroku ze sprzecznością zmiana jest wycofywana: wymagania, W i P pozostają z kroku k-1.
    """
    result, requirements, W, P = [], [], set(), set()
    for step in system["steps"]:
        conflict = step["type"] == "contradiction"
        if not conflict:
            requirements = apply_change(requirements, step)
            W, P = tuples(step["W"]), tuples(step.get("P", []))
        changed = {r["id"] for r in step.get("add", [])} | set(step.get("remove", []))
        result.append({
            "type": step["type"],
            "requirements": requirements,
            "W": W,
            "P": P,
            "conflict": conflict,
            "conflicting": set(step.get("conflicting", [])),
            "kind": step.get("kind"),
            "affects": changed | set(step.get("affects", [])),
        })
    return result


def gold_model(system, W):
    """Model wzorcowy z przejść W (używany w zestawie Z i w kontroli spójności wzorca)."""
    used = {system["initial"]} | {t[0] for t in W} | {t[3] for t in W}
    return {
        "states": [s for s in system["vocabulary"]["states"] if s in used],
        "initial": system["initial"],
        "final": [],
        "transitions": [dict(zip(("from", "event", "guard", "to"), t)) for t in sorted(W, key=str)],
    }


def check_transition(t, vocab):
    s, e, g, d = t
    ok = s in vocab["states"] and d in vocab["states"] and e in vocab["events"]
    return ok and (g is None or g in vocab["guards"])


def check_change(change, known_ids, errors, where):
    for r in change.get("add", []):
        if not r.get("id") or not r.get("text") or not r.get("tests"):
            errors.append(f"{where}: wymaganie bez id/text/tests: {r}")
        for t in r.get("tests", []):
            if t.get("type") not in sm.TEST_TYPES:
                errors.append(f"{where}: nieznany typ testu {t}")
    for rid in change.get("remove", []):
        if rid not in known_ids:
            errors.append(f"{where}: usuwane wymaganie {rid} nie istnieje")


def validate_system(system):
    errors = []
    vocab = system["vocabulary"]
    steps = system["steps"]
    for a, b in vocab["exclusive"]:
        if a not in vocab["guards"] or b not in vocab["guards"]:
            errors.append(f"para wykluczająca spoza słownika: {a}, {b}")
    if system["initial"] not in vocab["states"]:
        errors.append("stan początkowy spoza słownika")
    if not steps or steps[0]["type"] != "initial":
        errors.append("krok 0 musi mieć typ 'initial'")

    requirements = []
    for k, (step, gold) in enumerate(zip(steps, gold_steps(system))):
        where = f"krok {k}"
        if step["type"] not in CHANGE_TYPES:
            errors.append(f"{where}: nieznany typ zmiany {step['type']}")
        check_change(step, {r["id"] for r in requirements}, errors, where)
        if gold["conflict"]:
            ids = {r["id"] for r in apply_change(requirements, step)}
            if not gold["conflicting"] or not gold["conflicting"] <= ids:
                errors.append(f"{where}: 'conflicting' musi wskazywać istniejące wymagania")
            if step.get("kind") not in CONFLICT_KINDS - {"trap"}:
                errors.append(f"{where}: krok ze sprzecznością wymaga 'kind' (state/transitive/ordering)")
            if "W" in step or "P" in step:
                errors.append(f"{where}: krok ze sprzecznością nie ma własnego W/P")
            continue
        requirements = gold["requirements"]
        if gold["W"] & gold["P"]:
            errors.append(f"{where}: W i P nie mogą mieć części wspólnej")
        for t in gold["W"] | gold["P"]:
            if not check_transition(t, vocab):
                errors.append(f"{where}: przejście spoza słownika {t}")
        # Kontrola spójności wzorca: model złożony z W musi przechodzić wszystkie testy.
        m = gold_model(system, gold["W"])
        for r in requirements:
            if not sm.requirement_passes(r, m, vocab):
                errors.append(f"{where}: model z W nie spełnia testów wymagania {r['id']}")
    return errors


def validate_cases(system, cases):
    errors = []
    base_ids = {r["id"] for r in apply_change([], system["steps"][0])}
    for case in cases:
        where = f"przypadek {case['id']}"
        if case["kind"] not in CONFLICT_KINDS:
            errors.append(f"{where}: nieznany rodzaj {case['kind']}")
        check_change(case, base_ids, errors, where)
        ids = {r["id"] for r in apply_change(apply_change([], system["steps"][0]), case)}
        trap = case["kind"] == "trap"
        if trap and case.get("conflicting"):
            errors.append(f"{where}: pułapka nie może mieć 'conflicting'")
        if not trap and not (case.get("conflicting") and set(case["conflicting"]) <= ids):
            errors.append(f"{where}: 'conflicting' musi wskazywać istniejące wymagania")
    return errors


def main(directory):
    systems = {s["system"]: s for s in load_systems(directory)}
    conflicts = load_conflicts(directory)
    ok = True
    for name, system in systems.items():
        errors = validate_system(system)
        if name in conflicts:
            errors += validate_cases(system, conflicts[name])
        print(f"{name}: {'OK' if not errors else 'BŁĘDY'}")
        for e in errors:
            print("  -", e)
        ok = ok and not errors
    for name in conflicts.keys() - systems.keys():
        print(f"{name}: zestaw Z bez pliku systemu")
        ok = False
    return ok


if __name__ == "__main__":
    sys.exit(0 if main(sys.argv[1] if len(sys.argv) > 1 else "data/main") else 1)
