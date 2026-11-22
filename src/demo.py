"""Offline: demonstracja raportu na zaplanowanych odpowiedziach, NIE wyniki LLM.

python -m src.demo --out results/demo_mock
"""
import argparse
import copy
import json
from collections import deque
from pathlib import Path
from unittest.mock import patch

from src import analysis, dataset, run


def diff(edges=None, remove=None):
    return {"add": {"A": [], "R": edges or [], "D": []},
            "modify": {"A": [], "R": [], "D": []}, "remove": remove or []}


def sentence(system, value="E", ident="K1", source="R4"):
    return {"id": ident, "state": system["vocabulary"]["states"][2],
            "event": system["vocabulary"]["events"][3], "form": value, "value": "true", "source": source}


def edge(ident, kind, a, b, source):
    return {"id": ident, "type": kind, "from": a, "to": b, "source": source}


def state_edges(system, change=False):
    c = system["vocabulary"]["states"][2]
    ex = system["vocabulary"]["events"][3]
    return [edge("G2", "requires", ex, c, "R8")] if change else [edge("G1", "excludes", ex, c, "R4")]


def queue_answers(systems, conflicts, reps, done_seq=None, done_z=None):
    done_seq, done_z = done_seq or set(), done_z or set()
    answers = deque()
    variants = ["B1", "B2", "M1", "M2"]
    for system in systems:
        gold = dataset.gold_steps(system)
        for variant in variants:
            for rep in range(reps):
                if all((system["system"], variant, rep, k) in done_seq for k in range(len(system["steps"]))):
                    continue
                for k, step in enumerate(system["steps"]):
                    conflict = step["type"] == "contradiction"
                    rejected = variant == "M1" and system["system"] == "library" and step["type"] == "new_dependency"
                    model = dataset.gold_model(system, gold[k]["W"])
                    # Celowo różne, syntetyczne błędy do sprawdzenia prezentacji.
                    if variant == "B1" and system["system"] == "library" and k >= 2:
                        model["initial"] = "Bogus"
                    if variant == "B1" and system["system"] == "access" and k % 2 and rep == 0:
                        model["transitions"] = model["transitions"][:-1]
                    if variant == "B2":
                        answers.append("DEMO: zaplanowana analiza, bez wywołania LLM.")
                    if variant.startswith("B"):
                        answers.append({"result": "CONFLICT" if conflict else "OK",
                                        "conflicting": step.get("conflicting", []), "model": None if conflict else model})
                    else:
                        edges = []
                        if k == 0:
                            edges = [sentence(system)] if variant == "M1" else state_edges(system)
                        elif conflict:
                            edges = [sentence(system, "I", "K2", "R8")] if variant == "M1" else state_edges(system, True)
                        answers.append(diff(edges, ["K_missing"] if rejected else None))
                        if not conflict and not rejected:
                            answers.append({"model": model})
    for system in systems:
        c, d = system["vocabulary"]["states"][2:4]
        e = system["vocabulary"]["events"][1]
        g, ng, h, _ = system["vocabulary"]["guards"]
        for case in conflicts[system["system"]]:
            for variant in variants:
                for rep in range(reps):
                    if (system["system"], case["id"], variant, rep) in done_z:
                        continue
                    if variant.startswith("B"):
                        if variant == "B2":
                            answers.append("DEMO: zaplanowana analiza przypadku Z.")
                        conflict = case["kind"] != "trap"
                        answers.append({"result": "CONFLICT" if conflict else "OK",
                                        "conflicting": case.get("conflicting", []),
                                        "model": None if conflict else dataset.gold_model(system, dataset.tuples(system["steps"][0]["W"]))})
                    elif variant == "M1":
                        answers.append(diff([sentence(system)]))
                        answers.append(diff([sentence(system, "I", "K2", "R8")]) if case["kind"] == "state" else diff())
                    else:
                        if case["kind"] == "state":
                            base, change = state_edges(system), state_edges(system, True)
                        elif case["kind"] == "transitive":
                            base = [edge("G1", "requires", e, g, "R2"), edge("G2", "excludes", g, ng, "vocabulary")]
                            change = [edge("G3", "requires", e, h, "R9"), edge("G4", "requires", h, ng, "R9")]
                        elif case["kind"] == "ordering":
                            base = [edge("G1", "precedes", c, d, "R5")]
                            change = [edge("G2", "precedes", d, c, "R10")]
                        else:
                            base, change = [], []
                        answers.extend([diff(base), diff(change)])
    return answers


def main(out):
    systems, conflicts = dataset.validated_load("data/pilot")
    out = Path(out)
    seq_key = lambda r: (r["system"], r["variant"], r["rep"], r["step"])
    z_key = lambda r: (r["system"], r["case"], r["variant"], r["rep"])
    done_seq = {seq_key(r) for r in analysis.read_jsonl(out / "sequences.jsonl", seq_key)}
    done_z = {z_key(r) for r in analysis.read_jsonl(out / "z.jsonl", z_key)}
    answers = queue_answers(systems, conflicts, reps=2, done_seq=done_seq, done_z=done_z)

    def chat(prompt, schema=None):
        answer = copy.deepcopy(answers.popleft())
        return {"text": answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False),
                "prompt_tokens": 100, "output_tokens": 50, "seconds": 0.1}

    info = {"model": "MOCK_DEMO_OFFLINE", "digest": "0" * 64, "temperature": 0.2,
            "num_ctx": 8192, "num_predict": 4096, "base_url": "mock://offline"}
    argv = ["demo", "--data", "data/pilot", "--out", str(out), "--reps", "2"]
    with patch("sys.argv", argv), patch("src.llm.model_info", return_value=info), patch("src.llm.chat", side_effect=chat):
        run.main()
    if answers:
        raise RuntimeError("Demonstracja nie wykorzystała wszystkich zaplanowanych odpowiedzi")
    # Przy ponownym uruchomieniu cały ukończony przebieg jest pomijany.
    analysis.main(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="results/demo_mock")
    main(parser.parse_args().out)
