"""Metrics + paired statistics (plan A.5). Pure numpy, no extra deps.

Primary nDCG@10; secondary Recall@10/64, MRR@10, P@5.
Stats: paired query-level bootstrap 10k (95% CI), mean difference,
paired randomization test, Cohen's dz, Holm correction over declared family.
Stochastic seeds must already be averaged within query before calling.
"""
from __future__ import annotations

import math
import numpy as np


def dcg(gains: list[int], k: int) -> float:
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains[:k]))


def ndcg_at(ranked: list[str], relevant: dict[str, int], k: int = 10) -> float:
    gains = [relevant.get(d, 0) for d in ranked]
    ideal = sorted(relevant.values(), reverse=True)
    denom = dcg(ideal, k)
    return dcg(gains, k) / denom if denom > 0 else 0.0


def recall_at(ranked: list[str], relevant: dict[str, int], k: int) -> float:
    if not relevant:
        return 0.0
    hit = sum(1 for d in ranked[:k] if d in relevant)
    return hit / len(relevant)


def mrr_at(ranked: list[str], relevant: dict[str, int], k: int = 10) -> float:
    for i, d in enumerate(ranked[:k]):
        if d in relevant:
            return 1.0 / (i + 1)
    return 0.0


def precision_at(ranked: list[str], relevant: dict[str, int], k: int = 5) -> float:
    if k <= 0:
        return 0.0
    return sum(1 for d in ranked[:k] if d in relevant) / k


def per_query_scores(rankings: dict[str, list[str]], qrels: dict[str, dict[str, int]]):
    out: dict[str, dict[str, float]] = {}
    for qid, ranked in rankings.items():
        rel = qrels.get(qid, {})
        out[qid] = {
            "nDCG@10": ndcg_at(ranked, rel, 10),
            "Recall@10": recall_at(ranked, rel, 10),
            "Recall@64": recall_at(ranked, rel, 64),
            "MRR@10": mrr_at(ranked, rel, 10),
            "P@5": precision_at(ranked, rel, 5),
        }
    return out


def mean_scores(per_query: dict[str, dict[str, float]]):
    keys = ["nDCG@10", "Recall@10", "Recall@64", "MRR@10", "P@5"]
    return {k: float(np.mean([v[k] for v in per_query.values()])) for k in keys} if per_query else {k: 0.0 for k in keys}


def paired_bootstrap(a: dict[str, float], b: dict[str, float], n_resamples: int = 10_000,
                     seed: int = 0, ci: float = 0.95):
    """Bootstrap mean(b-a) with paired resampling over queries."""
    qids = sorted(set(a) & set(b))
    diffs = np.array([b[q] - a[q] for q in qids])
    rng = np.random.default_rng(seed)
    means = np.array([rng.choice(diffs, size=len(diffs), replace=True).mean() for _ in range(n_resamples)])
    lo_q = (1 - ci) / 2 * 100
    return {"mean_diff": float(diffs.mean()) if len(diffs) else 0.0,
            "ci_low": float(np.percentile(means, lo_q)) if len(diffs) else 0.0,
            "ci_high": float(np.percentile(means, 100 - lo_q)) if len(diffs) else 0.0,
            "n_queries": len(qids)}


def paired_randomization(a: dict[str, float], b: dict[str, float], n_perm: int = 10_000, seed: int = 1):
    qids = sorted(set(a) & set(b))
    diffs = np.array([b[q] - a[q] for q in qids])
    obs = float(np.abs(diffs.mean())) if len(diffs) else 0.0
    rng = np.random.default_rng(seed)
    signs = rng.choice([-1.0, 1.0], size=(n_perm, len(diffs)))
    perm_means = np.abs((signs * diffs).mean(axis=1))
    p = float((np.sum(perm_means >= obs) + 1) / (n_perm + 1)) if len(diffs) else 1.0
    # Cohen's dz on differences
    std = float(diffs.std(ddof=1)) if len(diffs) > 1 else 0.0
    dz = float(diffs.mean() / std) if std > 0 else 0.0
    return {"p_value": p, "effect_dz": dz, "obs_abs_diff": obs}


def holm(p_values: dict[str, float], alpha: float = 0.05):
    """Proper Holm step-down with stop on first failure.

    Sort ascending; reject while p < alpha/(m-i+1); on first failure stop
    and mark it plus all remaining non-significant (issue 7). Matches
    statsmodels.multipletests(method='holm').
    """
    ordered = sorted(p_values.items(), key=lambda kv: kv[1])
    m = len(ordered)
    out: dict[str, dict] = {}
    failed = False
    for i, (name, p) in enumerate(ordered, start=1):
        level = alpha / (m - i + 1)
        if not failed and p < level:
            out[name] = {"p": p, "rank": i, "holm_alpha": level, "significant": True}
        else:
            failed = True
            out[name] = {"p": p, "rank": i, "holm_alpha": level, "significant": False}
    return out
