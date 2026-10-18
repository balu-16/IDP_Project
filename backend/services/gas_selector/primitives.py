"""Grover Adaptive Search on fixed-cardinality evidence sets.

The compact simulator stores amplitudes for valid subsets only. It implements
the phase oracle and reflection about their uniform superposition exactly
(up to floating-point roundoff). This is NOT execution of a full Qiskit circuit
or evidence of a physical quantum speedup. Classical enumeration and energy
preparation are explicitly counted and timed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from functools import lru_cache
import itertools
import math
import time
from typing import Sequence

import numpy as np


def _integer(name: str, value: int, minimum: int = 0) -> None:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


@dataclass(frozen=True)
class GASConfig:
    candidate_limit: int = 15
    selected_count: int = 8
    diversity_weight: float = 0.25
    coefficient_bits: int = 6
    max_oracle_calls: int = 64
    max_trials: int = 32
    time_limit_seconds: float = 15.0
    window_growth: float = 1.2
    max_subsets: int = 200_000

    def __post_init__(self) -> None:
        for name in ("candidate_limit", "selected_count", "coefficient_bits", "max_subsets"):
            _integer(name, getattr(self, name), 1)
        for name in ("max_oracle_calls", "max_trials"):
            _integer(name, getattr(self, name))
        for name in ("candidate_limit", "selected_count", "coefficient_bits", "max_subsets",
                     "max_oracle_calls", "max_trials"):
            object.__setattr__(self, name, int(getattr(self, name)))
        if self.selected_count > self.candidate_limit:
            raise ValueError("selected_count cannot exceed candidate_limit")
        if self.candidate_limit > 20 or self.coefficient_bits > 16:
            raise ValueError("Compact simulation supports at most 20 candidates and 16 coefficient bits")
        if not math.isfinite(self.diversity_weight) or not 0 <= self.diversity_weight <= 1:
            raise ValueError("diversity_weight must be finite and in [0, 1]")
        if not math.isfinite(self.time_limit_seconds) or self.time_limit_seconds < 0:
            raise ValueError("time_limit_seconds must be finite and nonnegative")
        if not math.isfinite(self.window_growth) or not 1 < self.window_growth < 4 / 3:
            raise ValueError("window_growth must be between 1 and 4/3")
        if math.comb(self.candidate_limit, self.selected_count) > self.max_subsets:
            raise ValueError("Configuration exceeds max_subsets")


@dataclass(frozen=True)
class CandidateFeatures:
    """Arrays and passages in candidate-ID order; callers must prefilter first."""

    ids: tuple[str, ...]
    cosine_scores: np.ndarray
    embeddings: np.ndarray
    passages: tuple[str, ...] = ()
    representative_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        ids = tuple(self.ids)
        if any(not isinstance(d, str) or not d for d in ids) or len(set(ids)) != len(ids):
            raise ValueError("Candidate IDs must be unique nonempty strings")
        scores = np.array(self.cosine_scores, dtype=np.float64, copy=True)
        vectors = np.array(self.embeddings, dtype=np.float64, copy=True)
        if not ids and vectors.size == 0:
            vectors = np.empty((0, 0), dtype=np.float64)
        if scores.shape != (len(ids),) or not np.isfinite(scores).all():
            raise ValueError("Each candidate requires one finite cosine score")
        if np.any(np.abs(scores) > 1 + 1e-6):
            raise ValueError("Cosine scores must be in [-1, 1]")
        if vectors.ndim != 2 or vectors.shape[0] != len(ids) or not np.isfinite(vectors).all():
            raise ValueError("Embeddings must be a finite candidate-by-dimension matrix")
        if ids:
            norms = np.linalg.norm(vectors, axis=1)
            if vectors.shape[1] == 0 or not np.isfinite(norms).all() or np.any(norms <= 1e-12):
                raise ValueError("Candidate embeddings must be nonzero and have finite norms")
            vectors /= norms[:, None]
        passages, representatives = tuple(self.passages), tuple(self.representative_ids)
        for name, values in (("passages", passages), ("representative_ids", representatives)):
            if values and (len(values) != len(ids) or any(not isinstance(v, str) for v in values)):
                raise ValueError(f"{name} must have one string per candidate")
        scores = np.clip(scores, -1, 1)
        scores.setflags(write=False)
        vectors.setflags(write=False)
        object.__setattr__(self, "ids", ids)
        object.__setattr__(self, "cosine_scores", scores)
        object.__setattr__(self, "embeddings", vectors)
        object.__setattr__(self, "passages", passages)
        object.__setattr__(self, "representative_ids", representatives)

    def to_dict(self) -> dict:
        return {"ids": list(self.ids), "cosine_scores": self.cosine_scores.tolist(),
                "embeddings": self.embeddings.tolist(), "passages": list(self.passages),
                "representative_ids": list(self.representative_ids)}

    @classmethod
    def from_dict(cls, value: dict) -> "CandidateFeatures":
        return cls(tuple(value["ids"]), value["cosine_scores"], value["embeddings"],
                   tuple(value.get("passages", ())), tuple(value.get("representative_ids", ())))


@lru_cache(maxsize=4)
def subset_layout(n: int, k: int) -> np.ndarray:
    """Data-independent basis; bounded and read-only to avoid cache corruption."""
    _integer("n", n)
    _integer("k", k)
    if k > n or n > 20 or math.comb(n, k) > 200_000:
        raise ValueError("Unsupported subset basis")
    rows = np.asarray(list(itertools.combinations(range(n), k)), dtype=np.int16)
    rows = rows.reshape(math.comb(n, k), k)
    rows.setflags(write=False)
    return rows


@dataclass(frozen=True)
class SelectionProblem:
    features: CandidateFeatures
    config: GASConfig
    count: int
    relevance: np.ndarray
    similarity: np.ndarray
    linear: np.ndarray
    quadratic: np.ndarray

    def energy(self, indices: Sequence[int]) -> int:
        chosen = tuple(int(i) for i in indices)
        return int(-self.linear[list(chosen)].sum() +
                   sum(int(self.quadratic[i, j]) for i, j in itertools.combinations(chosen, 2)))

    def utility(self, indices: Sequence[int]) -> float:
        chosen = tuple(int(i) for i in indices)
        if not chosen:
            return 0.0
        return float(self.relevance[list(chosen)].mean() -
                     self.config.diversity_weight * self.redundancy(chosen))

    def redundancy(self, indices: Sequence[int]) -> float:
        pairs = list(itertools.combinations(indices, 2))
        return float(np.mean([self.similarity[i, j] for i, j in pairs])) if pairs else 0.0

    def cosine_order(self, indices: Sequence[int] | None = None) -> list[int]:
        indices = range(len(self.features.ids)) if indices is None else indices
        return sorted(indices, key=lambda i: (-self.features.cosine_scores[i], self.features.ids[i]))

    def resources(self) -> dict:
        n, k = len(self.features.ids), self.count
        # Valid-subset bounds; the incumbent is also feasible, so |E-tau|
        # cannot exceed upper-lower. No optimum or improving-state count is used.
        lower = -int(np.sort(self.linear)[-k:].sum()) if k else 0
        pair_count = math.comb(k, 2)
        values = self.quadratic[np.triu_indices(n, 1)]
        upper = int(np.sort(values)[-pair_count:].sum()) if pair_count else 0
        width = max(1, int(upper - lower).bit_length() + 1)
        states = math.comb(n, k)
        return {"feasible_subsets": states, "decision_qubits": n,
                "value_qubits": width, "logical_total_qubits": n + width,
                "energy_lower_bound": lower, "energy_upper_bound": upper,
                "compact_amplitude_bytes": states * np.dtype(np.complex128).itemsize,
                "full_statevector_bytes_estimate": (1 << (n + width)) * 16,
                "note": "Logical circuit estimate; compact simulation does not allocate work qubits."}


def prepare_problem(features: CandidateFeatures, config: GASConfig | None = None) -> SelectionProblem:
    config = config or GASConfig()
    n = len(features.ids)
    if n > config.candidate_limit:
        raise ValueError("Too many candidates: prefilter explicitly before calling the selector")
    k = min(n, config.selected_count)
    if math.comb(n, k) > config.max_subsets:
        raise ValueError("Candidate set exceeds max_subsets")
    relevance = (features.cosine_scores + 1) / 2
    similarity = np.clip(features.embeddings @ features.embeddings.T, 0, 1)
    np.fill_diagonal(similarity, 0)
    scale = (1 << config.coefficient_bits) - 1
    linear = np.rint(scale * relevance).astype(np.int64)
    quadratic = (np.rint(scale * 2 * config.diversity_weight / (k - 1) * similarity).astype(np.int64)
                 if k > 1 else np.zeros((n, n), dtype=np.int64))
    for array in (relevance, similarity, linear, quadratic):
        array.setflags(write=False)
    return SelectionProblem(features, config, k, relevance, similarity, linear, quadratic)


def enumerate_energies(problem: SelectionProblem) -> tuple[np.ndarray, np.ndarray]:
    """Classical simulator work, also used independently by exact baselines."""
    layout = subset_layout(len(problem.features.ids), problem.count)
    energies = -problem.linear[layout].sum(axis=1, dtype=np.int64)
    # One gather at a time bounds temporary memory even for 20 choose 10.
    for a, b in itertools.combinations(range(problem.count), 2):
        energies += problem.quadratic[layout[:, a], layout[:, b]]
    return layout, energies


def grover_step(amplitudes: np.ndarray, marked: np.ndarray) -> None:
    """In-place phase marking followed by reflection about the uniform state."""
    amplitudes[marked] *= -1
    mean = amplitudes.mean()
    amplitudes *= -1
    amplitudes += 2 * mean


@dataclass
class SelectionResult:
    method: str
    selected_ids: list[str]
    ranked_ids: list[str]
    energy: int
    utility: float
    redundancy: float
    status: str
    seed: int | None
    resources: dict
    timings_ms: dict
    counts: dict
    trace: list[dict] = field(default_factory=list)
    config: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _result(problem: SelectionProblem, method: str, indices: Sequence[int], status: str,
            seed: int | None, timings: dict, counts: dict, trace: list[dict] | None = None) -> SelectionResult:
    ordered = problem.cosine_order(indices)
    ids = problem.features.ids
    resources = problem.resources()
    resources["ordering_policy"] = "cosine descending, document-ID tie-break"
    return SelectionResult(method, sorted(ids[i] for i in indices), [ids[i] for i in ordered],
                           problem.energy(indices), problem.utility(indices), problem.redundancy(indices),
                           status, seed, resources, timings, counts, trace or [], asdict(problem.config))


def _finish_measurement(result: SelectionResult, start: float, cpu_start: float) -> SelectionResult:
    result.timings_ms["total_ms"] = (time.perf_counter() - start) * 1000
    result.timings_ms["cpu_ms"] = (time.process_time() - cpu_start) * 1000
    try:
        import resource
        import sys

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        result.resources["process_peak_rss_bytes"] = int(peak if sys.platform == "darwin" else peak * 1024)
    except (ImportError, AttributeError):
        result.resources["process_peak_rss_bytes"] = None
    result.resources["rss_note"] = "Whole-process lifetime high-water mark, not isolated selector peak memory."
    return result


def search(problem: SelectionProblem, seed: int = 0) -> SelectionResult:
    """Bounded GAS with no access to the exact optimum or marked-state count."""
    _integer("seed", seed)
    seed = int(seed)
    start = time.perf_counter()
    config = problem.config
    initial = sorted(problem.cosine_order()[:problem.count])
    counts = {"phase_oracle_calls": 0, "reversible_objective_calls": 0,
              "measured_trials": 0, "classical_search_objective_evaluations": 1,
              "classical_simulator_objective_evaluations": 0}
    timings = {"enumeration_ms": 0.0, "search_ms": 0.0, "total_ms": 0.0}
    if len(problem.features.ids) <= config.selected_count:
        timings["total_ms"] = (time.perf_counter() - start) * 1000
        return _result(problem, "gas", initial, "trivial", seed, timings, counts)
    if config.max_oracle_calls == 0 or config.max_trials == 0 or config.time_limit_seconds == 0:
        status = ("time_limit" if config.time_limit_seconds == 0 else
                  "oracle_budget" if config.max_oracle_calls == 0 else "trial_budget")
        timings["total_ms"] = (time.perf_counter() - start) * 1000
        return _result(problem, "gas", initial, status, seed, timings, counts)
    deadline = start + config.time_limit_seconds
    prep_start = time.perf_counter()
    layout, energies = enumerate_energies(problem)
    timings["enumeration_ms"] = (time.perf_counter() - prep_start) * 1000
    counts["classical_simulator_objective_evaluations"] = len(layout)
    incumbent = problem.energy(initial)
    best = initial
    rng = np.random.default_rng(seed)
    window = 1.0
    trace = []
    search_start = time.perf_counter()
    status = "trial_budget"
    for trial in range(config.max_trials):
        if time.perf_counter() >= deadline:
            status = "time_limit"
            break
        remaining = config.max_oracle_calls - counts["phase_oracle_calls"]
        if remaining <= 0:
            status = "oracle_budget"
            break
        iterations = min(int(rng.integers(0, math.ceil(window))), remaining)
        before = incumbent
        # This array is the simulator's oracle implementation. The adaptive
        # controller neither counts marked states nor sees an optimum.
        marked = energies < incumbent
        amplitudes = np.full(len(layout), 1 / math.sqrt(len(layout)), dtype=np.complex128)
        completed = 0
        for _ in range(iterations):
            if time.perf_counter() >= deadline:
                break
            grover_step(amplitudes, marked)
            completed += 1
        counts["phase_oracle_calls"] += completed
        counts["reversible_objective_calls"] += 2 * completed
        if completed != iterations or time.perf_counter() >= deadline:
            status = "time_limit"
            trace.append({"trial": trial, "iterations": completed, "measured": False,
                          "incumbent_before": before, "incumbent_after": incumbent})
            break
        probabilities = np.abs(amplitudes) ** 2
        norm = float(probabilities.sum())
        if not math.isfinite(norm) or abs(norm - 1) > 1e-8:
            raise ArithmeticError("Compact Grover state lost normalization")
        probabilities /= norm
        address = int(rng.choice(len(layout), p=probabilities))
        measured = layout[address].tolist()
        energy = problem.energy(measured)
        counts["measured_trials"] += 1
        counts["classical_search_objective_evaluations"] += 1
        accepted = energy < incumbent
        if accepted:
            best, incumbent, window = measured, energy, 1.0
        else:
            window = min(window * config.window_growth, math.sqrt(len(layout)))
        trace.append({"trial": trial, "iterations": completed, "measured": True,
                      "sampled_ids": [problem.features.ids[i] for i in measured],
                      "sample_energy": energy, "accepted": bool(accepted),
                      "incumbent_before": before, "incumbent_after": incumbent,
                      "sample_probability": float(probabilities[address])})
    if status != "time_limit" and counts["phase_oracle_calls"] >= config.max_oracle_calls:
        status = "oracle_budget"
    timings["search_ms"] = (time.perf_counter() - search_start) * 1000
    timings["total_ms"] = (time.perf_counter() - start) * 1000
    return _result(problem, "gas", best, status, seed, timings, counts, trace)


def select_evidence(features: CandidateFeatures, config: GASConfig | None = None,
                    seed: int = 0) -> SelectionResult:
    """Public entrypoint: candidate validation/preparation is included in timing."""
    start = time.perf_counter()
    cpu_start = time.process_time()
    problem = prepare_problem(features, config)
    preparation_ms = (time.perf_counter() - start) * 1000
    result = search(problem, seed)
    result.timings_ms["feature_preparation_ms"] = preparation_ms
    return _finish_measurement(result, start, cpu_start)


CLASSICAL_METHODS = ("cosine", "fusion", "mmr", "greedy", "exact_quantized", "exact_float", "random")


def select_classical(features: CandidateFeatures, method: str, config: GASConfig | None = None,
                     seed: int = 0, lexical_scores: Sequence[float] | None = None,
                     objective_budget: int = 161, mmr_weight: float | None = None) -> SelectionResult:
    """Matched selectors. Exact baselines compute their own objective table.

    Random-search budget is matched to 2*phase_calls + measured_trials + 1
    when used alongside GAS. It never receives an exhaustive energy table.
    """
    if method not in CLASSICAL_METHODS:
        raise ValueError(f"Unknown classical selector {method!r}")
    if mmr_weight is not None and (method != "mmr" or not math.isfinite(mmr_weight) or
                                   not 0 <= mmr_weight <= 1):
        raise ValueError("mmr_weight requires the MMR method and a finite value in [0, 1]")
    _integer("seed", seed)
    seed = int(seed)
    _integer("objective_budget", objective_budget, 1)
    start = time.perf_counter()
    cpu_start = time.process_time()
    problem = prepare_problem(features, config)
    # Tune MMR independently, while scoring every returned set with the same
    # GAS objective for meaningful exact-optimum and utility comparisons.
    mmr_diversity = problem.config.diversity_weight if mmr_weight is None else mmr_weight
    n, k = len(features.ids), problem.count
    order = problem.cosine_order()
    selected = sorted(order[:k])
    evaluations = 1
    if method == "fusion":
        lexical = np.asarray(lexical_scores, dtype=float)
        if lexical.shape != (n,) or not np.isfinite(lexical).all():
            raise ValueError("Fusion requires one finite BM25 score per candidate")
        lexical_order = sorted(range(n), key=lambda i: (-lexical[i], features.ids[i]))
        dense_rank = {i: rank for rank, i in enumerate(order, 1)}
        sparse_rank = {i: rank for rank, i in enumerate(lexical_order, 1)}
        selected = sorted(range(n), key=lambda i:
                          (-(1 / (60 + dense_rank[i]) + 1 / (60 + sparse_rank[i])), features.ids[i]))[:k]
    elif method in {"mmr", "greedy"}:
        selected = []
        remaining = set(range(n))
        for _ in range(k):
            def score(i: int) -> float:
                if method == "mmr":
                    redundancy = max((problem.similarity[i, j] for j in selected), default=0.0)
                    return float((1 - mmr_diversity) * problem.relevance[i] -
                                 mmr_diversity * redundancy)
                return float(problem.linear[i] - sum(problem.quadratic[i, j] for j in selected))
            winner = min(remaining, key=lambda i: (-score(i), features.ids[i]))
            evaluations += len(remaining)
            selected.append(winner)
            remaining.remove(winner)
    elif method in {"exact_quantized", "exact_float"}:
        if method == "exact_quantized":
            layout, energies = enumerate_energies(problem)
            values = energies
        else:
            layout = subset_layout(n, k)
            values = -problem.relevance[layout].mean(axis=1) if k else np.zeros(len(layout))
            if k > 1:
                for a, b in itertools.combinations(range(k), 2):
                    values += (problem.config.diversity_weight / math.comb(k, 2) *
                               problem.similarity[layout[:, a], layout[:, b]])
        # Input-position ties are avoided: equal optima use document-ID order.
        minimum = float(values.min())
        tied = np.flatnonzero(values == minimum)
        winner = min(tied, key=lambda j: tuple(sorted(features.ids[i] for i in layout[j])))
        selected = layout[winner].tolist()
        evaluations = len(layout)
    elif method == "random" and n > k:
        rng = np.random.default_rng(seed)
        seen = {tuple(selected)}
        best = problem.energy(selected)
        limit = min(objective_budget, math.comb(n, k))
        while len(seen) < limit:
            sample = tuple(sorted(rng.choice(n, size=k, replace=False).tolist()))
            if sample in seen:
                continue
            seen.add(sample)
            energy = problem.energy(sample)
            if energy < best:
                selected, best = list(sample), energy
        evaluations = len(seen)
    result = _result(problem, method, selected, "completed", seed if method == "random" else None,
                     {}, {"classical_objective_evaluations": evaluations})
    if method in {"mmr", "fusion"}:
        result.ranked_ids = [features.ids[i] for i in selected]
        result.resources["ordering_policy"] = "native MMR" if method == "mmr" else "native reciprocal-rank fusion"
    if method == "mmr":
        result.resources["mmr_diversity_weight"] = mmr_diversity
    return _finish_measurement(result, start, cpu_start)


def selection_metrics(result: SelectionResult, relevance_judgments: dict[str, int]) -> dict[str, float]:
    """Pure metric calculation; no dataset access, downloads, or artifact writes."""
    from .metrics import ndcg_at, recall_at, mrr_at, precision_at

    positive = {d: grade for d, grade in relevance_judgments.items() if grade > 0}
    ranked = result.ranked_ids
    return {"nDCG@5": ndcg_at(ranked, positive, 5), "nDCG@8": ndcg_at(ranked, positive, 8),
            "Recall@5": recall_at(ranked, positive, 5), "Recall@8": recall_at(ranked, positive, 8),
            "MRR@5": mrr_at(ranked, positive, 5), "MRR@8": mrr_at(ranked, positive, 8),
            "P@5": precision_at(ranked, positive, 5), "redundancy": result.redundancy,
            "utility": result.utility}
