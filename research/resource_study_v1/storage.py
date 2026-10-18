"""Immutable study inputs/results with explicit parent and source identities."""
from pathlib import Path
import json

from research.accuracy_v3.storage import (ROOT, atomic_bytes, digest, environment_identity,
    exclusive, read_checked, sha, utc, write_checked)
from . import VERSION

DEFAULT = ROOT / "research/runs/resource_study_v1_final"


def sources():
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(Path(__file__).parent.glob("*.py"))}


def prerequisites():
    fiqa = json.loads((ROOT / "research/runs/accuracy_v3_redundancy_fiqa_full_execution.json").read_text())
    app = json.loads((ROOT / "build/application_gas/verification.json").read_text())
    if fiqa["status"] not in {"completed", "gate_failed"}:
        raise ValueError("Finish FiQA collection/evaluation/report before resource experiments")
    if app["status"] != "passed":
        raise ValueError("Finish and pass the queued application checks before resource experiments")
    fiqa_directory = ROOT / "research/runs/accuracy_v3_redundancy_fiqa_test"
    evaluated = read_checked(fiqa_directory / "evaluation.json")
    if (evaluated["query_count"] != 648 or evaluated["gate"] != fiqa["gate"]
            or evaluated["manifest_sha256"] != sha(fiqa_directory / "manifest.json")):
        raise ValueError("FiQA completion state disagrees with its verified full-test evaluation")
    for relative, expected in app["sources"].items():
        if sha(ROOT / relative) != expected:
            raise ValueError(f"Application checks are stale: {relative}")
    return {"fiqa_status": fiqa["status"], "fiqa_gate": fiqa["gate"],
            "fiqa_directory": str(fiqa_directory.relative_to(ROOT)),
            "fiqa_manifest_sha256": sha(fiqa_directory / "manifest.json"),
            "fiqa_evaluation_sha256": sha(fiqa_directory / "evaluation.json"),
            "application_checks_sha256": sha(ROOT / "build/application_gas/verification.json")}


def once(path, payload):
    path = Path(path)
    if path.exists():
        if read_checked(path) != payload:
            raise ValueError(f"Refusing to replace immutable resource artifact: {path}")
    else:
        write_checked(path, payload)


def protocol(directory):
    directory = Path(directory)
    p = read_checked(directory / "protocol.json")
    if p["version"] != VERSION or p["sources"] != sources():
        raise ValueError("Resource source/version changed; use recorded sources or a fresh directory")
    if p["environment"] != environment_identity():
        raise ValueError("Resource dependencies or frozen research sources changed")
    if sha(directory / "verification.json") != p["verification_sha256"]:
        raise ValueError("Resource verification snapshot changed")
    for relative, expected in p["sources"].items():
        if sha(directory / "source_snapshot" / relative) != expected:
            raise ValueError(f"Corrupt resource source snapshot: {relative}")
    for dataset, parent in p["parents"].items():
        for filename, expected in parent["hashes"].items():
            if sha(ROOT / parent["directory"] / filename) != expected:
                raise ValueError(f"Changed resource parent: {dataset}/{filename}")
    return p


def load_input(directory, item):
    path = Path(directory) / item["input"]
    if sha(path) != item["input_sha256"]:
        raise ValueError(f"Resource input changed: {path}")
    return read_checked(path)


def result_path(directory, task):
    return Path(directory) / "results" / (digest(task) + ".json")


def read_result(directory, task):
    path = result_path(directory, task)
    if not path.exists():
        return None
    value = read_checked(path)
    if value["protocol_sha256"] != sha(Path(directory) / "protocol.json") or value["task"] != task:
        raise ValueError(f"Resource result identity mismatch: {path}")
    return value
