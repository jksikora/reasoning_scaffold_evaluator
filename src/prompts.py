"""Budowanie promptów ze wspólnego szablonu i schematy JSON wymuszające format odpowiedzi."""
import json
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _fill(text, values):
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def _dump(obj):
    return json.dumps(obj, ensure_ascii=False)


def describe_change(change, initial=False):
    if initial:
        lines = ["Wymagania początkowe (pierwszy model systemu):"]
    else:
        lines = [change["description"]]
        if change.get("add"):
            lines.append("Nowe lub zmienione wymagania:")
    lines += [f"- {r['id']}: {r['text']}" for r in change.get("add", [])]
    if change.get("remove"):
        lines.append("Usunięte wymagania: " + ", ".join(change["remove"]))
    return "\n".join(lines)


def render(section, system, requirements, model, change, initial=False, **extra):
    """Pełny prompt: wspólny szablon + środkowa sekcja wariantu (plik prompts/<section>.md).

    extra: wartości dla znaczników sekcji (previous, analysis, scaffold).
    """
    vocab = system["vocabulary"]
    section_text = _fill((PROMPTS_DIR / f"{section}.md").read_text(encoding="utf-8"), extra)
    values = {
        "system": system["system"],
        "states": ", ".join(vocab["states"]),
        "events": ", ".join(vocab["events"]),
        "guards": ", ".join(vocab["guards"]),
        "exclusive": "; ".join(f"{a} ↔ {b}" for a, b in vocab["exclusive"]),
        "initial": system["initial"],
        "requirements": "\n".join(f"- {r['id']}: {r['text']}" for r in requirements) or "(brak)",
        "model": _dump(model) if model["transitions"] else "(brak – to będzie pierwszy model)",
        "change": describe_change(change, initial),
        "section": section_text,
    }
    return _fill((PROMPTS_DIR / "template.md").read_text(encoding="utf-8"), values)


# --- Schematy JSON (Ollama wymusza zgodność generowanej odpowiedzi ze schematem) ---

STR = {"type": "string"}
STR_OR_NULL = {"type": ["string", "null"]}
STR_LIST = {"type": "array", "items": STR}


def _object(**props):
    return {"type": "object", "properties": props, "required": list(props)}


MODEL = _object(
    states=STR_LIST,
    initial=STR,
    final=STR_LIST,
    transitions={"type": "array", "items": _object(**{"from": STR, "event": STR, "guard": STR_OR_NULL, "to": STR})},
)

B_RESULT = _object(
    result={"enum": ["OK", "CONFLICT"]},
    conflicting=STR_LIST,
    model={"anyOf": [MODEL, {"type": "null"}]},
)

M_MODEL = _object(model=MODEL)

_A = _object(id=STR, text=STR, status={"enum": ["required", "inferred", "unresolved"]}, source=STR_OR_NULL)
_D = _object(id=STR, transition={"type": "array", "items": STR_OR_NULL, "minItems": 4, "maxItems": 4},
             justified_by=STR_LIST)
_R = {
    "M1": _object(id=STR, state=STR, event=STR, form={"enum": ["A", "E", "I", "O"]},
                  value={"enum": ["true", "false", "unresolved"]}, source=STR),
    "M2": _object(id=STR, type={"enum": ["requires", "excludes", "precedes"]}, **{"from": STR, "to": STR}, source=STR),
}


def diff_schema(variant):
    sections = _object(A={"type": "array", "items": _A}, R={"type": "array", "items": _R[variant]},
                       D={"type": "array", "items": _D})
    return _object(add=sections, modify=sections, remove=STR_LIST)
