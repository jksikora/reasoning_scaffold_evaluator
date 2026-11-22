"""Zabezpieczenia pilotażu i odtwarzalności; wszystkie wywołania LLM są podstawione."""
import copy
import csv
import json
import shutil
from argparse import Namespace
from pathlib import Path
from unittest.mock import Mock

import pytest

from src import analysis, dataset, demo, experiment, llm, metrics, model, run

EXAMPLE = dataset.load_system("data/example/systems/orders.json")


def args(**changes):
    values = dict(data="data/example", variants=["B1"], reps=1, systems=None, steps=2, part="sequences")
    return Namespace(**(values | changes))


def info():
    return dict(model="fake", digest="0" * 64, temperature=0.2, num_ctx=8192,
                num_predict=4096, base_url="mock://offline")


def manifest(**changes):
    return experiment.build_config(args(**changes), [EXAMPLE], {"orders": []}, info())


@pytest.mark.parametrize("extra", [
    ["--data", "data/main"], ["--data", "does-not-exist"],
    ["--data", "data/example", "--systems", "unknown"],
    ["--data", "data/example", "--reps", "0"],
    ["--data", "data/example", "--steps", "-1"],
])
def test_invalid_invocation_does_not_contact_llm_or_write(extra, tmp_path, monkeypatch):
    probe = Mock(side_effect=AssertionError("LLM nie może być wywołany"))
    monkeypatch.setattr(llm, "model_info", probe)
    monkeypatch.setattr(llm, "chat", probe)
    out = tmp_path / "out"
    monkeypatch.setattr("sys.argv", ["run", "--out", str(out)] + extra)
    with pytest.raises(SystemExit) as error:
        run.main()
    assert error.value.code == 2
    assert not out.exists()
    probe.assert_not_called()


def test_bad_dataset_fails_before_output(tmp_path, monkeypatch):
    root = tmp_path / "data"
    (root / "systems").mkdir(parents=True)
    broken = copy.deepcopy(EXAMPLE)
    broken["steps"][0]["W"] = []
    (root / "systems" / "broken.json").write_text(json.dumps(broken))
    probe = Mock()
    monkeypatch.setattr(llm, "model_info", probe)
    out = tmp_path / "out"
    monkeypatch.setattr("sys.argv", ["run", "--data", str(root), "--out", str(out)])
    with pytest.raises(SystemExit):
        run.main()
    assert not out.exists()
    probe.assert_not_called()


def test_invalid_model_keeps_raw_requirement_score():
    gold = dataset.gold_steps(EXAMPLE)
    m = dataset.gold_model(EXAMPLE, gold[0]["W"])
    m.update(initial="Bogus", states=[])
    rec = {"model": m, "result": "OK", "calls": [], "conflicting": [], "model_issues": []}
    measured = metrics.step_metrics(EXAMPLE, gold, 0, rec, None)
    assert measured["requirement_satisfaction"] == 1
    assert not measured["model_valid"]
    assert not measured["fully_correct"]
    assert measured["model_validation_errors"] > 0
    assert measured["model_issues"] > 0  # przeliczone, mimo pustej starej listy


@pytest.mark.parametrize("field,value", [
    ("states", ["New", "New"]), ("states", ["New", "Bogus"]),
    ("final", ["Bogus"]), ("final", ["New", "New"]), ("initial", "Paid"),
])
def test_validation_checks_declarations(field, value):
    m = dataset.gold_model(EXAMPLE, dataset.gold_steps(EXAMPLE)[0]["W"])
    m[field] = value
    assert model.validation_errors(m, EXAMPLE["vocabulary"], EXAMPLE["initial"])


def test_unreachable_is_only_a_warning():
    m = dataset.gold_model(EXAMPLE, dataset.gold_steps(EXAMPLE)[0]["W"])
    m["states"].append("Returned")
    assert model.validation_errors(m, EXAMPLE["vocabulary"], EXAMPLE["initial"]) == []
    assert any("nieosiągalne" in e for e in model.semantic_issues(m, EXAMPLE["vocabulary"]))


def test_invalid_model_is_accepted_in_variant_history(monkeypatch):
    m = dataset.gold_model(EXAMPLE, dataset.gold_steps(EXAMPLE)[0]["W"])
    m.update(initial="Bogus", states=[])
    answer = {"result": "OK", "conflicting": [], "model": m}
    monkeypatch.setattr(llm, "chat", lambda *a: {"text": json.dumps(answer), "prompt_tokens": 1,
                                                "output_tokens": 1, "seconds": 0.1})
    ctx = run.new_context()
    rec = run.run_step("B1", EXAMPLE, ctx, [], EXAMPLE["steps"][0], True)
    assert ctx["model"] == m and rec["result"] == "OK"
    assert rec["model_valid"] is False
    assert rec["model_validation_errors"]


def test_resume_identical_is_noop(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setattr(llm, "model_info", info)
    response = {"result": "OK", "conflicting": [],
                "model": dataset.gold_model(EXAMPLE, dataset.gold_steps(EXAMPLE)[0]["W"])}
    chat = Mock(return_value={"text": json.dumps(response), "prompt_tokens": 1,
                              "output_tokens": 1, "seconds": 0.1})
    monkeypatch.setattr(llm, "chat", chat)
    monkeypatch.setattr("sys.argv", ["run", "--data", "data/example", "--out", str(out),
                                     "--variants", "B1", "--reps", "1", "--steps", "1", "--part", "sequences"])
    run.main()
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    run.main()
    assert chat.call_count == 1
    assert before == {p.name: p.read_bytes() for p in out.iterdir()}


@pytest.mark.parametrize("change", ["model", "num_predict", "data", "source", "reps", "steps", "variants", "part"])
def test_resume_rejects_changed_configuration_without_writing(tmp_path, monkeypatch, change):
    config, snapshot = manifest()
    experiment.prepare(tmp_path, config, snapshot)
    (tmp_path / "sequences.jsonl").write_text("history\n")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    if change == "source":
        monkeypatch.setattr(experiment, "source_hashes", lambda: {"prompts/template.md": "changed"})
    changes = {"reps": 2} if change == "reps" else {"steps": 1} if change == "steps" else {}
    if change == "variants": changes["variants"] = ["B1", "M1"]
    if change == "part": changes["part"] = "all"
    new, frozen = manifest(**changes)
    if change in ("model", "num_predict"):
        new["llm"][change] = "other" if change == "model" else 128
    if change == "data":
        frozen["systems"][0] = copy.deepcopy(EXAMPLE)
        frozen["systems"][0]["note"] = "zmienione dane"
        new["dataset_hash"] = experiment.digest(frozen)
    new["fingerprint"] = experiment.digest({k: v for k, v in new.items() if k not in ("data", "fingerprint")})
    with pytest.raises(ValueError, match="nowego katalogu"):
        experiment.prepare(tmp_path, new, frozen)
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_old_run_cannot_resume(tmp_path):
    (tmp_path / "config.json").write_text('{"data":"data/example"}')
    config, snapshot = manifest()
    with pytest.raises(ValueError, match="Starszego"):
        experiment.prepare(tmp_path, config, snapshot)


def test_snapshot_tampering_detected(tmp_path):
    config, snapshot = manifest()
    experiment.prepare(tmp_path, config, snapshot)
    (tmp_path / "dataset_snapshot.json").write_text('{}')
    with pytest.raises(ValueError, match="Snapshot"):
        experiment.prepare(tmp_path, config, snapshot)


def test_pilot_data_and_conflict_oracles():
    systems, conflicts = dataset.validated_load("data/pilot")
    assert len(systems) == 3
    for s in systems:
        assert len(s["steps"]) == 6
        assert {step["type"] for step in s["steps"]} == dataset.CHANGE_TYPES
        cases = conflicts[s["system"]]
        assert len(cases) == 4 and {c["kind"] for c in cases} == dataset.CONFLICT_KINDS
        # Dla pułapki budujemy świadectwo spójności, dla konfliktów — sprawdzamy ich naturę.
        a, b, c, d, _, _ = s["vocabulary"]["states"]
        e1, e2, e3, _, _ = s["vocabulary"]["events"]
        g, ng, h, _ = s["vocabulary"]["guards"]
        base = dataset.apply_change([], s["steps"][0])
        W = dataset.tuples(s["steps"][0]["W"])
        trap_model = dataset.gold_model(s, W - {(c, e3, None, d)} | {(c, e3, h, d)})
        assert all(model.requirement_passes(r, trap_model, s["vocabulary"])
                   for r in dataset.apply_change(base, cases[3]))
        # Stanowy i przechodni mają dokładnie przeciwne testy dla tej samej sytuacji.
        assert base[3]["tests"][0]["type"] == "no_transition"
        assert cases[0]["add"][0]["tests"][0]["type"] == "has_transition"
        assert base[1]["tests"][0]["guard"] == cases[1]["add"][0]["tests"][0]["guard"] == g
        assert cases[1]["add"][0]["tests"][0]["type"] == "no_transition"
        # Oba stany muszą być osiągalne i każdy ma poprzedzać drugi: brak rozwiązania.
        assert base[4]["tests"][0] == {"type": "reachable", "state": d}
        assert cases[2]["add"][0]["tests"] == [
            {"type": "reachable", "state": c}, {"type": "always_before", "state": c, "before": d}]


def test_complete_demo_analysis_portability_and_partial_run(tmp_path, monkeypatch):
    out = tmp_path / "demo"
    demo.main(out)
    original = (out / "sequences.jsonl").read_bytes()
    demo.main(out)
    assert (out / "sequences.jsonl").read_bytes() == original
    # Wznawiamy tylko ostatnią, przerwaną sekwencję; kolejka mocka musi pozostać zgodna.
    seq_path = out / "sequences.jsonl"
    seq_path.write_text("\n".join(seq_path.read_text().splitlines()[:-1]) + "\n")
    demo.main(out)
    report = (out / "report.md").read_text()
    assert "PILOTAŻ; KOMPLETNY" in report
    assert "DEMONSTRACJA OFFLINE" in report
    assert "## Część potwierdzająca" not in report
    with (out / "steps.csv").open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 144
    assert any(r["model_valid"] == "False" for r in rows)
    assert len(list(out.glob("plot_*.png"))) == 6
    moved = tmp_path / "moved"
    shutil.move(str(out), moved)
    # Zabronione odwołanie do oryginalnych danych podczas analizy.
    monkeypatch.setattr(dataset, "load_systems", Mock(side_effect=AssertionError("snapshot wymagany")))
    analysis.main(moved)
    assert (moved / "report.md").read_text().replace("moved", "demo", 1) == report
    path = moved / "sequences.jsonl"
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[1:]) + "\n")
    analysis.main(moved)
    partial = (moved / "report.md").read_text()
    assert "NIEPEŁNY / NIEZGODNY" in partial
    assert "## Część potwierdzająca" not in partial


def test_legacy_analysis_warns(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"data":"data/example", "variants":["B1"], "reps":1, "llm":info()}))
    with pytest.warns(UserWarning, match="Starszy przebieg"):
        analysis.main(tmp_path)
    assert "brak snapshotu" in (tmp_path / "report.md").read_text()


def test_manifest_tampering_blocks_analysis(tmp_path):
    config, snapshot = manifest()
    experiment.prepare(tmp_path, config, snapshot)
    config['llm']['model'] = 'silently-changed'
    with pytest.raises(ValueError, match='Manifest'):
        experiment.frozen_data(tmp_path, config)


def test_conflict_denominators_include_failures_and_keep_modes_separate():
    seq = [{"variant":"M1", "result":status, "conflict_expected":expected, "kind":"state" if expected else None}
           for status, expected in [("CONFLICT", True), ("ERROR", True), ("REJECTED", True), ("CONFLICT", False)]]
    z = [{"variant":"M1", "result":status, "kind":kind}
         for status, kind in [("SCAFFOLD_ERROR", "ordering"), ("CONFLICT", "trap"), ("OK", "trap")]]
    counts = analysis.detection_counts(seq, z)
    seq_hits = next(c for c in counts if c['part'] == 'sekwencje' and c['kind'] == 'łącznie')
    z_hits = next(c for c in counts if c['part'] == 'Z' and c['kind'] == 'łącznie')
    z_fp = next(c for c in counts if c['part'] == 'Z' and c['kind'] == 'bez konfliktu')
    assert (seq_hits['hits'], seq_hits['n']) == (1, 3)
    assert (z_hits['hits'], z_hits['n']) == (0, 1)
    assert (z_fp['hits'], z_fp['n']) == (1, 2)


def test_confirmatory_report_requires_all_planned_records(tmp_path):
    systems = []
    for i in range(10):
        s = copy.deepcopy(EXAMPLE)
        s['system'] = f'orders{i}'
        systems.append(s)
    config, snapshot = experiment.build_config(
        args(variants=['B1','B2','M1','M2'], steps=None), systems,
        {s['system']: [] for s in systems}, info())
    experiment.prepare(tmp_path, config, snapshot)
    records = []
    for s in systems:
        for variant in config['variants']:
            for k, g in enumerate(dataset.gold_steps(s)):
                records.append({'system':s['system'], 'variant':variant, 'rep':0, 'step':k,
                                'type':g['type'], 'result':'CONFLICT' if g['conflict'] else 'OK',
                                'conflicting':list(g['conflicting']), 'calls':[],
                                'model':dataset.gold_model(s,g['W'])})
    path = tmp_path / 'sequences.jsonl'
    path.write_text('\n'.join(json.dumps(r) for r in records) + '\n')
    analysis.main(tmp_path)
    assert '## Część potwierdzająca' in (tmp_path / 'report.md').read_text()
    path.write_text('\n'.join(json.dumps(r) for r in records[:-1]) + '\n')
    analysis.main(tmp_path)
    report = (tmp_path / 'report.md').read_text()
    assert 'NIEPEŁNY / NIEZGODNY' in report
    assert '## Część potwierdzająca' not in report
