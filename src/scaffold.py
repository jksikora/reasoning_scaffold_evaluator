"""Wspólna część scaffoldu <C, A, R, Γ, D>: różnica (diff), odnośniki w D, źródła konfliktów.

Scaffold w pamięci: {"A": [...], "R": [...], "D": [...]}. C jest stałe (słownik systemu),
więc nie jest przechowywane w scaffoldzie ani budowane przez LLM.
Prefiksy ID: A - założenia, K - zdania kwadratu (M1), G - krawędzie grafu (M2), D - decyzje.
"""
import copy

EMPTY_SCAFFOLD = {"A": [], "R": [], "D": []}
A_STATUSES = {"required", "inferred", "unresolved"}
R_PREFIX = {"M1": "K", "M2": "G"}
# Źródło elementów wynikających wprost ze słownika (np. krawędź 'excludes' dla pary warunków).
VOCABULARY_SOURCE = "vocabulary"


def diff_shape_errors(diff):
    """Błędy struktury odpowiedzi (powód do ponowienia zapytania)."""
    if not isinstance(diff, dict):
        return ["odpowiedź nie jest obiektem"]
    errors = []
    for op in ("add", "modify"):
        part = diff.get(op)
        if not isinstance(part, dict) or not all(isinstance(part.get(s), list) for s in "ARD"):
            errors.append(f"'{op}' musi mieć listy A, R, D")
            continue
        for s in "ARD":
            for item in part[s]:
                if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                    errors.append(f"element bez 'id' w {op}.{s}: {item}")
    if not isinstance(diff.get("remove"), list) or not all(isinstance(i, str) for i in diff["remove"]):
        errors.append("'remove' musi być listą ID")
    return errors


def item_errors(section, item, variant, vocabulary, requirement_ids, known_ids):
    """Błędy merytoryczne pojedynczego elementu (słownik, typy, odnośniki).

    known_ids: ID wymagań, założeń A i "vocabulary", na które może wskazywać pole 'source' elementu R.
    """
    prefix = {"A": "A", "R": R_PREFIX[variant], "D": "D"}[section]
    if not item["id"].startswith(prefix):
        return [f"{item['id']}: element sekcji {section} musi mieć ID z prefiksem {prefix}"]
    states, events, guards = vocabulary["states"], vocabulary["events"], vocabulary["guards"]
    errors = []
    if section == "A":
        if item.get("status") not in A_STATUSES:
            errors.append(f"{item['id']}: niepoprawny status")
        if item.get("status") == "required" and item.get("source") not in requirement_ids:
            errors.append(f"{item['id']}: założenie wymagane musi wskazywać wymaganie")
    elif section == "D":
        t = item.get("transition")
        if not (isinstance(t, list) and len(t) == 4 and isinstance(item.get("justified_by"), list)):
            errors.append(f"{item['id']}: D wymaga 'transition' (4 elementy) i 'justified_by'")
    elif item.get("source") not in known_ids:
        errors.append(f"{item['id']}: 'source' musi wskazywać wymaganie, założenie A lub 'vocabulary'")
    if section != "R" or errors:
        return errors
    if variant == "M1":
        if item.get("state") not in states or item.get("event") not in events:
            errors.append(f"{item['id']}: stan/zdarzenie spoza słownika")
        if item.get("form") not in ("A", "E", "I", "O"):
            errors.append(f"{item['id']}: niepoprawna forma zdania")
        if item.get("value") not in ("true", "false", "unresolved"):
            errors.append(f"{item['id']}: niepoprawny status zdania")
    else:
        nodes = set(states) | set(events) | set(guards)
        if item.get("type") not in ("requires", "excludes", "precedes"):
            errors.append(f"{item['id']}: niepoprawny typ krawędzi")
        if item.get("from") not in nodes or item.get("to") not in nodes:
            errors.append(f"{item['id']}: węzeł spoza słownika")
    return errors


def apply_diff(scaffold, diff, variant, vocabulary, requirement_ids, strict=True):
    """Stosuje diff. Zwraca (nowy_scaffold, błędy, zmienione_elementy).

    strict=True: każdy błąd (nieistniejące ID, element spoza słownika) odrzuca cały diff.
    strict=False (ablacja bez skryptu): błędne operacje są pomijane, reszta jest stosowana.
    zmienione_elementy to stare i nowe wersje elementów, których dotyczył diff (do strefy wpływu).
    """
    new = copy.deepcopy(scaffold)
    errors, changed = [], []

    def find(item_id):
        for s in "ARD":
            for i, item in enumerate(new[s]):
                if item["id"] == item_id:
                    return s, i
        return None, None

    for item_id in diff["remove"]:
        s, i = find(item_id)
        if s is None:
            errors.append(f"usuwany element {item_id} nie istnieje")
        else:
            changed.append(new[s].pop(i))

    known_ids = requirement_ids | {VOCABULARY_SOURCE} | {a["id"] for a in new["A"] + diff["add"]["A"]}
    for op in ("modify", "add"):
        for s in "ARD":
            for item in diff[op][s]:
                found_s, i = find(item["id"])
                problems = item_errors(s, item, variant, vocabulary, requirement_ids, known_ids)
                if op == "add" and found_s is not None:
                    problems.append(f"dodawany element {item['id']} już istnieje")
                if op == "modify" and found_s is None:
                    problems.append(f"zmieniany element {item['id']} nie istnieje")
                if problems:
                    errors += problems
                    continue
                if op == "modify":
                    changed.append(new[found_s].pop(i))
                new[s].append(item)
                changed.append(item)

    if strict and errors:
        return scaffold, errors, []
    return new, errors, changed


def unjustified(model_transitions, scaffold):
    """Przejścia modelu bez wpisu w D, którego wszystkie odnośniki wskazują istniejące A lub R."""
    ids = {x["id"] for x in scaffold["A"] + scaffold["R"]}
    justified = {
        tuple(d["transition"]) for d in scaffold["D"]
        if d["justified_by"] and all(ref in ids for ref in d["justified_by"])
    }
    return {t for t in model_transitions if t not in justified}


def requirements_of(items, scaffold, requirement_ids):
    """Wymagania, na których opierają się podane elementy R (bezpośrednio lub przez założenie A)."""
    assumptions = {a["id"]: a.get("source") for a in scaffold["A"]}
    result = set()
    for item in items:
        source = item.get("source")
        source = assumptions.get(source, source)
        if source in requirement_ids:
            result.add(source)
    return sorted(result)
