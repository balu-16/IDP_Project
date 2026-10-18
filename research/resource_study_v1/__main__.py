"""Freeze, check, pilot, execute/resume, or report the independent resource study."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "check", "pilot", "run", "report", "status"))
    parser.add_argument("--directory", type=Path, default=Path("research/runs/resource_study_v1_final"))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--background", action="store_true")
    args = parser.parse_args()
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[key] = "2"
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false",
                      PYTHONDONTWRITEBYTECODE="1")
    from .storage import ROOT, atomic_bytes, exclusive, prerequisites, read_checked, sha, write_checked
    directory = args.directory.resolve()
    if args.command == "status":
        p = directory / "execution.json"
        print(json.dumps(read_checked(p) if p.exists() else {"status": "not_started"}, indent=2))
        return 0
    if args.background:
        if args.command != "run":
            parser.error("--background is supported only for run")
        from .runner import task_index
        task_index(directory)
        command = [sys.executable, "-u", "-m", "research.resource_study_v1", "run", "--directory", str(directory)]
        if args.resume:
            command.append("--resume")
        logfile = directory / "supervisor.log"
        with exclusive(directory / ".launch.lock"):
            pidfile = directory / "supervisor.pid"
            if pidfile.exists():
                try:
                    current = Path(f"/proc/{int(pidfile.read_text())}/cmdline").read_bytes()
                except (OSError, ValueError):
                    current = b""
                if b"research.resource_study_v1" in current:
                    raise ValueError("Resource supervisor is already running")
            if (directory / "execution.json").exists() and not args.resume:
                raise ValueError("Resource execution exists; use --resume")
            with logfile.open("ab", buffering=0) as log:
                process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True, env=os.environ.copy())
            atomic_bytes(pidfile, f"{process.pid}\n".encode())
        print(json.dumps({"supervisor_pid": process.pid, "log": str(logfile)}))
        return 0
    if args.command == "check":
        prerequisites()
        import unittest
        suite = unittest.defaultTestLoader.loadTestsFromName("research.resource_study_v1.test_study")
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        if not result.wasSuccessful():
            return 1
        from .storage import sources, utc
        output = ROOT / "build/resource_study/checks.json"
        write_checked(output, {"passed": True, "sources": sources(), "checked_utc": utc(), "tests": result.testsRun})
        print(output)
    elif args.command == "freeze":
        from .inputs import freeze
        result = freeze(directory)
        print(json.dumps({"tasks": len(result["tasks"]), "availability": result["availability"]}, indent=2))
    elif args.command == "pilot":
        from .runner import pilot
        print(json.dumps(pilot(directory), indent=2))
    elif args.command == "run":
        from .runner import run
        run(directory, args.resume)
    else:
        from .report import report
        report(directory)
        print(directory / "REPORT.md")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, InterruptedError) as exc:
        print(f"Interrupted: {exc}; committed resource tasks retained.", file=sys.stderr)
        raise SystemExit(130)
    except (ValueError, RuntimeError, OSError, ArithmeticError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
