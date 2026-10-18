"""Explicit entrypoints; --help never loads datasets or model weights."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description="L6-guided GAS v2. Dataset evaluations require an explicit run command.")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("preflight", help="Validate local inputs without inference or benchmark rankings")
    check.add_argument("--dataset", choices=["all", "scifact", "nfcorpus", "fiqa"], default="all")
    check.add_argument("--output", type=Path, default=Path("build/accuracy_v2/preflight.json"))
    smoke = commands.add_parser("smoke", help="Replay saved development features and score two local L6 pairs")
    smoke.add_argument("--saved-development", type=Path, default=Path("build/accuracy_smalltest_20261017T091602Z"))
    smoke.add_argument("--output", type=Path, default=Path("build/accuracy_v2/smoke.json"))
    for name in ("tune", "run"):
        command = commands.add_parser(name)
        command.add_argument("--dataset", choices=["synthetic", "scifact", "nfcorpus", "fiqa"], required=True)
        command.add_argument("--directory", type=Path, required=True)
        command.add_argument("--resume", action="store_true")
        command.add_argument("--no-neural-controls", action="store_true", help="Keep mandatory guided L6; omit additional L2/L6 dense15/top64 controls")
        command.add_argument("--legacy-grover", action="store_true", help="Also tune/run the older probability-based circuit control")
        command.add_argument("--preflight", type=Path, help="Preflight report; defaults to build/accuracy_v2/preflight.json")
        if name == "run":
            command.add_argument("--frozen", type=Path, help="Required for real datasets: sealed development tuning's frozen.json")
    for name in ("evaluate", "report"):
        command = commands.add_parser(name)
        command.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args(argv)
    for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[key] = "2"
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        os.environ[key] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    import torch
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    from . import checks, experiment
    try:
        if args.command == "preflight":
            names = ["scifact", "nfcorpus", "fiqa"] if args.dataset == "all" else [args.dataset]
            checks.preflight(names, args.output)
            result = args.output
        elif args.command == "smoke":
            checks.smoke(args.output, args.saved_development)
            result = args.output
        elif args.command == "tune":
            result = experiment.tune(args.dataset, args.directory, args.resume, not args.no_neural_controls, args.legacy_grover, preflight_path=args.preflight)
        elif args.command == "run":
            result = experiment.run(args.dataset, args.directory, args.frozen, args.resume, not args.no_neural_controls, args.legacy_grover, preflight_path=args.preflight)
        elif args.command == "evaluate":
            result = experiment.evaluate(args.directory)
        else:
            result = experiment.report(args.directory)
    except (KeyboardInterrupt, InterruptedError) as exc:
        print(f"Stopped: {exc}. Committed work retained; use the same command with --resume.", file=sys.stderr)
        return 130
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
