"""Phase-specific CPU settings established before importing numerical libraries."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description="Encoding-only CPU acceleration for TREC-COVID")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "benchmark", "benchmark-worker", "check", "freeze", "encode", "run", "evaluate", "report", "launch", "supervise", "status"):
        p = sub.add_parser(name)
        p.add_argument("--study", type=Path)
        if name in ("run", "launch", "supervise"):
            p.add_argument("--resume", action="store_true")
        if name == "benchmark-worker":
            p.add_argument("--threads", type=int, choices=(2, 4, 6), required=True)
    args = parser.parse_args(argv)
    default = Path(__file__).resolve().parents[1] / "runs/fourth_dataset_cpu_v1_trec_covid"
    study = args.study or default
    threads = 2
    if args.command == "benchmark-worker":
        threads = args.threads
    elif args.command == "encode":
        # Checksummed verification follows before any inference; this bootstrap
        # read only initializes the process's numerical libraries consistently.
        threads = json.loads((study / "frozen.json").read_text())["payload"]["identity"]["cpu_preparation"]["encoding_threads"]
        if threads not in (2, 4, 6):
            raise ValueError("Unsupported offline CPU thread count")
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[key] = str(threads)
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    import torch
    torch.set_num_threads(threads)
    torch.set_num_interop_threads(1)
    from . import benchmark, checks, experiment, pipeline, protocol, supervisor
    try:
        if args.command == "prepare":
            result = protocol.prepare(study)
        elif args.command == "benchmark":
            result = benchmark.benchmark(study)
        elif args.command == "benchmark-worker":
            result = benchmark.worker(study, args.threads)
        elif args.command == "check":
            result = checks.check(study)
        elif args.command == "freeze":
            result = protocol.freeze(study)
        elif args.command == "encode":
            result = pipeline.encode(study)
        elif args.command == "run":
            result = experiment.run(study, args.resume)
        elif args.command in ("evaluate", "report"):
            result = getattr(experiment, args.command)(study)
        elif args.command in ("launch", "supervise"):
            result = getattr(supervisor, args.command)(study, args.resume)
        else:
            result = protocol.read_checked(study / "execution.json")
    except (KeyboardInterrupt, InterruptedError) as exc:
        print(f"Interrupted: {exc}; saved work retained.", file=sys.stderr)
        return 130
    except (ValueError, OSError, RuntimeError, ArithmeticError, AssertionError, subprocess.CalledProcessError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
