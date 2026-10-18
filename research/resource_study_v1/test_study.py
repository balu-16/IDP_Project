"""Small exhaustive native-oracle checks; no retrieval or model inference."""
from dataclasses import replace
import itertools
import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

import numpy as np

from research.accuracy_v2.core import ScoredFeatures
from .problem import OracleProblem, restrict, synthetic


class ProblemTests(unittest.TestCase):
    def test_nested_pools_keep_incumbent_and_precision_has_safe_signed_range(self):
        scored, base = synthetic(20)
        previous = set()
        for m in (3, 5, 8, 12, 16, 20):
            limited = restrict(scored, base, m)
            self.assertTrue(set(base) <= set(limited.candidates.ids))
            self.assertTrue(previous <= set(limited.candidates.ids))
            previous = set(limited.candidates.ids)
            for bits in (4, 8, 12, 16):
                p = OracleProblem(limited, base, bits)
                self.assertEqual(p.m, m)
                self.assertGreaterEqual(p.lower, -(1 << (p.width-1)))
                self.assertLess(p.upper, 1 << (p.width-1))
                self.assertFalse(p.marked(sum(1 << i for i in p.initial)))
        self.assertIsNone(restrict(scored, base, 21))

    def test_integer_objective_matches_independent_pair_sum_and_score_counts(self):
        scored, base = synthetic(5)
        scored = ScoredFeatures(scored.candidates, [3]*5 + [0, 1, 2, 3, .5])
        p = OracleProblem(scored, base, 4)
        ids = list(scored.candidates.ids)
        vectors = scored.candidates.embeddings
        z = dict(zip(ids, scored.l6_logits))
        def independent(selected):
            chosen = base[:5] + [p.ids[i] for i in selected]
            return sum(round(15 * max(0., min(1., float(vectors[ids.index(a)] @ vectors[ids.index(b)]))))
                       for a, b in itertools.combinations(chosen, 2))
        for length in range(6):
            for selected in itertools.combinations(range(5), length):
                address = sum(1 << i for i in selected)
                self.assertEqual(p.energy(selected), independent(selected))
                values = sorted(z[p.ids[i]] for i in selected)
                valid = length == 3 and all(a >= b-1e-12 for a, b in zip(values, p.thresholds))
                counts = length == 3 and all(sum(i in group for i in selected) >= n
                                            for group, n in zip(p.groups, (3, 2, 1)))
                self.assertEqual(valid, counts)
                self.assertEqual(p.marked(address), valid and independent(selected) < independent(p.initial))
        self.assertTrue(any(p.marked(i) for i in range(32)))
        self.assertTrue(any(i.bit_count() == 3 and not p.marked(i) for i in range(32)))


class NativeCircuitTests(unittest.TestCase):
    def test_phase_complete_iteration_and_workspace_on_small_instances(self):
        from .circuits import oracle, complete_iteration, simulate_small, synthesize
        for m, bits in ((3, 2), (5, 2), (5, 4)):
            scored, base = synthetic(m)
            if m == 5:
                scored = ScoredFeatures(scored.candidates, [3]*5 + [0, 1, 2, 3, .5])
            p = OracleProblem(scored, base, bits)
            phase, layout = oracle(p)
            self.assertEqual(layout["total"], phase.num_qubits)
            uniform = phase.copy_empty_like()
            uniform.h(range(m))
            uniform.compose(phase, inplace=True)
            report = simulate_small(uniform, p, p.expected_uniform_phase())
            self.assertLess(report["maximum_density_error"], 1e-8)
            iteration = complete_iteration(p, phase)
            report = simulate_small(iteration, p, p.expected_iteration())
            self.assertAlmostEqual(report["zero_workspace_probability_lower_bound"], 1)
            compiled, stats = synthesize(phase)
            self.assertGreater(stats["depth"], 0)
            self.assertTrue(set(compiled.count_ops()) <= {"u", "cx"})


class RecoveryTests(unittest.TestCase):
    def test_interruption_reuses_complete_tasks_and_rejects_corruption(self):
        from .runner import Executor
        from .storage import read_result, result_path, write_checked
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            write_checked(directory / "protocol.json", {"test_identity": "synthetic-only"})
            calls = []
            interrupt = False
            class Child:
                def __init__(child, command, **kwargs):
                    calls.append(command)
                    write_checked(Path(command[-1]), {"status": "completed", "rows": [{"ranking": ["a", "b"]}]})
                def wait(child, timeout=None):
                    if interrupt:
                        raise KeyboardInterrupt()
                    return 0
                def poll(child):
                    return 0
            a = {"dataset": "synthetic", "qid": "a", "kind": "compact"}
            b = {"dataset": "synthetic", "qid": "b", "kind": "compact"}
            with patch("research.resource_study_v1.runner.load_input", return_value={}), \
                 patch("research.resource_study_v1.runner.subprocess.Popen", Child):
                execution = Executor(directory)
                first, reused = execution.execute(a)
                self.assertFalse(reused)
                second, reused = execution.execute(a)
                self.assertTrue(reused)
                self.assertEqual(first, second)
                self.assertEqual(len(calls), 1)
                interrupt = True
                with self.assertRaises(KeyboardInterrupt):
                    execution.execute(b)
                self.assertIsNone(read_result(directory, b))
                interrupt = False
                resumed, reused = Executor(directory).execute(b)
                self.assertEqual(resumed["output"], first["output"])
                self.assertTrue(list((directory / "pending").glob("*.uncommitted-*.json")))
                count = len(calls)
                result_path(directory, a).write_text("corrupt")
                with self.assertRaises(ValueError):
                    execution.execute(a)
                self.assertEqual(len(calls), count)


if __name__ == "__main__":
    unittest.main()
