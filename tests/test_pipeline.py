"""Integracja runnera i analizy z podstawionym LLM, który zwraca zaplanowane odpowiedzi."""
import json

import pytest

from src import analysis, dataset, llm, run

EXAMPLE = dataset.load_system("data/example/systems/orders.json")
EMPTY = {"A": [], "R": [], "D": []}


@pytest.fixture
def fake_llm(monkeypatch):
    """Kolejka odpowiedzi; każde wywołanie llm.chat zdejmuje kolejną (dict -> JSON, str -> tekst)."""
    queue, prompts = [], []

    def chat(prompt, schema=None):
        prompts.append(prompt)
        answer = queue.pop(0)
        text = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
        return {"text": text, "prompt_tokens": 10, "output_tokens": 5, "seconds": 0.1}

    monkeypatch.setattr(llm, "chat", chat)
    monkeypatch.setattr(llm, "model_info", lambda: {"model": "fake", "digest": "0" * 12,
                                                    "temperature": 0.2, "num_ctx": 0})
    return queue, prompts


def gold_model(k):
    return dataset.gold_model(EXAMPLE, dataset.gold_steps(EXAMPLE)[k]["W"])


def test_b1_perfect_sequence_and_analysis(fake_llm, tmp_path, monkeypatch):
    queue, prompts = fake_llm
    queue += ["to nie jest JSON", {"result": "OK", "conflicting": [], "model": gold_model(0)}]  # 1 ponowienie
    queue += [{"result": "OK", "conflicting": [], "model": gold_model(k)} for k in (1, 2)]
    queue += [{"result": "CONFLICT", "conflicting": ["R5", "R9"], "model": None}]
    queue += [{"result": "OK", "conflicting": [], "model": gold_model(k)} for k in (4, 5)]
    out = tmp_path / "wyniki"
    monkeypatch.setattr("sys.argv", ["run", "--data", "data/example", "--out", str(out), "--variants", "B1",
                                     "--reps", "1", "--part", "sequences"])
    run.main()
    assert not queue
    # Krok 4 widzi zatwierdzony model z kroku 2 i nie widzi wycofanego R9 na liście wymagań.
    assert "R9" not in prompts[5].split("## Zmiana")[0]

    analysis.main(out)
    rows = list(analysis.csv.DictReader((out / "steps.csv").open(encoding="utf-8")))
    assert [r["result"] for r in rows] == ["OK", "OK", "OK", "CONFLICT", "OK", "OK"]
    assert all(float(r["requirement_satisfaction"]) == 1 for r in rows)
    assert rows[0]["retries"] == "1"
    assert (out / "report.md").exists() and (out / "plot_requirement_satisfaction.png").exists()


def test_m1_detects_state_conflict_in_z(fake_llm):
    queue, _ = fake_llm
    build = {"add": {"A": [], "D": [],
                     "R": [{"id": "K1", "state": "Shipped", "event": "cancel", "form": "E",
                            "value": "true", "source": "R5"}]},
             "modify": EMPTY, "remove": []}
    change = {"add": {**EMPTY, "R": [{"id": "K2", "state": "Shipped", "event": "cancel", "form": "I",
                                      "value": "true", "source": "R9"}]},
              "modify": EMPTY, "remove": []}
    queue += [build, change]
    case = json.load(open("data/example/conflicts/orders.json"))["cases"][0]
    rec = run.run_z_case(EXAMPLE, case, "M1", 0)
    assert rec["result"] == "CONFLICT" and rec["conflicting"] == ["R5", "R9"]
    assert len(rec["calls"]) == 2  # w zestawie Z bez generowania modelu


def test_m2_sequence_step_with_rejected_diff(fake_llm):
    queue, _ = fake_llm
    queue += [{"add": EMPTY, "modify": EMPTY, "remove": ["G7"]}]  # nieistniejące ID -> skrypt odrzuca
    ctx = run.new_context()
    rec = run.run_step("M2", EXAMPLE, ctx, [], EXAMPLE["steps"][0], initial=True)
    assert rec["result"] == "REJECTED" and rec["model"]["transitions"] == []


def test_m2_ok_step_generates_model_and_zone(fake_llm):
    queue, _ = fake_llm
    diff = {"add": {"A": [{"id": "A1", "text": "wysyłka po opłaceniu", "status": "required", "source": "R4"}],
                    "R": [{"id": "G1", "type": "precedes", "from": "Paid", "to": "Shipped", "source": "A1"}],
                    "D": [{"id": "D1", "transition": ["Paid", "ship", None, "Shipped"], "justified_by": ["G1"]}]},
            "modify": EMPTY, "remove": []}
    queue += [diff, {"model": gold_model(0)}]
    ctx = run.new_context()
    rec = run.run_step("M2", EXAMPLE, ctx, [], EXAMPLE["steps"][0], initial=True)
    assert rec["result"] == "OK" and set(rec["zone"]) == {"Paid", "Shipped", "ship"}
    assert ctx["scaffold"]["D"][0]["id"] == "D1"
