"""Manifest przebiegu, zamrożone dane i oczekiwane klucze wyników."""
import hashlib
import json
from pathlib import Path
import platform
from importlib.metadata import version

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = 1


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def source_hashes():
    files = sorted((ROOT / "src").glob("*.py")) + sorted((ROOT / "prompts").glob("*.md"))
    files += [ROOT / "requirements.txt"]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def build_config(args, systems, conflicts, llm_info):
    snapshot = {"systems": systems, "conflicts": conflicts}
    config = {
        "schema_version": SCHEMA_VERSION,
        "data": args.data,
        "purpose": "pilot" if all(s.get("purpose") == "pilot" for s in systems) else "experiment",
        "variants": sorted(set(args.variants)), "reps": args.reps,
        "systems": [s["system"] for s in systems], "steps": args.steps, "part": args.part,
        "llm": llm_info,
        "snapshot": "dataset_snapshot.json", "dataset_hash": digest(snapshot),
        "source_hashes": source_hashes(),
        "runtime": {"python": platform.python_version(),
                    "packages": {p: version(p) for p in ("ollama", "scipy", "matplotlib", "pytest")}},
    }
    # Lokalizacja danych nie wpływa na zgodność; znaczenie ma ich treść.
    config["fingerprint"] = digest({k: v for k, v in config.items() if k != "data"})
    return config, snapshot


def frozen_data(out, config):
    if config.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Nieobsługiwana wersja manifestu")
    if digest({k: v for k, v in config.items() if k not in ("data", "fingerprint")}) != config.get("fingerprint"):
        raise ValueError("Manifest przebiegu został zmodyfikowany")
    snapshot = json.loads((Path(out) / config["snapshot"]).read_text(encoding="utf-8"))
    if digest(snapshot) != config["dataset_hash"]:
        raise ValueError("Snapshot danych jest niezgodny z manifestem")
    return snapshot


def prepare(out, config, snapshot):
    """Nigdy nie nadpisuje istniejącego manifestu ani logów."""
    out = Path(out)
    path = out / "config.json"
    if path.exists():
        previous = json.loads(path.read_text(encoding="utf-8"))
        if previous.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Starszego przebiegu nie można wznowić. Użyj nowego katalogu --out.")
        if previous.get("fingerprint") != config["fingerprint"]:
            raise ValueError("Konfiguracja, dane lub kod zmieniły się. Użyj nowego katalogu --out.")
        if digest({k: v for k, v in previous.items() if k not in ("data", "fingerprint")}) != previous["fingerprint"]:
            raise ValueError("Manifest przebiegu został zmodyfikowany")
        frozen_data(out, previous)
        return
    if out.exists() and any(out.iterdir()):
        raise ValueError("Katalog wyników nie jest pusty i nie ma manifestu. Użyj nowego --out.")
    out.mkdir(parents=True, exist_ok=True)
    (out / config["snapshot"]).write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def expected_keys(config, systems, conflicts):
    seq, z = set(), set()
    for name, system in systems.items():
        for variant in config["variants"]:
            for rep in range(config["reps"]):
                if config.get("part", "all") in ("all", "sequences"):
                    for k in range(min(config.get("steps") or 6, len(system["steps"]))):
                        seq.add((name, variant, rep, k))
                if config.get("part", "all") in ("all", "z"):
                    for case in conflicts.get(name, []):
                        z.add((name, case["id"], variant, rep))
    return seq, z
