"""Research pipeline regression tests (fixtures only, not benchmarks)."""
import json
import unittest

import numpy as np

from research import artifacts, baselines, datasets, metrics
from research.config_frozen import FROZEN
from research.resources import cosine_to_unit, run_grid


class PipelineTests(unittest.TestCase):
    def test_chunk_aggregation_uses_max_and_dedups(self):
        agg = datasets.aggregate_chunks_to_parents({"D1::a": 0.2, "D1::b": 0.9, "D2": 0.5})
        self.assertEqual(agg, {"D1": 0.9, "D2": 0.5})

    def test_frozen_config_matches_paper(self):
        self.assertEqual((FROZEN["candidate_budget"], FROZEN["shots"], FROZEN["boost"]), (64, 1024, 2.0))
        self.assertEqual(FROZEN["seeds"], [0, 1, 2, 3, 4])

    def test_metrics_known_values(self):
        ranked = ["a", "b", "c"]
        rel = {"a": 1, "c": 1}
        self.assertAlmostEqual(metrics.precision_at(ranked, rel, 2), 0.5)
        self.assertAlmostEqual(metrics.recall_at(ranked, rel, 2), 0.5)
        self.assertAlmostEqual(metrics.mrr_at(ranked, rel, 2), 1.0)
        self.assertGreater(metrics.ndcg_at(ranked, rel, 3), 0.5)

    def test_matched_candidates_share_ids(self):
        corpus, queries, _ = datasets.synthetic_fixture()
        vecs = baselines.TfidfVectors(corpus)
        scores = baselines.exact_cosine_scores(vecs, queries["Q0"])
        cands = baselines.top_candidates(scores, 16)
        ranked, trace = baselines.rerank_frozen(cands, scores, "analytical", 0.3, 1024, 2.0, [0, 1])
        self.assertEqual(sorted(ranked), sorted(cands))
        self.assertTrue(trace["frozen_match"])

    def test_resource_grid_reports_supported(self):
        rows = run_grid([-0.8 + 0.1 * i for i in range(16)], threshold_cosine=0.5)
        self.assertTrue(any(r.get("supported") for r in rows))
        self.assertTrue(all("candidates" in r for r in rows))

    def test_resource_grid_separates_zero_iteration_search_from_oracle(self):
        # All four candidates are marked, so the search needs zero iterations.
        # The score oracle is still constructed and must be reported separately.
        rows = run_grid([0.9] * 16, threshold_cosine=0.5)
        row = [r for r in rows if r["candidates"] == 4 and r["score_bits"] == 6][0]
        self.assertTrue(row["supported"])
        self.assertGreater(row["oracle_depth"], 0)
        self.assertIn("oracle_one_q", row)
        self.assertIn("oracle_two_q", row)

    def test_global_mapping_preserves_predicate(self):
        # [0.6,0.7,0.8,0.9] cosine @0.5 -> unit [0.8,0.85,0.9,0.95] vs 0.75: all mark.
        self.assertEqual(cosine_to_unit([0.6, 0.7, 0.8, 0.9]),
                         [0.8, 0.85, 0.9, 0.95])
        rows = run_grid([0.6, 0.7, 0.8, 0.9], threshold_cosine=0.5)
        four = [r for r in rows if r["candidates"] == 4 and r["score_bits"] == 6][0]
        self.assertTrue(four["supported"])
        self.assertEqual(sorted(four["marked_indices"]), [0, 1, 2, 3])
        self.assertIn("qasm_sha256", four)
        self.assertEqual(four["threshold_cosine"], 0.5)
        self.assertAlmostEqual(four["threshold_unit"], 0.75)

    def test_threshold_moves_with_scores(self):
        # Audit case: [0.1,0.2,0.3,0.9] cosine @0.5 -> unit threshold 0.75, only 0.9 marks.
        from research.resources import cosine_threshold_to_unit

        self.assertAlmostEqual(cosine_threshold_to_unit(0.5), 0.75)
        rows = run_grid([0.1, 0.2, 0.3, 0.9], threshold_cosine=0.5)
        four = [r for r in rows if r["candidates"] == 4 and r["score_bits"] == 6][0]
        self.assertTrue(four["supported"])
        self.assertEqual(four["marked_indices"], [3])

    def test_qrels_filtering_and_scifact_sample(self):
        queries = {"Q0": "a", "Q1": "b", "Q2": "c"}
        qrels = {"Q0": {"D0": 1}, "Q2": {"D1": 1}}
        fq, fr = datasets._filter_to_qrels(queries, qrels)
        self.assertEqual(set(fq), {"Q0", "Q2"})
        tq, tr = datasets.scifact_train_sample(
            {f"Q{i}": "t" for i in range(10)}, {f"Q{i}": {"D0": 1} for i in range(10)})
        self.assertEqual(len(tq), 2)

    def test_normalization_is_deterministic(self):
        self.assertEqual(datasets.normalize_text("  A\u00a0  B\nC  "), "A B C")
        self.assertEqual(datasets.normalize_text("\uff21"), "A")

    def test_query_subset_is_stable_and_not_input_order(self):
        ids = ["q3", "q1", "q2", "q4"]
        first = datasets.deterministic_query_subset(ids, "scifact", 2)
        second = datasets.deterministic_query_subset(list(reversed(ids)), "scifact", 2)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)
        self.assertTrue(set(first).issubset(set(ids)))

    def test_official_requires_dense(self):
        with self.assertRaises(ValueError):
            baselines.build_vector_space({"D0": "hi"}, prefer="tfidf", dataset="scifact")
        with self.assertRaises(ValueError):
            baselines.build_vector_space({"D0": "hi"}, prefer="tfidf", dataset="nfcorpus")

    def test_chunk_words_policy(self):
        words = [f"w{i}" for i in range(400)]
        chunks = baselines.chunk_words(words, 192, 32)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= 192 for c in chunks))

    def test_timings_are_per_method(self):
        import inspect

        from research import run as _run

        src = inspect.getsource(_run.cmd_run)
        self.assertIn('"rerank"', src)
        self.assertNotIn("**sel_timings", src)

    def test_coverage_validation_rejects_gaps(self):
        manifest = {"test_ids": ["Q0", "Q1"], "methods": ["exact_cosine", "grover"]}
        rankings = {"exact_cosine": {"Q0": ["D0"], "Q1": ["D0"]}, "grover": {"Q0": ["D0"]}}
        traces = {"Q0": {"exact_cosine": {}, "grover": {"per_seed_rankings": {0: ["D0"]}}},
                  "Q1": {"exact_cosine": {}, "grover": {"per_seed_rankings": {0: ["D0"]}}}}
        with self.assertRaises(ValueError):
            artifacts.validate_coverage(manifest, rankings, traces)

    def test_beir_loader_reads_official_format(self):
        import tempfile

        from research.datasets import DATA_ROOT, load_beir

        with tempfile.TemporaryDirectory() as tmp:
            base = DATA_ROOT / "_test_official"
            try:
                (base / "qrels").mkdir(parents=True, exist_ok=True)
                with open(base / "corpus.jsonl", "w") as f:
                    f.write(json.dumps({"_id": "D0", "title": "T", "text": "hello world"}) + "\n")
                with open(base / "queries.jsonl", "w") as f:
                    f.write(json.dumps({"_id": "Q0", "text": "hello"}) + "\n")
                with open(base / "qrels" / "test.tsv", "w") as f:
                    f.write("query-id\tcorpus-id\tscore\nQ0\tD0\t1\n")
                corpus, queries, qrels = load_beir("_test_official")
                self.assertEqual(corpus, {"D0": "T hello world"})
                self.assertEqual(queries, {"Q0": "hello"})
                self.assertEqual(qrels, {"Q0": {"D0": 1}})
            finally:
                import shutil

                shutil.rmtree(base, ignore_errors=True)

    def test_synthetic_splits_keep_test_disjoint(self):
        corpus, dev_q, dev_qrels, test_q, test_qrels = datasets.synthetic_splits()
        self.assertTrue(set(dev_q).isdisjoint(test_q))
        self.assertEqual(len(test_q), 8)
        # Every test query preserved with judgments.
        for qid in test_q:
            self.assertIn(qid, test_qrels)

    def test_holm_stops_on_first_failure(self):
        # Issue 7: 0.03,0.04,0.045 with m=3 -> levels .0167,.025,.05; first fails -> none significant.
        out = metrics.holm({"a": 0.03, "b": 0.04, "c": 0.045})
        self.assertFalse(any(v["significant"] for v in out.values()))

    def test_recall64_needs_full_ranking(self):
        # Issue 5: relevant at rank 21 scores Recall@64=1 only with full list.
        ranked = [f"D{i}" for i in range(64)]
        rel = {"D20": 1}
        self.assertEqual(metrics.recall_at(ranked, rel, 64), 1.0)
        self.assertEqual(metrics.recall_at(ranked[:10], rel, 64), 0.0)

    def test_per_seed_rankings_saved_not_ensemble(self):
        corpus, queries, _ = datasets.synthetic_fixture()
        vecs = baselines.TfidfVectors(corpus)
        scores = baselines.exact_cosine_scores(vecs, queries["Q0"])
        cands = baselines.top_candidates(scores, 16)
        _, trace = baselines.rerank_frozen(cands, scores, "sampling", 0.0, 128, 2.0, [0, 1, 2])
        self.assertEqual(set(trace["per_seed_rankings"]), {0, 1, 2})
        for rank in trace["per_seed_rankings"].values():
            self.assertEqual(sorted(rank), sorted(cands))

    def test_provenance_is_honest_about_standin(self):
        vecs, meta = baselines.build_vector_space({"D0": "hello world"}, prefer="tfidf",
                                                  dataset="synthetic")
        self.assertEqual(meta["embedding_space"], "tfidf-standin")
        self.assertIsNotNone(meta["fallback"])

    def test_hnsw_queries_topk_from_prebuilt_index(self):
        corpus, queries, _ = datasets.synthetic_fixture()
        vecs = baselines.TfidfVectors(corpus)
        index = baselines.HNSWIndex(vecs)
        scores, qmeta = index.query(queries["Q0"], k=16)
        self.assertEqual(len(scores), 16)
        self.assertGreaterEqual(index.build_ms, 0.0)
        self.assertIn("query_ms", qmeta)

    def test_manifest_verification_rejects_edits(self):
        run_dir = artifacts.new_run_dir("_verify_test")
        try:
            artifacts.write_manifest(run_dir, {"freeze": {"synthetic": True}})
            artifacts.verify_manifest(run_dir)  # passes
            with open(run_dir / "manifest.json", "a") as f:
                f.write(" ")
            with self.assertRaises(ValueError):
                artifacts.verify_manifest(run_dir)
        finally:
            import shutil

            shutil.rmtree(run_dir, ignore_errors=True)

    def test_dense_hnsw_indexes_chunks_to_parents(self):
        class FakeDense:
            is_chunked = True
            doc_ids = ["P0", "P1"]
            chunk_parents = ["P0", "P0", "P1"]
            chunk_matrix = np.eye(3)

            def query_vec(self, query):
                v = np.zeros(3)
                v[0] = 1.0
                return v

        index = baselines.HNSWIndex(FakeDense(), ef_construction=10)
        scores, qmeta = index.query("q", k=2)
        self.assertEqual(set(scores), {"P0", "P1"})
        self.assertTrue(qmeta["chunked"])
        self.assertGreaterEqual(qmeta["chunks_fetched"], 2)

    def test_fallback_saves_labeled_per_seed_rankings(self):
        corpus, queries, _ = datasets.synthetic_fixture()
        vecs = baselines.TfidfVectors(corpus)
        scores = {d: -0.9 for d in list(corpus)[:8]}
        cands = list(scores)
        ranked, trace = baselines.rerank_frozen(cands, scores, "sampling", 0.5, 128, 2.0, [0, 1])
        self.assertEqual(trace["fallback"], "no_marked_items")
        self.assertEqual(set(trace["per_seed_rankings"]), {0, 1})
        for rank in trace["per_seed_rankings"].values():
            self.assertEqual(rank, ranked)

    def test_per_seed_trec_separates_methods(self):
        traces = {"Q0": {"grover": {"per_seed_rankings": {0: ["D0", "D1"]}},
                         "sampling": {"per_seed_rankings": {0: ["D1", "D0"]}}}}
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            from pathlib import Path as _P

            artifacts.write_per_seed_trec(traces, _P(tmp))
            grover = (_P(tmp) / "grover.seed0.trec").read_text()
            sampling = (_P(tmp) / "sampling.seed0.trec").read_text()
            self.assertIn("grover.seed0", grover)
            self.assertNotIn("sampling", grover)
            self.assertIn("sampling.seed0", sampling)
            self.assertFalse((_P(tmp) / "seeds0.trec").exists())

    def test_dev_requires_judgments(self):
        import tempfile

        from research.datasets import DATA_ROOT

        base = DATA_ROOT / "scifact"
        # Only run when real cache absent; otherwise the real loader enforces counts.
        if base.exists():
            self.skipTest("real BEIR cache present")
        with self.assertRaises((FileNotFoundError, ValueError)):
            datasets.load_splits("scifact")

    def test_report_rejects_unsealed_scores(self):
        import json as _json

        run_dir = artifacts.new_run_dir("_unsealed_test")
        try:
            artifacts.write_manifest(run_dir, {"freeze": {"synthetic": True},
                                               "test_ids": [], "methods": []})
            (run_dir / "rankings.json").write_text("{}")
            (run_dir / "traces.jsonl").write_text("")
            (run_dir / "scores.json").write_text(_json.dumps({"means": {}}))
            from research import run as _run

            with self.assertRaises(ValueError):
                _run.cmd_report(type("A", (), {"run": str(run_dir)})())
        finally:
            import shutil

            shutil.rmtree(run_dir, ignore_errors=True)

    def test_hnsw_progressive_fetch_finds_minority_parent(self):
        # One doc owns the 12 nearest chunks; K=2 must still find 2 parents.
        rng = np.random.default_rng(0)
        n_major, dim = 12, 8
        major = np.tile(np.eye(dim)[0], (n_major, 1)) + rng.normal(0, 1e-4, (n_major, dim))
        minor = np.eye(dim)[1:3] + rng.normal(0, 1e-4, (2, dim))
        mat = np.vstack([major, minor])
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        mat = mat / norms

        class FakeDense2:
            is_chunked = True
            doc_ids = ["MAJOR", "MINOR"]
            chunk_parents = ["MAJOR"] * n_major + ["MINOR", "MINOR"]
            chunk_matrix = mat

            def query_vec(self, query):
                v = np.zeros(dim)
                v[0] = 1.0
                return v / np.linalg.norm(v)

        index = baselines.HNSWIndex(FakeDense2(), ef_construction=10)
        scores, qmeta = index.query("q", k=2)
        self.assertEqual(set(scores), {"MAJOR", "MINOR"})
        self.assertGreaterEqual(qmeta["fetch_rounds"], 1)


if __name__ == "__main__":
    unittest.main()
