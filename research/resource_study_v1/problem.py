"""Explicit integer objective and independently readable constraint semantics."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import itertools
import math

import numpy as np

from research.accuracy_v2.core import ScoredFeatures, take
from research.accuracy_v3.core import Config, prepare
from research.selection import CandidateFeatures

POOLS = (3, 5, 8, 12, 16, 20)
BITS = (4, 8, 12, 16)
SEEDS = (0, 1, 2, 3, 4)
EPS = 1e-12


def stable(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def eligible(scored, baseline):
    if len(baseline) != 8:
        return []
    by_id = dict(zip(scored.candidates.ids, scored.l6_logits))
    cutoff = min(by_id[d] for d in baseline[5:])
    return sorted(d for d in by_id if d not in baseline[:5] and by_id[d] >= cutoff - EPS)


def restrict(scored, baseline, count, namespace="resource-study-v1"):
    """Keep the original three tail documents for every nested candidate pool."""
    pool = eligible(scored, baseline)
    if len(pool) < count:
        return None
    original = list(baseline[5:])
    rest = sorted(set(pool) - set(original), key=lambda d: (stable(namespace + ":" + d), d))
    chosen = list(baseline[:5]) + sorted(original + rest[:count-3])
    index = {d: i for i, d in enumerate(scored.candidates.ids)}
    return ScoredFeatures(take(scored.candidates, [index[d] for d in chosen]),
                          [scored.l6_logits[index[d]] for d in chosen])


def synthetic(count):
    """Explicitly artificial stress data, never reported as retrieval evidence."""
    ids = tuple([f"H{i}" for i in range(5)] + [f"T{i:02}" for i in range(count)])
    rng = np.random.default_rng(5821 + count)
    vectors = rng.normal(size=(len(ids), 32))
    vectors[:8] = 0
    vectors[:8, 0] = 1
    if count > 3:
        vectors[8:, 0] = 0
    scored = ScoredFeatures(CandidateFeatures(ids, np.zeros(len(ids)), vectors), np.full(len(ids), -1.))
    return scored, list(ids[:8])


@dataclass
class OracleProblem:
    scored: ScoredFeatures
    baseline: list[str]
    bits: int

    def __post_init__(self):
        if not 1 <= self.bits <= 16:
            raise ValueError("Coefficient bits must be in [1,16]")
        p = prepare(self.scored, self.baseline, Config(coefficient_bits=self.bits))
        if len(p["head"]) != 5 or len(p["base"]) != 8 or len(p["pool"]) < 3:
            raise ValueError("Resource oracle requires five protected and three selected tail documents")
        self.pool = list(p["pool"])
        self.head = list(p["head"])
        self.ids = [self.scored.candidates.ids[i] for i in self.pool]
        self.m = len(self.pool)
        scale = (1 << self.bits) - 1
        q = np.rint(scale * p["sim"]).astype(np.int64)
        self.constant = int(sum(q[i, j] for i, j in itertools.combinations(self.head, 2)))
        self.linear = q[np.ix_(self.pool, self.head)].sum(axis=1).astype(np.int64)
        self.quadratic = np.triu(q[np.ix_(self.pool, self.pool)], 1)
        self.initial = [self.ids.index(d) for d in self.baseline[5:]]
        self.incumbent = self.energy(self.initial)
        self.offset = self.constant - self.incumbent
        self.lower = self.offset
        self.upper = self.offset + int(self.linear.sum()) + int(self.quadratic.sum())
        self.width = 1
        while self.lower < -(1 << (self.width-1)) or self.upper >= 1 << (self.width-1):
            self.width += 1
        self.count_width = self.m.bit_length()
        z = self.scored.l6_logits
        index = {d: i for i, d in enumerate(self.scored.candidates.ids)}
        self.thresholds = sorted(float(z[index[d]]) for d in self.baseline[5:])
        self.groups = [[j for j, i in enumerate(self.pool) if z[i] >= value - EPS]
                       for value in self.thresholds]

    def energy(self, selected):
        return self.constant + int(self.linear[list(selected)].sum()) + sum(
            int(self.quadratic[min(i, j), max(i, j)]) for i, j in itertools.combinations(selected, 2))

    def marked(self, address):
        selected = [i for i in range(self.m) if address >> i & 1]
        if len(selected) != 3:
            return False
        # Deliberately use the sorted-logit definition, independently of the
        # count comparators used in the quantum circuit.
        z = dict(zip(self.scored.candidates.ids, self.scored.l6_logits))
        values = sorted(float(z[self.ids[i]]) for i in selected)
        return (all(a >= b - EPS for a, b in zip(values, self.thresholds))
                and self.energy(selected) < self.incumbent)

    def expected_uniform_phase(self):
        return np.array([(-1 if self.marked(i) else 1) / math.sqrt(1 << self.m)
                         for i in range(1 << self.m)], dtype=complex)

    def expected_iteration(self):
        state = np.zeros(1 << self.m, dtype=complex)
        for selected in itertools.combinations(range(self.m), 3):
            state[sum(1 << i for i in selected)] = 1 / math.sqrt(math.comb(self.m, 3))
        phased = state * np.array([-1 if self.marked(i) else 1 for i in range(len(state))])
        return 2 * np.vdot(state, phased) * state - phased
