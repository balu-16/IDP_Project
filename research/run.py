"""Headless retrieval experiment: `run`, `evaluate`, `report` (plan A.2-A.5).

Offline after data caching. No UI, prod DB, or Gemini required.
Tables are generated from artifacts only.

  python -m research.run run --dataset synthetic --tag smoke
  python -m research.run evaluate --run runs/<dir>
  python -m research.run report --run runs/<dir>
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from . import artifacts, baselines, datasets, metrics
from .config_frozen import FROZEN

METHODS = ["bm25", "exact_cosine", "hnsw", "grover", "analytical", "sampling"]
STORE_K = 64  # persist >=64 for Recall@64 (issue 5); cutoffs applied at eval.


def load_dataset(name: str):
    key = name.strip().lower()
    if key == "synthetic":
        corpus, dev_q, dev_qrels, test_q, test_qrels = datasets.synthetic_splits()
        freeze = {"dataset": "synthetic", "available": True, "synthetic": True}
        return corpus, dev_q, dev_qrels, test_q, test_qrels, freeze
    canonical = datasets.canonical_dataset(key)
    corpus, dev_q, dev_qrels, test_q, test_qrels = datasets.load_splits(canonical)
    return corpus, dev_q, dev_qrels, test_q, test_qrels, datasets.freeze_record(canonical)


def retrieve_full(query_text, method, vecs, bm25, hnsw_index, k):
    """Full-pipeline retrieval returning (ranked_ids_64, raw_scores, timings).

    Each method selects its own candidates; HNSW uses the prebuilt index
    (built once per run) and queries top-K. Timings record actual stages.
    """
    t0 = time.perf_counter()
    if method == "bm25":
        scores = bm25.scores(query_text)
        ranked = baselines.top_candidates(scores, k)
        timings = {"candidate_selection": (time.perf_counter() - t0) * 1000}
    elif method == "exact_cosine":
        scores = baselines.exact_cosine_scores(vecs, query_text)
        ranked = baselines.top_candidates(scores, k)
        timings = {"candidate_selection": (time.perf_counter() - t0) * 1000}
    elif method == "hnsw":
        scores, qmeta = hnsw_index.query(query_text, k=k)
        ranked = baselines.top_candidates(scores, k)
        timings = {"candidate_selection": qmeta["query_ms"], "index": hnsw_index.settings}
    else:
        scores = baselines.exact_cosine_scores(vecs, query_text)
        ranked = baselines.top_candidates(scores, k)
        timings = {"candidate_selection": (time.perf_counter() - t0) * 1000}
    return ranked, scores, timings


def cmd_run(args) -> Path:
    corpus, dev_q, dev_qrels, test_q, test_qrels, freeze = load_dataset(args.dataset)
    # Hard-require dense for official datasets (no TF-IDF fallback).
    vecs, vec_meta = baselines.build_vector_space(corpus, prefer=args.encoder, dataset=args.dataset)
    bm25 = baselines.BM25(corpus)
    hnsw_index = baselines.HNSWIndex(vecs)
    provenance = {"embedding_space": vec_meta["embedding_space"],
                  "dimension": vec_meta["dimension"],
                  "chunk_policy": vec_meta["chunk_policy"],
                  "chunk_statistics": {
                      key: vec_meta[key] for key in
                      ("n_chunks", "n_parents", "chunk_min_tokens", "chunk_max_tokens",
                       "chunk_mean_tokens", "truncation_events") if key in vec_meta
                  },
                  "encoder_fallback": vec_meta.get("fallback"),
                  "normalization": "unicode NFKC, whitespace collapse, empty-chunk drop",
                  "schema_version": "research-v1"}

    # Tune single threshold on DEV only using the stochastic sampling control
    # with per-seed metrics averaged within query. The analytical control is
    # threshold-invariant in ordering for nonnegatives, so tuning on it always
    # returns the first tied value. Documented tie rule: prefer 0.5, then 0.3,
    # then 0.7.
    dev_ids = sorted(dev_q)
    test_ids = sorted(test_q)
    if not dev_ids:
        raise ValueError("Development query set empty; refusing to tune without judgments")
    TIE_PREFERENCE = [0.5, 0.3, 0.7]
    dev_mean: dict[float, float] = {}
    for thr in TIE_PREFERENCE:
        per_q: dict[str, float] = {}
        for qid in dev_ids:
            _, scores, _ = retrieve_full(dev_q[qid], "exact_cosine", vecs, bm25, hnsw_index,
                                         FROZEN["candidate_budget"])
            cands = baselines.top_candidates(scores, FROZEN["candidate_budget"])
            _, trace = baselines.rerank_frozen(cands, scores, "sampling", thr,
                                               FROZEN["shots"], FROZEN["boost"], FROZEN["seeds"])
            seed_ranks = trace.get("per_seed_rankings") or {}
            if not seed_ranks:
                raise ValueError(f"missing per-seed dev rankings for {qid} @thr {thr}")
            vals = [metrics.per_query_scores({qid: r}, dev_qrels)[qid]["nDCG@10"]
                    for r in seed_ranks.values()]
            per_q[qid] = sum(vals) / len(vals)
        dev_mean[thr] = sum(per_q.values()) / len(per_q) if per_q else 0.0
    best_thr = max(TIE_PREFERENCE, key=lambda t: (dev_mean[t], -TIE_PREFERENCE.index(t)))
    best_ndcg = dev_mean[best_thr]

    run_dir = artifacts.new_run_dir(args.tag)
    # Store the exact test-query vectors produced by the pinned MiniLM model.
    # This is a compact audit artifact (300/323 x 384 values), not a substitute
    # for recording the model revision and dataset/query hashes.
    query_matrix = np.asarray([vecs.query_vec(test_q[qid]) for qid in test_ids], dtype=np.float32)
    np.savez_compressed(run_dir / "query_embeddings.npz",
                        query_ids=np.asarray(test_ids, dtype=str),
                        embeddings=query_matrix)
    rankings: dict[str, dict[str, list[str]]] = {m: {} for m in METHODS}
    traces: dict[str, dict] = {}
    for qid in test_ids:
        frozen_cands, frozen_scores, sel_timings = retrieve_full(
            test_q[qid], "exact_cosine", vecs, bm25, hnsw_index, FROZEN["candidate_budget"])
        for method in METHODS:
            t0 = time.perf_counter()
            if method in {"bm25", "exact_cosine", "hnsw"}:
                ranked, scores, timings = retrieve_full(test_q[qid], method, vecs, bm25,
                                                        hnsw_index, FROZEN["candidate_budget"])
                trace = {"candidates": ranked, "raw_scores": {d: scores[d] for d in ranked},
                         "frozen_match": ranked == frozen_cands if method == "exact_cosine" else None}
                method_timings = {"total": (time.perf_counter() - t0) * 1000,
                                  "candidate_selection": timings["candidate_selection"],
                                  "rerank": 0.0}
            else:
                ctrl = {"grover": "grover", "analytical": "analytical", "sampling": "sampling"}[method]
                r0 = time.perf_counter()
                ranked, trace = baselines.rerank_frozen(
                    frozen_cands, frozen_scores, ctrl, best_thr,
                    FROZEN["shots"], FROZEN["boost"], FROZEN["seeds"])
                rerank_ms = (time.perf_counter() - r0) * 1000
                trace = {**trace, "candidates": frozen_cands,
                         "raw_scores": {d: float(frozen_scores[d]) for d in frozen_cands},
                         "frozen_match": True}
                # Full-pipeline total MUST include shared candidate selection:
                # total = selection + combined rerank wall time. Per-seed
                # latency reported separately (combined / n_seeds is only an
                # average; per-seed timings vary with sampling).
                selection_ms = float(sel_timings["candidate_selection"])
                n_seeds = len(FROZEN["seeds"]) if method in {"grover", "sampling"} else 1
                method_timings = {"total": selection_ms + rerank_ms,
                                  "candidate_selection": selection_ms,
                                  "rerank": rerank_ms,
                                  "per_seed_latency_ms": rerank_ms / n_seeds,
                                  "combined_seeds_wall_ms": rerank_ms}
            # Persist full STORE_K (issue 5); evaluation applies cutoffs.
            rankings[method][qid] = ranked[:STORE_K]
            traces.setdefault(qid, {})[method] = {
                **trace, "ranked": ranked[:STORE_K],
                "threshold_cosine": best_thr,
                "timings_ms": method_timings,
                "candidate_count": len(frozen_cands),
            }
    # Resource grid on query-derived scores with circuit exports.
    from .resources import run_grid_for_query

    resources = {}
    circuits_dir = run_dir / "circuits"
    resource_ids = (datasets.deterministic_query_subset(
        test_ids, datasets.canonical_dataset(args.dataset), min(5, len(test_ids)))
        if args.dataset != "synthetic" else test_ids[:min(5, len(test_ids))])
    for qid in resource_ids:
        _, scores, _ = retrieve_full(test_q[qid], "exact_cosine", vecs, bm25,
                                     hnsw_index, FROZEN["candidate_budget"])
        rows, prov = run_grid_for_query(scores, threshold_cosine=best_thr,
                                        out_dir=circuits_dir, qid=qid)
        resources[qid] = {"rows": rows, "provenance": prov}
    manifest = {
        "dataset": args.dataset, "canonical_dataset": datasets.canonical_dataset(args.dataset)
        if args.dataset != "synthetic" else "synthetic",
        "freeze": freeze, "config": FROZEN, "provenance": provenance,
        "encoder_preference": args.encoder,
        "hnsw": {**hnsw_index.settings, "build_ms": hnsw_index.build_ms},
        "threshold_tuned_on_dev": best_thr, "dev_nDCG@10": best_ndcg,
        "dev_ids": dev_ids, "test_ids": test_ids,
        "resource_query_ids": resource_ids,
        "query_embedding_artifact": "query_embeddings.npz",
        "n_corpus": len(corpus),
        "n_dev": len(dev_q),
        "n_test": len(test_q),
        "relevant_test_pairs": sum(len(v) for v in test_qrels.values()),
        "unique_relevant_test_docs": len({d for rel in test_qrels.values() for d in rel}),
        "methods": METHODS, "n_test": len(test_ids), "stored_k": STORE_K,
        "note": "Fixture math, not benchmark evidence, unless real BEIR cache with hashes.",
    }
    artifacts.write_manifest(run_dir, manifest)
    for method in METHODS:
        artifacts.write_trec(rankings[method], method, run_dir)
    artifacts.write_traces(traces, run_dir)
    artifacts.write_per_seed_trec(traces, run_dir)
    (run_dir / "rankings.json").write_text(json.dumps(rankings, indent=2))
    (run_dir / "resources.json").write_text(json.dumps(resources, indent=2))
    artifacts.seal_results(run_dir)
    print(f"run: {run_dir} threshold={best_thr} n_test={len(test_ids)} space={provenance['embedding_space']}")
    return run_dir


def _primary_per_query(method: str, qid: str, trace: dict, ensemble_ranking: list[str],
                       qrels: dict) -> dict[str, float]:
    """Primary per-query scores: per-seed metrics averaged (issue 6).

    Deterministic methods: single ranking. Stochastic: mean of per-seed
    metrics within the query; missing seeds raise (ensemble fallback banned).
    """
    from .metrics import per_query_scores

    seeds = trace.get("per_seed_rankings") or {}
    if method in {"grover", "sampling"}:
        if not seeds:
            raise ValueError(f"missing per-seed rankings for {qid}/{method}: refusing ensemble fallback")
        per_seed = {s: per_query_scores({qid: rank}, qrels)[qid] for s, rank in seeds.items()}
        keys = ["nDCG@10", "Recall@10", "Recall@64", "MRR@10", "P@5"]
        avg = {k: float(sum(per_seed[s][k] for s in per_seed) / len(per_seed)) for k in keys}
        ens = per_query_scores({qid: ensemble_ranking}, qrels)[qid]
        avg["ensemble_nDCG@10"] = ens["nDCG@10"]
        return avg
    return per_query_scores({qid: ensemble_ranking}, qrels)[qid]


def cmd_evaluate(args) -> Path:
    run_dir = Path(args.run)
    artifacts.verify_manifest(run_dir)
    rankings = json.loads((run_dir / "rankings.json").read_text())
    manifest = json.loads((run_dir / "manifest.json").read_text())
    traces = {}
    with open(run_dir / "traces.jsonl") as f:
        for line in f:
            row = json.loads(line)
            traces[row["qid"]] = row
    artifacts.validate_coverage(manifest, rankings, traces)
    dataset = manifest["dataset"]
    _, _, _, _, test_qrels, _ = load_dataset(dataset)
    # Restrict to recorded test ids.
    per_method: dict[str, dict[str, dict]] = {m: {} for m in METHODS if m in rankings}
    for method, rk in rankings.items():
        for qid in manifest["test_ids"]:
            if qid not in rk:
                continue
            trace = traces.get(qid, {}).get(method, {})
            per_method[method][qid] = _primary_per_query(method, qid, trace, rk[qid], test_qrels)
    means = {m: metrics.mean_scores({q: {k: v[k] for k in
             ["nDCG@10", "Recall@10", "Recall@64", "MRR@10", "P@5"]} for q, v in pq.items()})
             for m, pq in per_method.items()}
    base = {qid: per_method["exact_cosine"][qid]["nDCG@10"] for qid in per_method["exact_cosine"]}
    comparisons = {}
    p_values = {}
    for method in ("bm25", "hnsw", "grover", "analytical", "sampling"):
        other = {qid: per_method[method][qid]["nDCG@10"] for qid in per_method[method]}
        boot = metrics.paired_bootstrap(base, other)
        rand = metrics.paired_randomization(base, other)
        comparisons[method + "_vs_exact_cosine"] = {**boot, **rand}
        p_values[method + "_vs_exact_cosine"] = rand["p_value"]
    holm = metrics.holm(p_values)
    result = {"means": means, "n_queries": len(manifest["test_ids"]),
              "comparisons": comparisons, "holm": holm,
              "scoring": "per-seed metrics averaged within query; ensemble_nDCG@10 diagnostic only"}
    (run_dir / "scores.json").write_text(json.dumps(result, indent=2))
    artifacts.seal_scores(run_dir)
    print(json.dumps(means, indent=2))
    return run_dir


def cmd_report(args) -> Path:
    run_dir = Path(args.run)
    # Reports must come from verified artifacts, not a lone scores.json.
    manifest = artifacts.verify_manifest(run_dir)
    rankings = json.loads((run_dir / "rankings.json").read_text())
    traces = {}
    with open(run_dir / "traces.jsonl") as f:
        for line in f:
            row = json.loads(line)
            traces[row["qid"]] = row
    artifacts.validate_coverage(manifest, rankings, traces)
    if manifest.get("canonical_dataset", manifest.get("dataset")) in {"scifact", "nfcorpus"}:
        space = (manifest.get("provenance") or {}).get("embedding_space", "")
        if not space.startswith("dense:"):
            raise ValueError(f"official report requires dense provenance (got {space!r})")
    sealed = manifest.get("result_hashes", {}).get("scores.json")
    if not sealed:
        raise ValueError("scores.json not sealed by evaluate; re-run evaluate before report")
    import hashlib as _hl

    actual = _hl.sha256((run_dir / "scores.json").read_bytes()).hexdigest()
    if actual != sealed:
        raise ValueError("scores.json changed since evaluate sealing; re-run evaluate")
    result = json.loads((run_dir / "scores.json").read_text())
    rows = [{"method": m, "means": result["means"][m], "n_queries": result["n_queries"]}
            for m in METHODS if m in result["means"]]
    table = artifacts.comparison_table(rows)
    comp_lines = ["", "## Paired nDCG@10 vs exact_cosine (bootstrap 10k, Holm)",
                  "| comparison | mean_diff | 95% CI | p | dz | holm_sig |",
                  "|---|---|---|---|---|---|"]
    for name, c in result["comparisons"].items():
        sig = result["holm"][name]["significant"]
        comp_lines.append(f"| {name} | {c['mean_diff']:.3f} | [{c['ci_low']:.3f},{c['ci_high']:.3f}] | "
                          f"{c['p_value']:.3f} | {c['effect_dz']:.2f} | {sig} |")
    out = "# Retrieval comparison (generated from artifacts — do not hand-edit)\n\n" + table + "\n".join(comp_lines) + "\n"
    resources_p = run_dir / "resources.json"
    if resources_p.exists():
        from .resources import resource_table

        resources = json.loads(resources_p.read_text())
        out += "\n" + resource_table(resources)
    (run_dir / "REPORT.md").write_text(out)
    print(out)
    return run_dir


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("--dataset", default="synthetic",
                       choices=["synthetic", "scifact", "nfcorpus", "nqcorpus"],
                       help="nfcorpus canonical; nqcorpus deprecated alias")
    p_run.add_argument("--tag", default="smoke")
    p_run.add_argument("--encoder", default="dense", choices=["tfidf", "dense"],
                       help="dense pinned MiniLM (required for official datasets); "
                            "tfidf stand-in allowed only for synthetic smoke")
    p_eval = sub.add_parser("evaluate")
    p_eval.add_argument("--run", required=True)
    p_rep = sub.add_parser("report")
    p_rep.add_argument("--run", required=True)
    args = parser.parse_args()
    if args.cmd == "run":
        cmd_run(args)
    elif args.cmd == "evaluate":
        cmd_evaluate(args)
    else:
        cmd_report(args)


if __name__ == "__main__":
    main()
