"""Constrained GAS with explicit simulator accounting and classical controls.

Judgments never enter this module. Only the simulator oracle sees objective
tables; the adaptive controller receives neither an optimum nor a marked count.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import itertools
import math
import time

import numpy as np

from .baseline import ScoredFeatures
from .primitives import SelectionResult, grover_step

METHODS = ("gas_v3", "greedy_v3", "exact_float_v3", "exact_quantized_v3",
           "random_v3", "l6_union", "l6_union_tail")
CONSTRAINED = set(METHODS[:5])
EPS = 1e-12


@dataclass(frozen=True)
class Config:
    protected_prefix: int = 5
    selected_count: int = 8
    coefficient_bits: int = 16
    max_oracle_calls: int = 64
    max_trials: int = 32
    window_growth: float = 1.2
    time_limit_seconds: float = 15.0
    max_subsets: int = 200_000

    def __post_init__(self):
        for key in ("protected_prefix", "selected_count", "coefficient_bits", "max_oracle_calls", "max_trials", "max_subsets"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{key} must be a nonnegative integer")
        if not 1 <= self.coefficient_bits <= 16 or not 1 <= self.selected_count <= 8:
            raise ValueError("Unsupported coefficient precision or output count")
        if not 0 <= self.protected_prefix <= self.selected_count or self.selected_count - self.protected_prefix > 3:
            raise ValueError("Refinement supports at most three tail documents")
        if not math.isfinite(self.window_growth) or not 1 < self.window_growth < 4 / 3:
            raise ValueError("Invalid growth factor")
        if not math.isfinite(self.time_limit_seconds) or self.time_limit_seconds < 0 or self.max_subsets < 1:
            raise ValueError("Invalid time or basis budget")


def prepare(features: ScoredFeatures, baseline, config=Config()):
    ids, z = features.candidates.ids, features.l6_logits
    baseline = tuple(baseline)
    if len(ids) > 45 or len(baseline) > config.selected_count:
        raise ValueError("Unsupported pool or baseline size")
    if len(set(baseline)) != len(baseline) or not set(baseline) <= set(ids):
        raise ValueError("Baseline IDs must be unique members of the union")
    if len(baseline) != min(config.selected_count, len(ids)):
        raise ValueError("Baseline has the wrong output count")
    lookup = {did: i for i, did in enumerate(ids)}
    base = [lookup[d] for d in baseline]
    head = base[:config.protected_prefix]
    tail = base[len(head):]
    pool = [i for i in range(len(ids)) if i not in head and
            (not tail or z[i] >= min(z[tail]) - EPS)]
    states = math.comb(len(pool), len(tail))
    if states > config.max_subsets:
        raise ValueError("Refinement basis exceeds its declared budget")
    layout = np.asarray(list(itertools.combinations(pool, len(tail))), dtype=np.int16).reshape(states, len(tail))
    initial = next(i for i, row in enumerate(layout) if set(row) == set(tail))
    sim = np.clip(features.candidates.embeddings @ features.candidates.embeddings.T, 0, 1)
    quantized = np.rint(((1 << config.coefficient_bits) - 1) * sim).astype(np.int64)
    red = np.full(states, sum(sim[i, j] for i, j in itertools.combinations(head, 2)), dtype=np.float64)
    energy = np.full(states, sum(quantized[i, j] for i, j in itertools.combinations(head, 2)), dtype=np.int64)
    for a in range(len(tail)):
        red += sim[layout[:, a]][:, head].sum(axis=1)
        energy += quantized[layout[:, a]][:, head].sum(axis=1)
    for a, b in itertools.combinations(range(len(tail)), 2):
        red += sim[layout[:, a], layout[:, b]]
        energy += quantized[layout[:, a], layout[:, b]]
    red /= max(1, math.comb(len(base), 2))
    # Equivalent to integer threshold-count constraints: at least j selected
    # documents exceed each fixed baseline score threshold. No qrels involved.
    valid = (np.sort(z[layout], axis=1) >= np.sort(z[tail]) - EPS).all(axis=1)
    if not valid[initial]:
        raise ArithmeticError("The unchanged baseline must be feasible")
    return {"layout": layout, "initial": initial, "red": red, "energy": energy,
            "valid": valid, "head": head, "base": base, "pool": pool, "sim": sim}


def select(features, baseline, method="gas_v3", config=Config(), seed=0, objective_budget=1):
    if method not in METHODS:
        raise ValueError(f"Unknown v3 method: {method}")
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)) or seed < 0:
        raise ValueError("Seed must be a nonnegative integer")
    if isinstance(objective_budget, bool) or not isinstance(objective_budget, int) or objective_budget < 1:
        raise ValueError("Invalid random-search budget")
    start, cpu = time.perf_counter(), time.process_time()
    p = prepare(features, baseline, config)
    prepared_ms = (time.perf_counter() - start) * 1000
    layout, initial = p["layout"], p["initial"]
    red, energy, valid = p["red"], p["energy"], p["valid"]
    incumbent, trace, window = initial, [], 1.0
    rng = np.random.default_rng(seed)
    counts = {"phase_oracle_calls": 0, "reversible_objective_calls": 0, "measured_trials": 0,
              "classical_simulator_objective_evaluations": len(layout),
              "classical_search_objective_evaluations": 1, "accepted_updates": 0}
    status = "completed"
    if method == "gas_v3":
        status = "trial_budget"
        if len(layout) == 1:
            status = "trivial_basis"
        elif config.max_oracle_calls == 0:
            status = "oracle_budget"
        elif config.time_limit_seconds == 0:
            status = "time_limit"
        else:
            deadline = start + config.time_limit_seconds
            for trial in range(config.max_trials):
                if time.perf_counter() >= deadline:
                    status = "time_limit"
                    break
                remaining = config.max_oracle_calls - counts["phase_oracle_calls"]
                if remaining <= 0:
                    status = "oracle_budget"
                    break
                iterations = min(int(rng.integers(0, math.ceil(window))), remaining)
                marked = valid & (energy < energy[incumbent])
                state = np.full(len(layout), 1 / math.sqrt(len(layout)), dtype=np.complex128)
                completed = 0
                for _ in range(iterations):
                    if time.perf_counter() >= deadline:
                        break
                    grover_step(state, marked)
                    completed += 1
                counts["phase_oracle_calls"] += completed
                counts["reversible_objective_calls"] += 2 * completed
                if completed != iterations or time.perf_counter() >= deadline:
                    status = "time_limit"
                    break
                probabilities = np.abs(state) ** 2
                norm = float(probabilities.sum())
                if not math.isfinite(norm) or abs(norm - 1) > 1e-8:
                    raise ArithmeticError("Grover state lost normalization")
                sampled = int(rng.choice(len(layout), p=probabilities / norm))
                before = incumbent
                accepted = bool(valid[sampled] and energy[sampled] < energy[incumbent]
                                and red[sampled] < red[incumbent] - EPS)
                counts["measured_trials"] += 1
                counts["classical_search_objective_evaluations"] += 1
                if accepted:
                    incumbent, window = sampled, 1.0
                    counts["accepted_updates"] += 1
                else:
                    window = min(window * config.window_growth, math.sqrt(len(layout)))
                trace.append({"trial": trial, "iterations": iterations, "sampled_address": sampled,
                              "accepted": accepted, "energy_before": int(energy[before]),
                              "energy_after": int(energy[incumbent]), "redundancy_before": float(red[before]),
                              "redundancy_after": float(red[incumbent]), "state_norm": norm})
            if counts["phase_oracle_calls"] >= config.max_oracle_calls:
                status = "oracle_budget"
    elif method in {"exact_float_v3", "exact_quantized_v3"}:
        feasible = valid & (red <= red[initial] + EPS)
        objective = red if method == "exact_float_v3" else energy
        incumbent = int(np.argmin(np.where(feasible, objective, np.inf)))
        counts["classical_search_objective_evaluations"] = len(layout)
    elif method == "greedy_v3":
        while True:
            required = max(0, layout.shape[1] - 1)
            neighbours = np.array([len(set(row) & set(layout[incumbent])) >= required for row in layout])
            feasible = neighbours & valid & (red <= red[initial] + EPS)
            pick = int(np.argmin(np.where(feasible, red, np.inf)))
            counts["classical_search_objective_evaluations"] += int(neighbours.sum())
            if red[pick] >= red[incumbent] - EPS:
                break
            incumbent = pick
            counts["accepted_updates"] += 1
    elif method == "random_v3":
        draws = rng.integers(0, len(layout), size=objective_budget)
        feasible = draws[valid[draws] & (red[draws] <= red[initial] + EPS)]
        candidates = np.r_[initial, feasible]
        incumbent = int(candidates[np.argmin(red[candidates])])
        counts["classical_search_objective_evaluations"] += objective_budget

    ids, z = features.candidates.ids, features.l6_logits
    order = lambda indices: sorted(indices, key=lambda i: (-z[i], ids[i]))
    if method == "l6_union":
        chosen = order(range(len(ids)))[:len(baseline)]
        ranked = chosen
    elif method == "l6_union_tail":
        chosen = p["head"] + order(p["pool"])[:len(p["base"]) - len(p["head"])]
        ranked = chosen
    else:
        chosen = p["head"] + layout[incumbent].tolist()
        ranked = p["head"] + order(layout[incumbent])
    pairs = list(itertools.combinations(chosen, 2))
    redundancy = float(np.mean([p["sim"][i, j] for i, j in pairs])) if pairs else 0.0
    scale = (1 << config.coefficient_bits) - 1
    result_energy = sum(int(np.rint(scale * p["sim"][i, j])) for i, j in pairs)
    resources = {"union_candidates": len(ids), "tail_candidates_after_prefilter": len(p["pool"]),
                 "compact_basis_states": len(layout), "compact_amplitude_bytes": 16 * len(layout),
                 "decision_qubits": len(p["pool"]), "objective_value_qubits": max(1, (scale * len(pairs)).bit_length() + 1),
                 "quality_constraints": len(p["base"]) - len(p["head"]),
                 "representation": "compact noiseless classical simulation; no physical QPU timing",
                 "ordering_policy": "original five fixed, raw-L6 ordered tail; l6_union is a global-sort control"}
    timings = {"preparation_ms": prepared_ms, "total_ms": (time.perf_counter() - start) * 1000,
               "cpu_ms": (time.process_time() - cpu) * 1000}
    return SelectionResult(method, sorted(ids[i] for i in chosen), [ids[i] for i in ranked], int(result_energy),
                           -redundancy, redundancy, status, int(seed), resources, timings, counts,
                           trace, {**asdict(config), "baseline_ids": list(baseline)})
