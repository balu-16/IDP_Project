"""Artificial fault injection and CPU-profile isolation; no dataset rankings."""
from dataclasses import asdict
import contextlib
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import torch

# Match the fresh-process CLI setup before running numerical isolation checks.
if torch.get_num_interop_threads() != 1:
    torch.set_num_interop_threads(1)

from research import datasets
from research.accuracy_v2.encoding import encode_sharded
from research.accuracy_v2.storage import read_checked, sha, write_checked
from research.accuracy_v3 import pipeline as kernels
from research.accuracy_v3.core import Config
from research.accuracy_v3.experiment import synthetic_base
from research.fourth_dataset_v1 import protocol as parent, test_fourth
from . import benchmark, pipeline, protocol, supervisor


class ProfileTests(unittest.TestCase):
    def test_speed_selection_threshold_and_fewer_thread_ties(self):
        def choose(a, b, c):
            return benchmark.choose({t: {"median_rows_per_second": v} for t, v in zip((2, 4, 6), (a, b, c))})["threads"]
        self.assertEqual(choose(50, 54, 54.9), 2)
        self.assertEqual(choose(50, 55, 50), 4)
        self.assertEqual(choose(50, 60, 62), 4)
        self.assertEqual(choose(50, 60, 80), 6)
        self.assertEqual(choose(50, 30, 40), 2)

    def test_effective_encoding_threads_override_inherited_reset(self):
        import torch
        calls = []
        class Model:
            max_seq_length = 256
            def encode(self, texts, **kwargs):
                calls.append((torch.get_num_threads(), kwargs))
                return np.ones((len(texts), 384))
        original = torch.get_num_threads()
        try:
            torch.set_num_threads(2)
            wrapped = pipeline.ThreadCheckedModel(Model(), 4)
            wrapped.encode(["text"], batch_size=8)
            self.assertEqual(calls, [(4, {"batch_size": 8})])
            self.assertEqual(wrapped.max_seq_length, 256)
        finally:
            torch.set_num_threads(original)

    def test_online_runtime_forces_two_threads_before_models_and_warmup(self):
        import torch
        calls = []
        class Vectors:
            def query_vec(self, query):
                calls.append(torch.get_num_threads())
        class Scorer:
            def scores(self, query, features):
                calls.append(torch.get_num_threads())
        original = torch.get_num_threads()
        try:
            torch.set_num_threads(4)
            with patch.object(pipeline, "CachedDenseSpace", return_value=Vectors()), patch.object(pipeline.v2, "Scorer", return_value=Scorer()), patch.object(pipeline, "FeatureBuilder"), patch.object(pipeline.baselines, "BM25"):
                pipeline.Runtime({"d": "text"})
            self.assertEqual(calls, [2, 2, 2])
            self.assertIs(pipeline.Runtime.retrieve, kernels.Runtime.retrieve)
            self.assertIs(pipeline.Runtime.expand, kernels.Runtime.expand)
            self.assertEqual(torch.get_num_threads(), 2)
        finally:
            torch.set_num_threads(original)

    def test_cpu_source_change_rejected_before_resume(self):
        with patch.object(parent, "require_frozen", return_value={"cpu_sources": {}}):
            with self.assertRaisesRegex(ValueError, "CPU adapter source fingerprint"):
                protocol.require_frozen(Path("unused"))


class ShardTests(unittest.TestCase):
    def model(self, calls):
        class Model:
            def encode(self, texts, **kwargs):
                calls.extend(texts)
                return np.array([[float(t) + 1] * 384 for t in texts])
        return Model()

    def test_imported_prefix_survives_interruption_without_repeat_work(self):
        calls, texts = [], list(map(str, range(1536)))
        space = SimpleNamespace(model=self.model(calls))
        with tempfile.TemporaryDirectory() as directory, patch("research.accuracy_v2.encoding.legacy_key", return_value="key"), contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            def interrupt_first(event, begin):
                if event == "after_embedding_commit":
                    raise InterruptedError("stop after one committed shard")
            with self.assertRaises(InterruptedError):
                encode_sharded(space, texts, root, hook=interrupt_first)
            shard = root / "key.shards"
            _, imported = protocol.verify_shards(shard, 512)
            prefix_hash = sha(shard / "000000000.npy")
            def interrupt_second(event, begin):
                if event == "after_embedding_commit" and begin == 512:
                    raise InterruptedError("stop accelerated worker after another commit")
            with self.assertRaises(InterruptedError):
                encode_sharded(space, texts, root, hook=interrupt_second)
            encode_sharded(space, texts, root)
            self.assertEqual(calls, texts)
            self.assertEqual(sha(shard / "000000000.npy"), prefix_hash)
            progress = pipeline.progress_record(shard, 512, 4, 1536, "protocol")
            self.assertEqual(progress["completed_chunk_rows"], 1536)
            self.assertEqual(progress["new_profile_rows"], 1024)
            self.assertEqual([r["threads"] for r in progress["profiles"]], [2, 4, 4])
            self.assertEqual(progress["profiles"][0]["commit_sha256"], imported[0]["commit_sha256"])
            (shard / "000000512.json").write_text("corrupt")
            with self.assertRaisesRegex(ValueError, "Corrupt checkpoint"):
                pipeline.progress_record(shard, 512, 4, 1536, "protocol")

    def test_prepare_copies_committed_arrays_and_does_not_modify_parent(self):
        calls, texts = [], list(map(str, range(1024)))
        space = SimpleNamespace(model=self.model(calls))
        with tempfile.TemporaryDirectory() as directory, patch("research.accuracy_v2.encoding.legacy_key", return_value="key"), contextlib.redirect_stdout(io.StringIO()):
            root = Path(directory)
            old, cache, newcache = root / "parent", root / "oldcache", root / "newcache"
            old.mkdir()
            def stop(event, begin):
                if event == "after_embedding_commit":
                    raise InterruptedError()
            with self.assertRaises(InterruptedError):
                encode_sharded(space, texts, cache, hook=stop)
            _, records = protocol.verify_shards(cache / "key.shards", 512)
            write_checked(old / "stop_for_cpu_profile.json", {"both_stopped": True, "cache_key": "key", "committed_rows": 512,
                "shards": [{k: r[k] for k in ("begin", "end", "commit_sha256", "array_sha256")} for r in records]})
            write_checked(old / "execution.json", {"status": "interrupted", "committed_queries": 0})
            for name in ("frozen.json", "preflight.json", "smoke.json", "smoke_tests.log", "dataset_inventory.json"):
                write_checked(old / name, {"fixture": True})
            with patch.object(protocol, "ROOT", root), patch.object(protocol, "PARENT", old), patch.object(protocol, "CACHE", newcache), patch.object(parent, "CACHE", cache), patch.object(parent, "require_frozen", return_value={}):
                study = root / "newstudy"
                protocol.prepare(study)
                self.assertEqual(read_checked(study / "imported_shards.json")["rows"], 512)
                original = cache / "key.shards/000000000.npy"
                copied = newcache / "key.shards/000000000.npy"
                self.assertEqual(sha(original), sha(copied))
                saved = sha(original)
                copied.write_bytes(b"corrupt")
                self.assertEqual(sha(original), saved)
                with self.assertRaisesRegex(ValueError, "changed"):
                    protocol.prepare(study)

    def test_collection_resume_keeps_results_timings_and_cpu_snapshots(self):
        corpus, all_queries, _, _, _ = datasets.synthetic_splits()
        queries = {q: all_queries[q] for q in sorted(all_queries)[:2]}
        identity = {**parent.code_identity(), "cpu_sources": protocol.sources(), "methods": kernels.expected_methods(),
                    "base_frozen": synthetic_base(), "config": asdict(Config()), "query_ids": sorted(queries)}
        from research.fourth_dataset_v1.experiment import collect_into
        from research.accuracy_v3.pipeline import Runtime
        factory = lambda c: Runtime(c, full_controls=True, synthetic=True)
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            store = protocol.Store(directory, identity)
            def interrupt(event, stage, qid):
                if event == "after_commit" and stage == "queries":
                    raise InterruptedError()
            with self.assertRaises(InterruptedError):
                collect_into(store, corpus, queries, factory, interrupt)
            first = sorted(queries)[0]
            saved = sha(store.file("queries", first))
            restored = protocol.Store(directory, identity, resume=True)
            collect_into(restored, corpus, queries, factory)
            restored.verify()
            self.assertEqual(sha(restored.file("queries", first)), saved)
            snapshot = Path(directory) / "source_snapshot/research/fourth_dataset_cpu_v1/pipeline.py"
            snapshot.write_text("corrupt")
            with self.assertRaisesRegex(ValueError, "CPU collection snapshot corrupt"):
                protocol.Store(directory, identity, resume=True)


class SupervisorTests(test_fourth.SupervisorTests):
    """Run existing stop/recovery/gate fault injection against this supervisor."""
    def setUp(self):
        self.patch = patch.object(test_fourth, "supervisor", supervisor)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()


if __name__ == "__main__":
    unittest.main()
