"""Maszyna stanów w JSON: walidacja i testy wymagań."""

EMPTY_MODEL = {"states": [], "initial": None, "final": [], "transitions": []}


def transitions(model):
    """Zbiór przejść modelu jako krotek (skąd, zdarzenie, warunek, dokąd)."""
    return {(t["from"], t["event"], t["guard"], t["to"]) for t in model["transitions"]}


def shape_errors(model):
    """Błędy struktury JSON (powód do ponowienia zapytania)."""
    if not isinstance(model, dict):
        return ["model nie jest obiektem"]
    errors = []
    for key, typ in [("states", list), ("final", list), ("transitions", list)]:
        if not isinstance(model.get(key), typ):
            errors.append(f"brak listy '{key}'")
    if not isinstance(model.get("initial"), str):
        errors.append("brak pola 'initial'")
    for key in ("states", "final"):
        if isinstance(model.get(key), list) and not all(isinstance(x, str) for x in model[key]):
            errors.append(f"lista '{key}' musi zawierać nazwy stanów")
    for t in model.get("transitions", []) if isinstance(model.get("transitions"), list) else []:
        if not isinstance(t, dict) or any(k not in t for k in ("from", "event", "guard", "to")):
            errors.append(f"niepoprawne przejście: {t}")
        elif not all(isinstance(t[k], str) for k in ("from", "event", "to")) or not (
            t["guard"] is None or isinstance(t["guard"], str)
        ):
            errors.append(f"niepoprawne typy w przejściu: {t}")
    return errors


def exclusive(g1, g2, vocabulary):
    return [g1, g2] in vocabulary["exclusive"] or [g2, g1] in vocabulary["exclusive"]


def validation_errors(model, vocabulary, expected_initial=None):
    """Błędy maszyny; nie zmieniają surowych testów wymagań ani historii wariantu."""
    issues = shape_errors(model)
    if issues:
        return issues
    states = set(model["states"])
    for key in ("states", "final"):
        if len(model[key]) != len(set(model[key])):
            issues.append(f"powtórzone stany w {key}")
    if not states:
        issues.append("pusta lista stanów")
    if not states <= set(vocabulary["states"]):
        issues.append("zadeklarowane stany spoza słownika")
    if model["initial"] not in states:
        issues.append("stan początkowy nie jest zadeklarowany")
    if expected_initial is not None and model["initial"] != expected_initial:
        issues.append("stan początkowy niezgodny z systemem")
    if not set(model["final"]) <= states:
        issues.append("stany końcowe nie są zadeklarowane")
    for t in sorted(transitions(model), key=str):
        s, e, g, d = t
        if s not in states or d not in states:
            issues.append(f"koniec przejścia nie jest zadeklarowany: {t}")
        if s not in vocabulary["states"] or d not in vocabulary["states"]:
            issues.append(f"stan spoza słownika: {t}")
        if e not in vocabulary["events"]:
            issues.append(f"zdarzenie spoza słownika: {t}")
        if g is not None and g not in vocabulary["guards"]:
            issues.append(f"warunek spoza słownika: {t}")

    # Determinizm: dwa przejścia z tego samego (s, e) tylko przy wykluczających się warunkach.
    ts = sorted(transitions(model), key=str)
    for i, a in enumerate(ts):
        for b in ts[i + 1:]:
            if a[:2] == b[:2] and not (a[2] and b[2] and exclusive(a[2], b[2], vocabulary)):
                issues.append(f"niedeterminizm: {a} i {b}")

    return issues


def semantic_issues(model, vocabulary, expected_initial=None):
    """Błędy walidacji i ostrzeżenia o osiągalności; nie blokują przyjęcia modelu."""
    issues = validation_errors(model, vocabulary, expected_initial)
    if shape_errors(model):
        return issues
    # Założenie egzystencjalne kwadratu: każdy stan modelu jest osiągalny.
    unreachable = set(model["states"]) - reachable(model)
    if unreachable:
        issues.append(f"stany nieosiągalne: {sorted(unreachable)}")
    return issues


def reachable(model, without=None):
    """Stany osiągalne ze stanu początkowego (opcjonalnie z pominięciem stanu `without`)."""
    start = model["initial"]
    if start is None or start == without:
        return set()
    seen, todo = {start}, [start]
    while todo:
        s = todo.pop()
        for t in model["transitions"]:
            if t["from"] == s and t["to"] != without and t["to"] not in seen:
                seen.add(t["to"])
                todo.append(t["to"])
    return seen


def _matching(model, test):
    found = [t for t in transitions(model) if t[0] == test["from"] and t[1] == test["event"]]
    if "to" in test:
        found = [t for t in found if t[3] == test["to"]]
    return found


def _allowed(model, test, vocabulary):
    """Czy zdarzenie jest dozwolone w sytuacji opisanej polem 'guard' testu.

    - brak klucza 'guard': w jakiejkolwiek sytuacji (istnieje przejście),
    - 'guard': g: w sytuacji, w której zachodzi g (przejście z g albo bez warunku),
    - 'guard': null: w każdej sytuacji (przejście bez warunku albo komplet wykluczających
      się warunków z jednej pary, por. README, ustalenie U3).
    """
    found = _matching(model, test)
    if "guard" not in test:
        return bool(found)
    guards = {t[2] for t in found}
    if None in guards:
        return True
    if test["guard"] is not None:
        return test["guard"] in guards
    return any(a in guards and b in guards for a, b in vocabulary["exclusive"])


def run_test(test, model, vocabulary):
    kind = test["type"]
    if kind == "has_transition":
        return _allowed(model, test, vocabulary)
    if kind == "no_transition":
        return not _allowed(model, test, vocabulary)
    if kind == "reachable":
        return test["state"] in reachable(model)
    if kind == "always_before":
        # Każda droga do 'state' przechodzi przez 'before'.
        return test["state"] not in reachable(model, without=test["before"])
    raise ValueError(f"nieznany typ testu: {kind}")


TEST_TYPES = {"has_transition", "no_transition", "reachable", "always_before"}


def requirement_passes(requirement, model, vocabulary):
    return all(run_test(t, model, vocabulary) for t in requirement["tests"])
