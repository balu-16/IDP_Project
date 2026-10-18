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


class SyntheticRuntime(frozen_pipeline.Runtime):
    def __init__(self, corpus):
        super().__init__(corpus, full_controls=True, synthetic=True)
    retrieve = pipeline.Runtime.retrieve



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
                "base_frozen": synthetic_base(), "config": asdict(Config()), "query_ids": sorted(queries), "stage_query_ids": sorted(queries)}

    def rankings(self, store, queries):
        return {q: {m: [r["ranked_ids"] for r in p["per_seed_results"].values()] if "per_seed_results" in p else p["result"]["ranked_ids"]
                    for m, p in store.get("queries", q)["methods"].items()} for q in queries}

    def test_isolated_runtime_uses_exact_frozen_kernels(self):
        self.assertIsNot(pipeline.Runtime.retrieve, frozen_pipeline.Runtime.retrieve)
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
            def retrieve(self, query, qid):
                calls["retrieve"] += 1
                return pipeline.Runtime.retrieve(self, query, qid)
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
            snapshot = Path(directory) / "source_snapshot/research/scidocs_500_v1/pipeline.py"
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
            factory = SyntheticRuntime
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
            factory = SyntheticRuntime
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


class SamplingAndGateTests(unittest.TestCase):
    def test_sampling_order_disjoint_stages_no_judgment_input(self):
        ids = [f"q{i}" for i in range(1000)]
        a, b = protocol.sampling(ids), protocol.sampling(reversed(ids))
        self.assertEqual(a, b)
        self.assertEqual(a["ordered_ids"], datasets.deterministic_query_subset(ids, "scidocs", 500, "scidocs-500-transfer-v1"))
        self.assertEqual(len(a["checkpoint"]), 100)
        self.assertEqual(len(a["continuation"]), 400)
        self.assertFalse(set(a["checkpoint"]) & set(a["continuation"]))
        self.assertEqual(a["ordered_ids"], a["checkpoint"] + a["continuation"])

    def test_self_exclusion_before_dense_top64_all_controls(self):
        corpus = {"self": "science medicine", **{f"d{i}": f"science evidence {i}" for i in range(70)}}
        runtime = SyntheticRuntime(corpus)
        bundle = runtime.retrieve("science medicine", "self")
        self.assertNotIn("self", bundle["full"]["ids"])
        self.assertEqual(len(bundle["full"]["ids"]), 64)
        self.assertEqual(bundle["self_excluded"], 1)
        enriched = runtime.expand("science medicine", runtime.enrich("science medicine", bundle, protocol.BaselineConfig()))
        record = experiment.execute_features(enriched, synthetic_base())
        pipeline.validate_record(record, enriched, frozen_pipeline.expected_methods())
        for payload in record["methods"].values():
            rows = payload.get("per_seed_results", {}).values() if "per_seed_results" in payload else [payload["result"]]
            for row in rows:
                self.assertNotIn("self", row["ranked_ids"])

    def test_effective_thread_profile_and_rejection(self):
        import torch, os
        with patch.dict(os.environ, {k: "2" for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")}), patch.object(torch, "get_num_threads", return_value=2), patch.object(torch, "get_num_interop_threads", return_value=1):
            self.assertEqual(protocol.assert_threads(), protocol.THREADS)
            with patch.object(torch, "get_num_threads", return_value=4):
                with self.assertRaisesRegex(ValueError, "thread profile"):
                    protocol.assert_threads()

    def test_missing_failed_and_changed_checkpoint_blocks_continuation(self):
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory)
            with self.assertRaisesRegex(ValueError, "missing"):
                experiment.require_checkpoint(study)
            write_checked(study / "checkpoint_outcome.json", {"passed": False})
            with patch.object(experiment, "freeze_checkpoint"):
                with self.assertRaisesRegex(ValueError, "FAILED"):
                    experiment.require_checkpoint(study)
                write_checked(study / "checkpoint_outcome.json", {"passed": True})
                self.assertTrue(experiment.require_checkpoint(study)["passed"])
            with patch.object(experiment, "freeze_checkpoint", side_effect=ValueError("manifest changed")):
                with self.assertRaisesRegex(ValueError, "manifest changed"):
                    experiment.require_checkpoint(study)

    def test_gate_each_failure_and_numerical_tie(self):
        base = {"nDCG@5": .4, "Recall@8": .5, "redundancy": .6}
        candidate = {"nDCG@5": .4 + 1e-13, "Recall@8": .49, "redundancy": .55}
        self.assertTrue(experiment.gate({"gas_l6": base, "gas_v3": candidate})["passed"])
        for key, value in (("nDCG@5", .401), ("Recall@8", .48999), ("redundancy", .6)):
            with self.subTest(key=key):
                self.assertFalse(experiment.gate({"gas_l6": base, "gas_v3": {**candidate, key: value}})["passed"])

    def test_aggregate_requires_disjoint_all500_records_and_binds_manifests(self):
        ids = [f"q{i}" for i in range(500)]
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory)
            write_checked(study / "checkpoint_outcome.json", {"passed": True})
            stores = {}
            for stage, queries in (("checkpoint", ids[:100]), ("continuation", ids[100:])):
                path = study / stage
                write_checked(path / "manifest.json", {"query_ids": queries})
                stores[stage] = SimpleNamespace(path=path, fingerprint=stage, get=lambda kind, q: {"qid": q})
            def completed(study, stage):
                return stores[stage], read_checked(stores[stage].path / "manifest.json")
            with patch.object(experiment, "require_checkpoint"), patch.object(experiment, "require_frozen", return_value={"query_ids": ids}), patch.object(experiment, "open_completed", side_effect=completed):
                _, ident, records = experiment.evaluation_inputs(study, "aggregate")
                self.assertEqual(len(records), 500)
                self.assertEqual(len(ident["stage_bindings"]), 2)
                write_checked(study / "continuation/manifest.json", {"query_ids": ids[99:]})
                with self.assertRaisesRegex(ValueError, "Overlapping"):
                    experiment.evaluation_inputs(study, "aggregate")

    def test_query_weighted_means_not_average_of_stage_means(self):
        queries = {str(i): {"metric": float(i < 100)} for i in range(500)}
        self.assertAlmostEqual(experiment.query_means({"method": queries})["method"]["metric"], .2)


class SupervisorTests(unittest.TestCase):
    def invoke(self, passed=True, fail_stage=None):
        handlers = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
        try:
            with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
                study = Path(directory)
                write_checked(study / "frozen.json", {"fixture": True})
                launched = []
                class Child:
                    pid = 123456
                    def __init__(self, command, **kwargs):
                        name = command[4]
                        stage = command[command.index("--stage") + 1] if "--stage" in command else None
                        launched.append((name, stage))
                        self.returncode = 1 if fail_stage == (name, stage) else 0
                        if self.returncode:
                            return
                        if name == "freeze-checkpoint":
                            path = study / "checkpoint_outcome.json"
                        elif name == "encode":
                            path = study / "encoding.json"
                        else:
                            path = study / stage / {"run": "manifest.json", "evaluate": "evaluation.json", "report": "REPORT.md"}[name]
                        write_checked(path, {"passed": passed, "gate": {"passed": passed}})
                    def poll(self):
                        return self.returncode
                with patch.object(supervisor, "require_frozen", return_value={}), patch.object(supervisor.subprocess, "Popen", Child):
                    if fail_stage:
                        with self.assertRaises(RuntimeError):
                            supervisor.supervise(study)
                        self.assertEqual(read_checked(study / "execution.json")["status"], "failed")
                        return launched
                    state = supervisor.supervise(study)
                    self.assertEqual(state, "completed" if passed else "checkpoint_gate_failed")
                    self.assertEqual(read_checked(study / "execution.json")["committed_queries"], 500 if passed else 100)
                    return launched
        finally:
            for signum, handler in handlers.items():
                signal.signal(signum, handler)

    def test_failed_gate_never_launches_continuation(self):
        launched = self.invoke(False)
        self.assertNotIn(("run", "continuation"), launched)
        self.assertEqual(launched[-1], ("freeze-checkpoint", None))

    def test_passed_gate_runs_remaining400_then_aggregate(self):
        launched = self.invoke(True)
        self.assertIn(("run", "continuation"), launched)
        self.assertEqual(launched[-1], ("report", "aggregate"))

    def test_execution_failure_stops_before_gate_and_remaining400(self):
        launched = self.invoke(fail_stage=("run", "checkpoint"))
        self.assertEqual(launched, [("encode", None), ("run", "checkpoint")])

class AdditionalRecoveryTests(unittest.TestCase):
    def test_frozen_outcome_binds_all_artifacts_and_rejects_replacement(self):
        result = {"query_count": 100, "gate": {"passed": True}}
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory)
            for relative in ("frozen.json", "checkpoint/manifest.json", "checkpoint/evaluation.json"):
                write_checked(study / relative, {"fixture": relative})
            identity = {"sampling_sha256": "sample", "sampling": {"continuation": [str(i) for i in range(400)]}}
            with patch.object(experiment, "checked_evaluation", return_value=result), patch.object(experiment, "require_frozen", return_value=identity):
                path = experiment.freeze_checkpoint(study)
                self.assertTrue(read_checked(path)["passed"])
                self.assertEqual(read_checked(path)["evaluation_sha256"], sha(study / "checkpoint/evaluation.json"))
                before = sha(path)
                experiment.freeze_checkpoint(study)
                self.assertEqual(sha(path), before)
                write_checked(study / "checkpoint/evaluation.json", {"changed": True})
                with self.assertRaisesRegex(ValueError, "outcome changed"):
                    experiment.freeze_checkpoint(study)

    def test_corrupt_heartbeat_terminates_active_worker(self):
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
                self.assertEqual(len(children), 1)
                self.assertTrue(children[0].terminated)
                self.assertEqual(read_checked(study / "execution.json")["status"], "failed")
        finally:
            for signum, handler in handlers.items():
                signal.signal(signum, handler)

    def test_resume_skips_encoding_and_preserves_completed_stage(self):
        handlers = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
        try:
            with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
                study = Path(directory)
                write_checked(study / "frozen.json", {"fixture": True})
                launched, fail = [], [True]
                class Child:
                    pid = 123456
                    def __init__(self, command, **kwargs):
                        name = command[4]
                        stage = command[command.index("--stage") + 1] if "--stage" in command else None
                        launched.append((name, stage))
                        self.returncode = int(fail[0] and name == "run")
                        if not self.returncode:
                            path = study / ("encoding.json" if name == "encode" else "checkpoint_outcome.json" if name == "freeze-checkpoint" else f"{stage}/" + {"run": "manifest.json", "evaluate": "evaluation.json", "report": "REPORT.md"}[name])
                            write_checked(path, {"passed": True, "gate": {"passed": True}})
                    def poll(self):
                        return self.returncode
                with patch.object(supervisor, "require_frozen", return_value={}), patch.object(supervisor.subprocess, "Popen", Child):
                    with self.assertRaises(RuntimeError):
                        supervisor.supervise(study)
                    before = sha(study / "encoding.json")
                    fail[0] = False
                    supervisor.supervise(study, resume=True)
                    self.assertEqual(launched.count(("encode", None)), 1)
                    self.assertEqual(sha(study / "encoding.json"), before)
                    state = read_checked(study / "execution.json")
                    self.assertEqual([s["status"] for s in state["sessions"]], ["failed", "completed"])
        finally:
            for signum, handler in handlers.items():
                signal.signal(signum, handler)

    def test_retrieval_matches_frozen_pipeline_when_no_self_id_exists(self):
        corpus, queries, _, _, _ = datasets.synthetic_splits()
        old = frozen_pipeline.Runtime(corpus, full_controls=True, synthetic=True)
        new = SyntheticRuntime(corpus)
        query = next(iter(queries.values()))
        a, b = old.retrieve(query), new.retrieve(query, "nonexistent-query-id")
        self.assertEqual(a["full"], b["full"])
        self.assertEqual(a["lexical"], b["lexical"])
        self.assertEqual(b["self_excluded"], 0)
