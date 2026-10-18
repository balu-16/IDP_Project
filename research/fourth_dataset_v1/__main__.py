"""Explicit preparation, verification, execution, and recovery commands."""
import argparse
import os
from pathlib import Path
import subprocess
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description="Isolated TREC-COVID predeclared transfer evaluation")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("download", "preflight", "smoke", "freeze", "encode", "run", "evaluate", "report", "launch", "supervise", "status"):
        p = sub.add_parser(name)
        p.add_argument("--study", type=Path)
        if name in ("run", "launch", "supervise"):
            p.add_argument("--resume", action="store_true")
        if name == "encode":
            p.add_argument("--pilot-shards", type=int, default=0)
    args = parser.parse_args(argv)
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[key] = "2"
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    import torch
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    from . import checks, data, experiment, pipeline, protocol, supervisor
    study = args.study or protocol.STUDY
    try:
        if args.command == "download":
            result = data.prepare()
        elif args.command in ("preflight", "smoke"):
            result = getattr(checks, args.command)(study)
        elif args.command == "freeze":
            result = protocol.freeze(study)
        elif args.command == "encode":
            if args.pilot_shards < 0:
                raise ValueError("pilot-shards must be nonnegative")
            result = pipeline.encode(study, args.pilot_shards)
        elif args.command == "run":
            result = experiment.run(study, args.resume)
        elif args.command in ("evaluate", "report"):
            result = getattr(experiment, args.command)(study)
        elif args.command in ("launch", "supervise"):
            result = getattr(supervisor, args.command)(study, args.resume)
        else:
            path = study / "execution.json"
            result = protocol.read_checked(path) if path.exists() else {"status": "not launched"}
    except (KeyboardInterrupt, InterruptedError) as exc:
        print(f"Interrupted: {exc}; committed work retained.", file=sys.stderr)
        return 130
    except (ValueError, OSError, RuntimeError, ArithmeticError, subprocess.CalledProcessError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
