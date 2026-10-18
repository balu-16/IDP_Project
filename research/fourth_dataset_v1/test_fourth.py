"""Artificial fixtures only: graded loading, parity, recovery and provenance."""
from dataclasses import asdict
import contextlib
import io
import json
from pathlib import Path
import signal
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from research import datasets
from research.accuracy_v2.encoding import encode_sharded
from research.accuracy_v2.storage import sha, read_checked, write_checked
from research.accuracy_v3 import pipeline as frozen_pipeline
from research.accuracy_v3.core import Config
from research.accuracy_v3.experiment import synthetic_base
from . import data, experiment, pipeline, protocol, supervisor


class LoaderTests(unittest.TestCase):
    def fixture(self, root):
        (root / "qrels").mkdir()
        rows = [{"_id": "d1", "title": "Title", "text": "  first\n document "},
                {"_id": "d2", "title": "", "text": "second"}, {"_id": "d3", "title": "", "text": "third"}]
        (root / "corpus.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
        (root / "queries.jsonl").write_text(json.dumps({"_id": "q", "text": "query"}) + "\n")
        (root / "qrels/test.tsv").write_text("query-id\tcorpus-id\tscore\nq\td1\t2\nq\td2\t1\nq\td3\t0\n")

    def test_graded_and_zero_judgments_and_normalization(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            corpus, queries, rel = data.load(root, expected=False)
            self.assertEqual(corpus["d1"], "Title first document")
            self.assertEqual(rel["q"], {"d1": 2, "d2": 1, "d3": 0})
            self.assertEqual(experiment.diagnostics(["d1", "d3", "missing"], rel["q"]),
                {"Precision@8": .125, "judged@8": .25, "unjudged@8": .125, "nonrelevant_judged@8": .125})
            with self.assertRaisesRegex(ValueError, "coverage"):
                data.load(root)

    def test_duplicate_missing_and_invalid_grades(self):
        for extra in ("q\td1\t1\n", "q\tmissing\t1\n", "missing\td1\t1\n", "q\td2\t-2\n"):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.fixture(root)
                with (root / "qrels/test.tsv").open("a") as f:
                    f.write(extra)
                with self.assertRaises(ValueError):
                    data.load(root, expected=False)

    def test_independent_graded_metrics_both_cutoffs_and_precision(self):
        rel = {"d1": 2, "d2": 1, "d3": 0, "unjudged": -1}
        result = experiment.independent_metrics([(["d2", "d3", "unjudged", "missing", "d1"], rel)] * 2)
        self.assertEqual(result["requests_covered"], 2)
        self.assertEqual(result["unique_requests"], 1)
        self.assertEqual(result["checks"], 4)
        diagnostic = experiment.diagnostics(["d1", "d3", "unjudged", "missing"], rel)
        self.assertEqual(diagnostic["judged@8"], .25)
        self.assertEqual(diagnostic["unjudged@8"], .25)


class RecoveryTests(unittest.TestCase):
    def identity(self, queries):
        return {**protocol.code_identity(), "methods": frozen_pipeline.expected_methods(),
                "base_frozen": synthetic_base(), "config": asdict(Config()), "query_ids": sorted(queries)}

    def rankings(self, store, queries):
        return {q: {m: [r["ranked_ids"] for r in p["per_seed_results"].values()] if "per_seed_results" in p else p["result"]["ranked_ids"]
                    for m, p in store.get("queries", q)["methods"].items()} for q in queries}

    def test_isolated_runtime_uses_exact_frozen_kernels(self):
        self.assertIs(pipeline.Runtime.retrieve, frozen_pipeline.Runtime.retrieve)
        self.assertIs(pipeline.Runtime.enrich, frozen_pipeline.Runtime.enrich)
        self.assertIs(pipeline.Runtime.expand, frozen_pipeline.Runtime.expand)
        self.assertIs(experiment.execute_features, frozen_pipeline.execute_features)
        self.assertEqual(protocol.controls()[0]["legacy_threshold"], .7)
        self.assertEqual(protocol.controls()[0]["config"]["lexical_weight"], .25)

    def test_retrieval_features_and_result_interruption_resume(self):
        corpus, all_queries, _, _, _ = datasets.synthetic_splits()
        queries = {q: all_queries[q] for q in sorted(all_queries)[:2]}
        calls = {"retrieve": 0}
        class FakeRuntime(frozen_pipeline.Runtime):
            def __init__(self, corpus):
                super().__init__(corpus, full_controls=True, synthetic=True)
            def retrieve(self, query):
                calls["retrieve"] += 1
                return super().retrieve(query)
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            ident = self.identity(queries)
            clean = protocol.Store(root / "clean", ident)
            experiment.collect_into(clean, corpus, queries, FakeRuntime)
            expected = self.rankings(clean, queries)
            for event, stage in (("after_commit", "retrieved"), ("after_commit", "original_features"),
                                 ("before_commit", "features"), ("after_commit", "features"),
                                 ("before_commit", "queries"), ("after_commit", "queries")):
                calls["retrieve"] = 0
                target = protocol.Store(root / (event + stage), ident)
                fired = False
                def interrupt(actual_event, actual_stage, qid):
                    nonlocal fired
                    if (actual_event, actual_stage) == (event, stage) and not fired:
                        fired = True
                        raise InterruptedError("fault injection")
                with self.assertRaises(InterruptedError):
                    experiment.collect_into(target, corpus, queries, FakeRuntime, interrupt)
                committed = {q: sha(target.file("queries", q)) for q in queries if target.file("queries", q).exists()}
                restored = protocol.Store(target.path, ident, resume=True)
                experiment.collect_into(restored, corpus, queries, FakeRuntime)
                restored.verify()
                self.assertEqual(self.rankings(restored, queries), expected)
                self.assertEqual(calls["retrieve"], 2)
                for q, checksum in committed.items():
                    self.assertEqual(sha(restored.file("queries", q)), checksum)
                for q in queries:
                    record = restored.get("queries", q)
                    for seed, result in record["methods"]["gas_v3"]["per_seed_results"].items():
                        self.assertEqual(result["ranked_ids"][:5], record["methods"]["gas_l6"]["per_seed_results"][seed]["ranked_ids"][:5])

    def test_corruption_changed_source_and_incompatible_resume_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            ident = self.identity(["q"])
            store = protocol.Store(directory, ident)
            store.put("features", "q", {"value": 1})
            store.file("features", "q").write_text("{}")
            with self.assertRaisesRegex(ValueError, "Corrupt checkpoint"):
                store.get("features", "q")
            with self.assertRaisesRegex(ValueError, "Resume identity mismatch"):
                protocol.Store(directory, {**ident, "query_ids": ["other"]}, resume=True)
            snapshot = Path(directory) / "source_snapshot/research/fourth_dataset_v1/pipeline.py"
            snapshot.write_text("changed")
            with self.assertRaisesRegex(ValueError, "snapshot corrupt"):
                protocol.Store(directory, ident, resume=True)

    def test_new_evaluation_and_report_end_to_end_on_artificial_queries(self):
        corpus, all_queries, all_rel, _, _ = datasets.synthetic_splits()
        queries = {q: all_queries[q] for q in sorted(all_queries)[:2]}
        judgments = {q: all_rel[q] for q in queries}
        ident = {**self.identity(queries), "limitations": "Artificial fixture only",
            "statistical_family": {"baselines": ["gas_l6"], "metrics": ["nDCG@5", "Recall@8", "nDCG@8", "redundancy"]}}
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            study = Path(directory)
            store = protocol.Store(study / "test", ident)
            factory = lambda c: frozen_pipeline.Runtime(c, full_controls=True, synthetic=True)
            experiment.collect_into(store, corpus, queries, factory)
            manifest = store.verify()
            with patch.object(experiment, "open_completed", return_value=(store, manifest)), patch.object(data, "load", return_value=(corpus, queries, judgments)):
                experiment.evaluate(study)
                experiment.report(study)
            result = read_checked(study / "test/evaluation.json")
            self.assertEqual(result["query_count"], 2)
            self.assertEqual(len(result["means"]), 27)
            self.assertEqual(result["comparisons"]["gas_l6"]["nDCG@5"]["p_value"], 1.)
            self.assertEqual(result["official_metrics"]["checks"], 4 * result["official_metrics"]["unique_requests"])
            self.assertIn("Optimization and termination", (study / "test/REPORT.md").read_text())

    def test_corrupt_intermediate_artifact_cannot_be_sealed(self):
        corpus, all_queries, _, _, _ = datasets.synthetic_splits()
        queries = {q: all_queries[q] for q in sorted(all_queries)[:1]}
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            store = protocol.Store(directory, self.identity(queries))
            factory = lambda c: frozen_pipeline.Runtime(c, full_controls=True, synthetic=True)
            def corrupt(event, stage, qid):
                if event == "after_commit" and stage == "queries":
                    store.file("retrieved", qid).write_text("corrupt")
            with self.assertRaisesRegex(ValueError, "Corrupt checkpoint"):
                experiment.collect_into(store, corpus, queries, factory, corrupt)
            self.assertFalse((Path(directory) / "manifest.json").exists())

    def test_embedding_shards_reused_and_corruption_rejected(self):
        calls = []
        class Model:
            def encode(self, texts, **kwargs):
                calls.extend(texts)
                return np.array([[int(t) + 1., 2.] for t in texts])
        space = SimpleNamespace(model=Model())
        texts = list(map(str, range(7)))
        with tempfile.TemporaryDirectory() as directory, patch("research.accuracy_v2.encoding.legacy_key", return_value="test-key"), contextlib.redirect_stdout(io.StringIO()):
            def stop(event, begin):
                if event == "after_embedding_commit" and begin == 0:
                    raise InterruptedError("encoding interruption")
            with self.assertRaises(InterruptedError):
                encode_sharded(space, texts, directory, shard_rows=3, hook=stop)
            matrix, metadata = encode_sharded(space, texts, directory, shard_rows=3)
            self.assertEqual(calls, texts)
            self.assertEqual(metadata["reused_shard_rows"], 3)
            np.testing.assert_array_equal(matrix, [[i + 1., 2.] for i in range(7)])
            path = Path(directory) / "test-key.npy"
            with path.open("r+b") as f:
                f.write(b"corrupt")
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                encode_sharded(space, texts, directory, shard_rows=3)


class SupervisorTests(unittest.TestCase):
    def test_corrupt_progress_stops_active_worker(self):
        import subprocess
        handlers = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
        try:
            with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
                study = Path(directory)
                write_checked(study / "frozen.json", {"fixture": True})
                (study / "encoding_progress.json").write_text("corrupt")
                children = []
                class Child:
                    pid = 123456
                    def __init__(self, command, **kwargs):
                        self.command, self.terminated = command, False
                        children.append(self)
                    def poll(self):
                        return 130 if self.terminated else None
                    def wait(self, timeout=None):
                        if self.terminated:
                            return 130
                        raise subprocess.TimeoutExpired(self.command, timeout)
                    def send_signal(self, signum):
                        self.terminated = True
                with patch.object(supervisor, "require_frozen", return_value={}), patch.object(supervisor.subprocess, "Popen", Child):
                    with self.assertRaisesRegex(ValueError, "Corrupt checkpoint"):
                        supervisor.supervise(study)
                self.assertTrue(children[0].terminated)
                self.assertEqual(len(children), 1)
                self.assertEqual(read_checked(study / "execution.json")["status"], "failed")
        finally:
            for signum, handler in handlers.items():
                signal.signal(signum, handler)

    def test_execution_error_stops_progress_and_resume_skips_completed_stage(self):
        handlers = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
        try:
            with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
                study = Path(directory)
                write_checked(study / "frozen.json", {"fixture": True})
                launched, fail = [], [True]
                class Child:
                    pid = 123456
                    def __init__(self, command, **kwargs):
                        stage = command[4]
                        launched.append(stage)
                        self.returncode = 1 if fail[0] and stage == "run" else 0
                        if not self.returncode:
                            artifact = {"encode": "encoding.json", "run": "test/manifest.json",
                                        "evaluate": "test/evaluation.json", "report": "test/REPORT.md"}[stage]
                            write_checked(study / artifact, {"gate": {"passed": True}})
                    def poll(self):
                        return self.returncode
                with patch.object(supervisor, "require_frozen", return_value={}), patch.object(supervisor.subprocess, "Popen", Child):
                    with self.assertRaisesRegex(RuntimeError, "run exited 1"):
                        supervisor.supervise(study)
                    state = read_checked(study / "execution.json")
                    self.assertEqual(state["status"], "failed")
                    self.assertEqual(state["stages"]["run"]["status"], "failed")
                    self.assertEqual(launched, ["encode", "run"])
                    fail[0] = False
                    self.assertEqual(supervisor.supervise(study, resume=True), "completed")
                    self.assertEqual(launched, ["encode", "run", "run", "evaluate", "report"])
        finally:
            for signum, handler in handlers.items():
                signal.signal(signum, handler)

    def test_failed_scientific_gate_is_retained_after_all_stages(self):
        handlers = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
        try:
            with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
                study = Path(directory)
                write_checked(study / "frozen.json", {"fixture": True})
                launched = []
                class Child:
                    pid = 123456
                    returncode = 0
                    def __init__(self, command, **kwargs):
                        stage = command[4]
                        launched.append(stage)
                        artifact = {"encode": "encoding.json", "run": "test/manifest.json",
                                    "evaluate": "test/evaluation.json", "report": "test/REPORT.md"}[stage]
                        write_checked(study / artifact, {"gate": {"passed": False}})
                    def poll(self):
                        return self.returncode
                with patch.object(supervisor, "require_frozen", return_value={}), patch.object(supervisor.subprocess, "Popen", Child):
                    self.assertEqual(supervisor.supervise(study), "gate_failed")
                self.assertEqual(launched, ["encode", "run", "evaluate", "report"])
                self.assertEqual(read_checked(study / "execution.json")["committed_queries"], 50)
        finally:
            for signum, handler in handlers.items():
                signal.signal(signum, handler)


if __name__ == "__main__":
    unittest.main()
