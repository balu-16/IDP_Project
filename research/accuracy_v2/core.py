"""Score-explicit fixed-cardinality GAS and matched classical controls.

Only the simulator's oracle implementation sees the enumerated energies. The
adaptive controller does not receive an optimum or a marked-state count.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import itertools
import math
import time

import numpy as np

from research.selection import CandidateFeatures, GASConfig, SelectionResult, grover_step, subset_layout

SEEDS = (0, 1, 2, 3, 4)
BETAS = (0.0, 0.25, 0.5)
PENALTIES = (0.0, 0.01, 0.025, 0.05)
MMR_WEIGHTS = (0.0, 0.1, 0.25, 0.5, 0.75, 1.0)
GUIDED = ("gas_l6", "l6_only", "greedy_l6", "exact_quantized_l6", "exact_float_l6", "mmr_l6", "random_l6")


@dataclass(frozen=True)
class Config:
    lexical_weight: float = 0.25
    diversity_weight: float = 0.05
    candidate_limit: int = 15
    selected_count: int = 8
    coefficient_bits: int = 8
    max_oracle_calls: int = 64
    max_trials: int = 32
    time_limit_seconds: float = 15.0
    window_growth: float = 1.2
    max_subsets: int = 200_000

    def __post_init__(self):
        self.gas_config()  # Reuse the frozen runner's strict configuration checks.
        if isinstance(self.lexical_weight, bool) or not math.isfinite(self.lexical_weight) or not 0 <= self.lexical_weight <= 1:
            raise ValueError("lexical_weight must be finite and in [0, 1]")

    def gas_config(self):
        return GASConfig(**{k: v for k, v in asdict(self).items() if k != "lexical_weight"})


def normalize_relevance(scores):
    scores = np.asarray(scores, dtype=np.float64)
    if scores.ndim != 1 or not np.isfinite(scores).all():
        raise ValueError("L6 logits must be a finite one-dimensional array")
    if not len(scores):
        return scores.copy()
    span = float(scores.max() - scores.min())
    if not math.isfinite(span):
        raise ValueError("L6 logit range overflow")
    return np.full(len(scores), 0.5) if span <= 1e-12 else (scores - scores.min()) / span


def hybrid_scores(cosine, lexical, beta=0.25):
    """Exact normalization used in the saved 32-query feasibility experiment."""
    cosine, lexical = np.asarray(cosine, dtype=float), np.asarray(lexical, dtype=float)
    if (cosine.ndim != 1 or cosine.shape != lexical.shape or not np.isfinite(cosine).all()
            or not np.isfinite(lexical).all() or np.any(np.abs(cosine) > 1 + 1e-6)
            or np.any(lexical < 0) or not math.isfinite(beta) or not 0 <= beta <= 1):
        raise ValueError("Invalid hybrid score inputs")
    if not len(cosine):
        return cosine.copy()
    cosine = np.clip(cosine, -1, 1)
    denominator = 1 + cosine.max()
    dense = (1 + cosine) / denominator if denominator > 1e-12 else (1 + cosine) / 2
    return (1 - beta) * dense + beta * lexical / lexical.max() if lexical.max() > 1e-12 else dense


def shortlist(ids, cosine, lexical, beta=0.25, count=15):
    if len(ids) != len(set(ids)) or len(ids) != len(cosine):
        raise ValueError("Shortlist IDs must be unique and aligned with scores")
    scores = hybrid_scores(cosine, lexical, beta)
    return sorted(range(len(ids)), key=lambda i: (-scores[i], ids[i]))[:count]


def take(features: CandidateFeatures, indices):
    return CandidateFeatures(tuple(features.ids[i] for i in indices), features.cosine_scores[indices],
                             features.embeddings[indices],
                             tuple(features.passages[i] for i in indices) if features.passages else (),
                             tuple(features.representative_ids[i] for i in indices) if features.representative_ids else ())


@dataclass(frozen=True)
class ScoredFeatures:
    candidates: CandidateFeatures
    l6_logits: np.ndarray

    def __post_init__(self):
        logits = np.array(self.l6_logits, dtype=np.float64, copy=True)
        if logits.shape != (len(self.candidates.ids),) or not np.isfinite(logits).all():
            raise ValueError("Each candidate requires one finite raw L6 logit")
        normalize_relevance(logits)
        logits.setflags(write=False)
        object.__setattr__(self, "l6_logits", logits)

    def to_dict(self):
        return {"candidates": self.candidates.to_dict(), "l6_logits": self.l6_logits.tolist(),
                "relevance_source": "raw pinned L6 logits, per-pool min-max normalization"}

    @classmethod
    def from_dict(cls, value):
        return cls(CandidateFeatures.from_dict(value["candidates"]), value["l6_logits"])


@dataclass(frozen=True)
class Problem:
    features: ScoredFeatures
    config: Config
    count: int
    relevance: np.ndarray
    similarity: np.ndarray
    linear: np.ndarray
    quadratic: np.ndarray

    @property
    def ids(self):
        return self.features.candidates.ids

    def order(self, indices=None):
        indices = range(len(self.ids)) if indices is None else indices
        return sorted(indices, key=lambda i: (-self.features.l6_logits[i], self.ids[i]))

    def energy(self, indices):
        return int(-self.linear[list(indices)].sum() + sum(int(self.quadratic[i, j]) for i, j in itertools.combinations(indices, 2)))

    def redundancy(self, indices):
        pairs = list(itertools.combinations(indices, 2))
        return float(np.mean([self.similarity[i, j] for i, j in pairs])) if pairs else 0.0

    def utility(self, indices):
        return float(self.relevance[list(indices)].mean() - self.config.diversity_weight * self.redundancy(indices)) if len(indices) else 0.0

    def resources(self):
        n, k = len(self.ids), self.count
        lower = -int(np.sort(self.linear)[-k:].sum()) if k else 0
        pairs = math.comb(k, 2)
        values = self.quadratic[np.triu_indices(n, 1)]
        upper = int(np.sort(values)[-pairs:].sum()) if pairs else 0
        width = max(1, int(upper - lower).bit_length() + 1)
        return {"feasible_subsets": math.comb(n, k), "decision_qubits": n, "value_qubits": width,
                "logical_total_qubits": n + width, "energy_lower_bound": lower, "energy_upper_bound": upper,
                "compact_amplitude_bytes": math.comb(n, k) * 16,
                "full_statevector_bytes_estimate": (1 << (n + width)) * 16,
                "ordering_policy": "raw L6 logits descending, document-ID tie-break",
                "relevance_source": "L6 per-pool min-max; constant range -> 0.5",
                "similarity_source": "original normalized MiniLM representative embeddings",
                "representation": "compact feasible-subset simulation; no physical QPU timing"}


def prepare(features: ScoredFeatures, config=Config()):
    n = len(features.candidates.ids)
    if n > config.candidate_limit:
        raise ValueError("Prefilter candidates explicitly before GAS")
    k = min(n, config.selected_count)
    relevance = normalize_relevance(features.l6_logits)
    similarity = np.clip(features.candidates.embeddings @ features.candidates.embeddings.T, 0, 1)
    np.fill_diagonal(similarity, 0)
    scale = (1 << config.coefficient_bits) - 1
    linear = np.rint(scale * relevance).astype(np.int64)
    quadratic = np.rint(scale * 2 * config.diversity_weight / (k - 1) * similarity).astype(np.int64) if k > 1 else np.zeros((n, n), dtype=np.int64)
    for array in (relevance, similarity, linear, quadratic):
        array.setflags(write=False)
    return Problem(features, config, k, relevance, similarity, linear, quadratic)


def enumerate_energies(problem):
    layout = subset_layout(len(problem.ids), problem.count)
    energies = -problem.linear[layout].sum(axis=1, dtype=np.int64)
    for a, b in itertools.combinations(range(problem.count), 2):
        energies += problem.quadratic[layout[:, a], layout[:, b]]
    return layout, energies


def _result(problem, method, chosen, start, cpu, counts, seed=None, status="completed", trace=None, timings=None):
    timings = dict(timings or {})
    timings.update(total_ms=(time.perf_counter() - start) * 1000, cpu_ms=(time.process_time() - cpu) * 1000)
    return SelectionResult(method, sorted(problem.ids[i] for i in chosen), [problem.ids[i] for i in problem.order(chosen)],
                           problem.energy(chosen), problem.utility(chosen), problem.redundancy(chosen), status,
                           seed, problem.resources(), timings, counts, trace or [], asdict(problem.config))


def select(features, method="gas_l6", config=Config(), seed=0, mmr_weight=0.0, objective_budget=161):
    if method not in GUIDED:
        raise ValueError(f"Unknown guided method {method}")
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)) or seed < 0:
        raise ValueError("Seed must be a nonnegative integer")
    if not math.isfinite(mmr_weight) or not 0 <= mmr_weight <= 1:
        raise ValueError("Invalid MMR weight")
    if isinstance(objective_budget, bool) or not isinstance(objective_budget, int) or objective_budget < 1:
        raise ValueError("objective_budget must be a positive integer")
    start, cpu = time.perf_counter(), time.process_time()
    problem = prepare(features, config)
    n, k = len(problem.ids), problem.count
    chosen = sorted(problem.order()[:k])
    counts = {"classical_objective_evaluations": 1}
    if method == "gas_l6":
        counts = {"phase_oracle_calls": 0, "reversible_objective_calls": 0, "measured_trials": 0,
                  "classical_search_objective_evaluations": 1, "classical_simulator_objective_evaluations": 0}
        if n <= k:
            return _result(problem, method, chosen, start, cpu, counts, seed, "trivial")
        if config.time_limit_seconds == 0 or config.max_oracle_calls == 0 or config.max_trials == 0:
            status = "time_limit" if config.time_limit_seconds == 0 else "oracle_budget" if config.max_oracle_calls == 0 else "trial_budget"
            return _result(problem, method, chosen, start, cpu, counts, seed, status)
        deadline = start + config.time_limit_seconds
        begin = time.perf_counter()
        layout, energies = enumerate_energies(problem)
        timings = {"enumeration_ms": (time.perf_counter() - begin) * 1000}
        counts["classical_simulator_objective_evaluations"] = len(layout)
        incumbent, window, rng, trace = problem.energy(chosen), 1.0, np.random.default_rng(seed), []
        status = "trial_budget"
        search_start = time.perf_counter()
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
            # The phase oracle, not the adaptive controller, uses this mask.
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
                raise ArithmeticError("Grover state lost normalization")
            address = int(rng.choice(len(layout), p=probabilities / norm))
            sample = layout[address].tolist()
            energy = problem.energy(sample)
            accepted = energy < incumbent
            counts["measured_trials"] += 1
            counts["classical_search_objective_evaluations"] += 1
            if accepted:
                chosen, incumbent, window = sample, energy, 1.0
            else:
                window = min(window * config.window_growth, math.sqrt(len(layout)))
            trace.append({"trial": trial, "iterations": completed, "measured": True,
                          "sampled_ids": [problem.ids[i] for i in sample], "sample_energy": energy,
                          "accepted": bool(accepted), "incumbent_before": before, "incumbent_after": incumbent,
                          "sample_probability": float(probabilities[address] / norm)})
        if status != "time_limit" and counts["phase_oracle_calls"] >= config.max_oracle_calls:
            status = "oracle_budget"
        timings["search_ms"] = (time.perf_counter() - search_start) * 1000
        return _result(problem, method, chosen, start, cpu, counts, seed, status, trace, timings)
    if method in {"greedy_l6", "mmr_l6"}:
        chosen, remaining = [], set(range(n))
        for _ in range(k):
            def value(i):
                if method == "mmr_l6":
                    return (1 - mmr_weight) * problem.relevance[i] - mmr_weight * max((problem.similarity[i, j] for j in chosen), default=0)
                return problem.linear[i] - sum(problem.quadratic[i, j] for j in chosen)
            winner = min(remaining, key=lambda i: (-value(i), -features.l6_logits[i], problem.ids[i]))
            counts["classical_objective_evaluations"] += len(remaining)
            chosen.append(winner)
            remaining.remove(winner)
    elif method in {"exact_quantized_l6", "exact_float_l6"}:
        if method == "exact_quantized_l6":
            layout, values = enumerate_energies(problem)
        else:
            layout = subset_layout(n, k)
            values = -problem.relevance[layout].mean(axis=1) if k else np.zeros(len(layout))
            if k > 1:
                for a, b in itertools.combinations(range(k), 2):
                    values += config.diversity_weight / math.comb(k, 2) * problem.similarity[layout[:, a], layout[:, b]]
        tied = np.flatnonzero(values == values.min())
        winner = min(tied, key=lambda j: (-float(problem.relevance[layout[j]].sum()), tuple(sorted(problem.ids[i] for i in layout[j]))))
        chosen = layout[winner].tolist()
        counts["classical_objective_evaluations"] = len(layout)
    elif method == "random_l6" and n > k:
        rng, seen, incumbent = np.random.default_rng(seed), {tuple(chosen)}, problem.energy(chosen)
        while len(seen) < min(objective_budget, math.comb(n, k)):
            sample = tuple(sorted(rng.choice(n, size=k, replace=False).tolist()))
            if sample in seen:
                continue
            seen.add(sample)
            energy = problem.energy(sample)
            if energy < incumbent:
                chosen, incumbent = list(sample), energy
        counts["classical_objective_evaluations"] = len(seen)
    result = _result(problem, method, chosen, start, cpu, counts, seed if method == "random_l6" else None)
    if method == "mmr_l6":
        result.resources["ordering_policy"] = "native MMR with L6 relevance"
        result.resources["mmr_diversity_weight"] = mmr_weight
        result.ranked_ids = [problem.ids[i] for i in chosen]
    return result


def guided_methods(features, config=Config(), mmr_weight=0.0):
    gas = {str(seed): select(features, config=config, seed=seed).to_dict() for seed in SEEDS}
    methods = {"gas_l6": {"per_seed_results": gas}}
    methods["random_l6"] = {"per_seed_results": {str(seed): select(
        features, "random_l6", config, seed, objective_budget=2 * gas[str(seed)]["counts"]["phase_oracle_calls"]
        + gas[str(seed)]["counts"]["classical_search_objective_evaluations"]).to_dict() for seed in SEEDS}}
    for name in GUIDED:
        if name not in methods:
            methods[name] = {"result": select(features, name, config, mmr_weight=mmr_weight).to_dict()}
    return methods
