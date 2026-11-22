"""Metryki z sekcji „Metryki” konspektu, liczone dla jednego kroku jednej sekwencji."""
from src import model as sm
from src import scaffold as sc


def ratio(a, b):
    return a / b if b else None


def status(t, W, P):
    return "required" if t in W else "allowed" if t in P else "forbidden"


def correct(t, T, W, P):
    s = status(t, W, P)
    return s == "allowed" or (t in T) == (s == "required")


def step_metrics(system, gold, k, rec, prev_rec):
    """gold: wynik dataset.gold_steps; rec/prev_rec: rekordy wariantu z kroków k i k-1."""
    vocab = system["vocabulary"]
    g = gold[k]
    gp = gold[k - 1] if k > 0 else {"W": set(), "P": set(), "requirements": []}
    W, P, Wp, Pp = g["W"], g["P"], gp["W"], gp["P"]
    T = sm.transitions(rec["model"])
    prev_model = prev_rec["model"] if prev_rec else sm.EMPTY_MODEL
    Tp = sm.transitions(prev_model)

    # Metryka główna: odsetek zatwierdzonych wymagań, których testy przechodzą.
    passed = {r["id"]: sm.requirement_passes(r, rec["model"], vocab) for r in g["requirements"]}
    passed_prev = {r["id"]: sm.requirement_passes(r, prev_model, vocab) for r in gp["requirements"]}

    precision = ratio(len(T & (W | P)), len(T))
    recall = ratio(len(T & W), len(W))
    # F1 = 0, gdy precyzja i czułość są zerowe albo model jest pusty (wtedy czułość = 0).
    # Pusta wartość tylko wtedy, gdy W jest puste (czułość nieokreślona).
    if recall is None:
        f1 = None
    elif not precision or not recall:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)

    add = W - Wp
    delete = {t for t in Wp | Pp if t not in W | P and (t in Wp or t in Tp)}
    unnecessary = (Tp ^ T) - (add | delete)
    hallucinations = T - (W | P)

    validation = sm.validation_errors(rec["model"], vocab, system["initial"])
    m = {
        "requirement_satisfaction": ratio(sum(passed.values()), len(passed)),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "fully_correct": not validation and W <= T <= W | P,
        "model_valid": not validation,
        "model_validation_errors": len(validation),
        "add_coverage": ratio(len(add & T), len(add)),
        "delete_coverage": ratio(len(delete - T), len(delete)),
        "functional_regressions": sum(
            1 for rid, ok in passed.items()
            if not ok and passed_prev.get(rid) and rid not in g["affects"]) if k > 0 else 0,
        "structural_regressions": sum(
            1 for t in W | P | Wp | Pp | T | Tp
            if status(t, W, P) == status(t, Wp, Pp) and correct(t, Tp, Wp, Pp) and not correct(t, T, W, P)
        ) if k > 0 else 0,
        "hallucinations": len(hallucinations),
        "unnecessary_changes": len(unnecessary),
        "model_issues": len(sm.semantic_issues(rec["model"], vocab, system["initial"])),
    }

    if "scaffold" in rec:  # warianty M1/M2
        no_reason = sc.unjustified(T, rec["scaffold"])
        m["strict_hallucinations"] = len(hallucinations & no_reason)
        m["scaffold_justified_errors"] = len(hallucinations - no_reason)
        m["unjustified_decisions"] = ratio(len(no_reason), len(T))
        m["script_conflicts"] = len(rec.get("gamma_conflicts") or [])
        m["script_blocked"] = rec["result"] in ("CONFLICT", "REJECTED")
        m["diff_rejected"] = rec["result"] == "REJECTED"
    if "zone" in rec:  # M2: ile zmian zbędnych leży poza strefą wpływu
        zone = set(rec["zone"])
        m["unnecessary_outside_zone"] = sum(1 for t in unnecessary if not zone & set(t))

    # Wykrywanie konfliktów: krok konfliktowy jest poprawny, gdy CONFLICT i model niezmieniony.
    detected = rec["result"] == "CONFLICT"
    m["conflict_expected"] = g["conflict"]
    m["conflict_detected"] = detected
    m["conflict_step_correct"] = (detected and T == Tp) if g["conflict"] else None
    m["conflict_list_jaccard"] = jaccard(rec["conflicting"], g["conflicting"]) if g["conflict"] and detected else None
    m.update(cost(rec))
    return m


def jaccard(a, b):
    a, b = set(a), set(b)
    return ratio(len(a & b), len(a | b))


def cost(rec):
    attempts = [a for call in rec["calls"] for a in call["attempts"]]
    return {
        "llm_calls": len(attempts),
        "retries": len(attempts) - len(rec["calls"]),
        "tokens": sum(a["prompt_tokens"] + a["output_tokens"] for a in attempts),
        "seconds": sum(a["seconds"] for a in attempts),
    }
