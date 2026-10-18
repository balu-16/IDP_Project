"""Fresh, memory-limited measurements; invoked by the resumable supervisor."""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import resource
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    request = json.loads(args.request.read_text())
    # Set before importing NumPy/Qiskit; no model weights are loaded.
    resource.setrlimit(resource.RLIMIT_AS, (2 << 30, 2 << 30))
    from .storage import load_input, write_checked
    from .problem import OracleProblem, POOLS, BITS, SEEDS, restrict
    from research.accuracy_v2.core import ScoredFeatures
    from research.accuracy_v3.core import Config, select
    import numpy as np
    import tracemalloc
    task = request["task"]
    payload = load_input(request["directory"], task)
    scored = ScoredFeatures.from_dict(payload["features"])
    before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    begin = time.perf_counter()
    try:
        if task["kind"] == "compact":
            rows = []
            for seed in SEEDS:
                base = payload["baselines"][str(seed)]
                for m in POOLS:
                    subset = restrict(scored, base, m)
                    if subset is None:
                        rows.append({"seed": seed, "pool": m, "status": "unavailable",
                                     "reason": "saved eligible pool is smaller than requested"})
                        continue
                    for bits in BITS:
                        cfg = Config(coefficient_bits=bits)
                        cell = {"seed": seed, "pool": m, "bits": bits, "methods": {}}
                        for method in ("gas_v3", "exact_float_v3", "exact_quantized_v3"):
                            result = select(subset, base, method, cfg, seed)
                            # A separate memory replay avoids charging allocation
                            # instrumentation to the reported selector timing.
                            tracemalloc.start()
                            current, _ = tracemalloc.get_traced_memory()
                            replay = select(subset, base, method, cfg, seed)
                            _, peak = tracemalloc.get_traced_memory()
                            tracemalloc.stop()
                            if replay.ranked_ids != result.ranked_ids:
                                raise ArithmeticError("Memory replay changed the sampled selection")
                            cell["methods"][method] = {**result.to_dict(),
                                "additional_traced_peak_bytes": max(0, peak-current),
                                "memory_replay_excluded_from_reported_timing": True}
                        gas = cell["methods"]["gas_v3"]
                        exact = cell["methods"]["exact_float_v3"]
                        quantized = cell["methods"]["exact_quantized_v3"]
                        cell.update(status="completed", float_gap=gas["redundancy"]-exact["redundancy"],
                                    quantized_gap=gas["redundancy"]-quantized["redundancy"])
                        rows.append(cell)
            output = {"status": "completed", "rows": rows,
                "memory_boundary": "Traced incremental allocations per method; RSS is the whole fresh query worker across its grid"}
        else:
            subset = restrict(scored, payload["baselines"]["0"], task["pool"])
            if subset is None:
                raise ValueError("Frozen native cell is no longer available")
            loading = time.perf_counter()
            from .circuits import (oracle, complete_iteration, simulate_small, synthesize,
                                   NativeSimulationUnavailable)
            libraries_ms = (time.perf_counter()-loading)*1000
            start = time.perf_counter()
            p = OracleProblem(subset, payload["baselines"]["0"], task["bits"])
            phase, registers = oracle(p)
            build_ms = (time.perf_counter()-start)*1000
            compiled, stats = synthesize(phase)
            output = {"status": "completed", "registers": registers, "oracle": stats,
                "build_ms": build_ms, "library_loading_ms": libraries_ms,
                "coefficient_bits": p.bits, "pool": p.m,
                "classical_coefficient_access": "saved classical features compiled as constants; no QRAM assumption"}
            if p.m <= 8:
                start = time.perf_counter()
                iteration = complete_iteration(p, phase)
                output["complete_iteration_build_ms"] = (time.perf_counter()-start)*1000
                _, output["complete_iteration"] = synthesize(iteration)
            else:
                output["complete_iteration"] = {"status": "not_performed",
                    "reason": "generic full state preparation is restricted to eight decisions"}
            if p.m <= 5:
                phase_test = phase.copy_empty_like()
                phase_test.h(range(p.m))
                phase_test.compose(phase, inplace=True)
                try:
                    output["phase_validation"] = simulate_small(phase_test, p, p.expected_uniform_phase())
                    output["iteration_validation"] = simulate_small(iteration, p, p.expected_iteration())
                except NativeSimulationUnavailable as exc:
                    output["native_simulation"] = {"status": "memory_limit", "reason": str(exc)}
            else:
                output["native_simulation"] = {"status": "not_performed",
                    "reason": "native validation simulations are restricted to five decisions"}
        output.update(elapsed_ms=(time.perf_counter()-begin)*1000,
                      process_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                      imported_process_peak_rss_bytes=before)
    except MemoryError:
        output = {"status": "memory_limit", "limit_bytes": 2 << 30}
    write_checked(args.output, output)


if __name__ == "__main__":
    main()
