"""Adapter regression evidence, separate from inherited selector verification."""
import os
from pathlib import Path
import subprocess
import sys

from research.accuracy_v2.storage import ROOT, atomic_bytes, sha, write_checked
from .protocol import STUDY, sources


def check(study=STUDY):
    study = Path(study)
    if (study / "frozen.json").exists():
        raise ValueError("Do not replace regression evidence after freezing")
    command = [sys.executable, "-m", "unittest", "research.fourth_dataset_cpu_v1.test_cpu",
        "research.fourth_dataset_v1.test_fourth", "research.accuracy_v2.test_accuracy",
        "research.accuracy_v3.test_accuracy", "-v"]
    result = subprocess.run(command, cwd=ROOT, env=os.environ.copy(), capture_output=True, text=True)
    atomic_bytes(study / "cpu_tests.log", (result.stdout + result.stderr).encode())
    if result.returncode:
        raise ValueError(f"CPU adapter regression failed: {study / 'cpu_tests.log'}")
    write_checked(study / "cpu_checks.json", {"passed": True, "cpu_sources": sources(),
        "command": command, "test_log_sha256": sha(study / "cpu_tests.log"),
        "no_dataset_rankings_generated": True})
    return study / "cpu_checks.json"
