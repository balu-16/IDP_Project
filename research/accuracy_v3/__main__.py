"""Explicit preflight/verification/collection and background-batch entrypoints."""
import argparse
import os
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description="Protected-prefix constrained GAS v3 evaluation")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "smoke"):
        sub.add_parser(name)
    for name in ("confirm", "run"):
        p = sub.add_parser(name)
        p.add_argument("--dataset", choices=("scifact", "nfcorpus", "fiqa", "synthetic"), required=True)
        p.add_argument("--directory", type=Path, required=True)
        p.add_argument("--resume", action="store_true")
        if name == "run":
            p.add_argument("--frozen", type=Path, required=True)
    for name in ("evaluate", "report", "freeze"):
        p = sub.add_parser(name)
        p.add_argument("--directory", type=Path, required=True)
        if name == "freeze":
            p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("batch")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--batch-name", default="accuracy_v3_redundancy",
                   help="Separate run namespace; default preserves the earlier interrupted v3 run")
    args = parser.parse_args(argv)
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[key] = "2"
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    import torch
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    from . import checks, experiment
    try:
        if args.command == "preflight":
            result = checks.preflight()
        elif args.command == "smoke":
            result = checks.smoke()
        elif args.command in {"confirm", "run"}:
            result = experiment.collect(args.dataset, args.command, args.directory, args.resume, getattr(args, "frozen", None))
        elif args.command == "freeze":
            result = experiment.freeze(args.directory, args.output)
        elif args.command in {"evaluate", "report"}:
            result = getattr(experiment, args.command)(args.directory)
        else:
            from .batch import main as batch_main
            return batch_main(args.resume, args.batch_name)
    except (KeyboardInterrupt, InterruptedError) as exc:
        print(f"Interrupted: {exc}; committed checkpoints retained, use --resume.", file=sys.stderr)
        return 130
    except (ValueError, OSError, RuntimeError, ArithmeticError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
