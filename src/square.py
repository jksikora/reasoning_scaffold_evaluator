"""Γ dla kwadratu logicznego (M1): tabela trzech stanów pary (stan, zdarzenie).

Elementy R: {"id": "K1", "state": s, "event": e, "form": "A|E|I|O",
             "value": "true|false|unresolved", "source": "R1" lub "A1"}.
Zdania, których LLM nie podał, są nierozstrzygnięte (nie fałszywe).
"""
from collections import defaultdict

ROWS = {
    "always":    {"A": True,  "E": False, "I": True,  "O": False},
    "never":     {"A": False, "E": True,  "I": False, "O": True},
    "conditional": {"A": False, "E": False, "I": True,  "O": True},
}


def pair_status(sentences):
    """Status pary na podstawie jej zdań: 'conflict', nazwa wiersza albo 'unresolved'."""
    values = defaultdict(set)
    for s in sentences:
        if s["value"] != "unresolved":
            values[s["form"]].add(s["value"] == "true")
    if any(len(v) > 1 for v in values.values()):
        return "conflict"
    known = {form: next(iter(v)) for form, v in values.items()}
    rows = [name for name, row in ROWS.items() if all(row[f] == val for f, val in known.items())]
    if not rows:
        return "conflict"
    return rows[0] if len(rows) == 1 else "unresolved"


def check(scaffold):
    """Zwraca (konflikty, statusy_par). Konflikt: {"pair": [s, e], "items": [elementy R]}."""
    pairs = defaultdict(list)
    for s in scaffold["R"]:
        pairs[(s["state"], s["event"])].append(s)
    conflicts, statuses = [], {}
    for pair, sentences in sorted(pairs.items()):
        status = pair_status(sentences)
        statuses[pair] = status
        if status == "conflict":
            conflicts.append({"pair": list(pair), "items": sentences})
    return conflicts, statuses
