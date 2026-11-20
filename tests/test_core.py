import copy

from src import dataset, graph, metrics, square
from src import model as sm
from src import scaffold as sc

EXAMPLE = dataset.load_system("data/example/systems/orders.json")
VOCAB = EXAMPLE["vocabulary"]


def model_of(*ts):
    return {"states": VOCAB["states"], "initial": "New", "final": [],
            "transitions": [dict(zip(("from", "event", "guard", "to"), t)) for t in ts]}


# --- model ---

def test_requirement_tests_semantics():
    m = model_of(("New", "cancel", "before_24h", "Cancelled"), ("New", "cancel", "after_24h", "Cancelled"))
    always = {"type": "has_transition", "from": "New", "event": "cancel", "guard": None}
    assert sm.run_test(always, m, VOCAB)  # komplet pary warunków = zawsze dozwolone (ustalenie U3)
    m = model_of(("New", "cancel", "before_24h", "Cancelled"))
    assert not sm.run_test(always, m, VOCAB)
    assert sm.run_test({"type": "has_transition", "from": "New", "event": "cancel"}, m, VOCAB)
    assert sm.run_test({"type": "no_transition", "from": "New", "event": "cancel", "guard": "after_24h"}, m, VOCAB)
    assert not sm.run_test({"type": "has_transition", "from": "New", "event": "cancel", "to": "Shipped"}, m, VOCAB)


def test_always_before():
    m = model_of(("New", "pay", None, "Paid"), ("Paid", "ship", None, "Shipped"))
    assert sm.run_test({"type": "always_before", "state": "Shipped", "before": "Paid"}, m, VOCAB)
    m["transitions"].append({"from": "New", "event": "ship", "guard": None, "to": "Shipped"})
    assert not sm.run_test({"type": "always_before", "state": "Shipped", "before": "Paid"}, m, VOCAB)


def test_semantic_issues():
    m = model_of(("New", "cancel", "before_24h", "Cancelled"), ("New", "cancel", "in_stock", "Cancelled"),
                 ("New", "pay", None, "Payed"))
    issues = " ".join(sm.semantic_issues(m, VOCAB))
    assert "niedeterminizm" in issues and "spoza słownika" in issues and "nieosiągalne" in issues
    ok = model_of(("New", "cancel", "before_24h", "Cancelled"), ("New", "cancel", "after_24h", "Cancelled"))
    ok["states"] = ["New", "Cancelled"]
    assert sm.semantic_issues(ok, VOCAB) == []


# --- dataset ---

def test_example_dataset_is_valid():
    assert dataset.validate_system(EXAMPLE) == []


def test_validator_detects_inconsistent_gold():
    broken = copy.deepcopy(EXAMPLE)
    broken["steps"][1]["W"].pop()  # W bez przejścia wymaganego przez R7
    assert any("R7" in e for e in dataset.validate_system(broken))


def test_conflict_step_is_withdrawn():
    gold = dataset.gold_steps(EXAMPLE)
    assert gold[3]["conflict"] and gold[3]["W"] == gold[2]["W"]
    assert "R9" not in {r["id"] for r in gold[4]["requirements"]}


# --- kwadrat logiczny ---

def sentence(i, form, value, source="R1", state="Shipped", event="cancel"):
    return {"id": f"K{i}", "state": state, "event": event, "form": form, "value": value, "source": source}


def test_square_table():
    assert square.pair_status([sentence(1, "I", "false")]) == "never"
    assert square.pair_status([sentence(1, "I", "true")]) == "unresolved"
    assert square.pair_status([sentence(1, "I", "true"), sentence(2, "O", "true")]) == "conditional"
    assert square.pair_status([sentence(1, "A", "true"), sentence(2, "O", "true")]) == "conflict"
    assert square.pair_status([sentence(1, "E", "true"), sentence(2, "E", "false")]) == "conflict"


def test_square_conflict_maps_to_requirements():
    s = {"A": [{"id": "A1", "text": "", "status": "required", "source": "R9"}], "D": [],
         "R": [sentence(1, "E", "true", "R5"), sentence(2, "I", "true", "A1")]}
    conflicts, _ = square.check(s)
    assert len(conflicts) == 1
    assert sc.requirements_of(conflicts[0]["items"], s, {"R5", "R9"}) == ["R5", "R9"]


# --- graf ograniczeń ---

def edge(i, kind, a, b):
    return {"id": f"G{i}", "type": kind, "from": a, "to": b, "source": "R1"}


def test_graph_rules():
    trap = {"R": [edge(1, "requires", "ship", "in_stock"), edge(2, "excludes", "in_stock", "out_of_stock")]}
    assert graph.check(trap) == []  # „A requires B, B excludes C” nie jest konfliktem
    transitive = {"R": [edge(1, "requires", "cancel", "out_of_stock"), edge(2, "requires", "out_of_stock", "after_24h"),
                        edge(3, "requires", "cancel", "before_24h"), edge(4, "excludes", "before_24h", "after_24h")]}
    [c] = graph.check(transitive)
    assert {i["id"] for i in c["items"]} == {"G1", "G2", "G3", "G4"}
    direct = {"R": [edge(1, "requires", "a", "b"), edge(2, "requires", "b", "c"), edge(3, "excludes", "c", "a")]}
    assert len(graph.check(direct)) == 1
    cycle = {"R": [edge(1, "precedes", "Shipped", "Delivered"), edge(2, "precedes", "Delivered", "Shipped")]}
    [c] = graph.check(cycle)
    assert {i["id"] for i in c["items"]} == {"G1", "G2"}


def test_influence_zone():
    s = {"R": [edge(1, "requires", "ship", "in_stock"), edge(2, "precedes", "New", "Paid")]}
    zone = graph.influence_zone(s, [edge(1, "requires", "ship", "in_stock")])
    assert zone == {"ship", "in_stock"}


# --- diff ---

def test_apply_diff():
    base = {"A": [{"id": "A1", "text": "", "status": "required", "source": "R1"}], "D": [],
            "R": [sentence(1, "I", "true", "A1")]}
    empty = {"A": [], "R": [], "D": []}
    diff = {"add": {**empty, "R": [sentence(2, "O", "true", "R2")]},
            "modify": {**empty, "R": [sentence(1, "I", "false", "A1")]}, "remove": []}
    new, errors, changed = sc.apply_diff(base, diff, "M1", VOCAB, {"R1", "R2"})
    assert errors == [] and len(new["R"]) == 2 and len(changed) == 3

    bad = {"add": empty, "modify": empty, "remove": ["K99"]}
    new, errors, _ = sc.apply_diff(base, bad, "M1", VOCAB, {"R1"})
    assert errors and new is base  # odrzucony w całości

    bad = {"add": {**empty, "R": [sentence(3, "I", "true", "R7")]}, "modify": empty, "remove": ["A1"]}
    new, errors, _ = sc.apply_diff(base, bad, "M1", VOCAB, {"R1"}, strict=False)
    assert errors and new["A"] == []  # ablacja: błędny element pominięty, reszta zastosowana


def test_unjustified():
    s = {"A": [{"id": "A1"}], "R": [],
         "D": [{"id": "D1", "transition": ["New", "pay", None, "Paid"], "justified_by": ["A1"]},
               {"id": "D2", "transition": ["New", "cancel", None, "Cancelled"], "justified_by": ["A7"]}]}
    T = {("New", "pay", None, "Paid"), ("New", "cancel", None, "Cancelled")}
    assert sc.unjustified(T, s) == {("New", "cancel", None, "Cancelled")}


# --- metryki ---

def record(W, result="OK"):
    return {"model": dataset.gold_model(EXAMPLE, W), "result": result, "conflicting": [], "calls": []}


def test_metrics_perfect_and_regression():
    gold = dataset.gold_steps(EXAMPLE)
    prev, cur = record(gold[0]["W"]), record(gold[1]["W"])
    m = metrics.step_metrics(EXAMPLE, gold, 1, cur, prev)
    assert m["requirement_satisfaction"] == 1 and m["f1"] == 1 and m["fully_correct"]
    assert m["add_coverage"] == 1 and m["functional_regressions"] == 0 and m["unnecessary_changes"] == 0

    # Model dodaje zwrot, ale gubi wysyłkę (R4) i dodaje anulowanie wysłanego (halucynacja).
    W = set(gold[1]["W"]) - {("Paid", "ship", None, "Shipped")} | {("Shipped", "cancel", None, "Cancelled")}
    m = metrics.step_metrics(EXAMPLE, gold, 1, record(W), prev)
    assert m["functional_regressions"] == 2  # R4 i R5
    assert m["structural_regressions"] == 2
    assert m["hallucinations"] == 1 and m["unnecessary_changes"] == 2


def test_metrics_deletion_and_conflict():
    gold = dataset.gold_steps(EXAMPLE)
    # Krok 5 usuwa R7; poprzedni model miał też dopuszczalny zwrot po 24 h - on również jest do usunięcia.
    prev = record(set(gold[4]["W"]) | set(gold[4]["P"]))
    m = metrics.step_metrics(EXAMPLE, gold, 5, record(set(gold[5]["W"]) | {("Delivered", "return", "after_24h", "Returned")}), prev)
    assert m["delete_coverage"] == 0.5

    prev = record(gold[2]["W"])
    conflict = record(gold[2]["W"], result="CONFLICT")
    conflict["conflicting"] = ["R5", "R9"]
    m = metrics.step_metrics(EXAMPLE, gold, 3, conflict, prev)
    assert m["conflict_step_correct"] and m["conflict_list_jaccard"] == 1


def test_f1_is_zero_for_wrong_or_empty_model():
    gold = dataset.gold_steps(EXAMPLE)
    wrong = record({("New", "pay", None, "Cancelled")})
    assert metrics.step_metrics(EXAMPLE, gold, 0, wrong, None)["f1"] == 0
    assert metrics.step_metrics(EXAMPLE, gold, 0, record(set()), None)["f1"] == 0
