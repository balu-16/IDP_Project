"""Frozen primary configuration (plan A.4). Single source of truth for runs."""

FROZEN = {
    "candidate_budget": 64,
    "shots": 1024,
    "boost": 2.0,
    "seeds": [0, 1, 2, 3, 4],
    "top_k": 10,
    "encoder": "sentence-transformers/all-MiniLM-L6-v2",
    "encoder_revision": "1110a243fdf4706b3f48f1d95db1a4f5529b4d41",
    "chunk_tokens": 192,
    "chunk_overlap_tokens": 32,
    "embedding_dimension": 384,
    "cpu_threads": 2,
    "hnsw_random_seed": 0,
    "hnsw_threads": 1,
    "qubit_cap": 18,
}

# Dataset freeze (plan A.2). Checksums filled on first real download;
# test runs refuse to execute if recorded hashes mismatch.
# Canonical BEIR ids: scifact (300 test), nfcorpus (323 test). `nqcorpus`
# is a deprecated alias accepted by the loader/CLI for backwards compat.
DATASETS = {
    "scifact": {
        "test_queries": 300,
        "beir_id": "scifact",
        "dev_split": "train",
        "source_url": "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/scifact.zip",
        "license": "CC BY-SA 4.0 (check BEIR repo for updates)",
        "sha256": None,  # filled by `run --freeze`
    },
    "nfcorpus": {
        "test_queries": 323,
        "beir_id": "nfcorpus",
        "dev_split": "dev",
        "source_url": "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/nfcorpus.zip",
        "license": "CC BY-SA 4.0 (check BEIR repo for updates)",
        "sha256": None,
    },
}

# Prose provenance recorded in every manifest (plan A.5). `embedding_space`
# describes what actually executed; official datasets hard-require the pinned
# dense MiniLM path, while TF-IDF is permitted only for synthetic smoke tests.
# Manifests must never claim MiniLM vectors while TF-IDF executed.
PROVENANCE = {
    "chunk_policy": "192-token windows, 32-token overlap, special tokens counted, no silent truncation",
    "normalization": "unicode NFKC, whitespace collapse, empty-chunk drop",
    "schema_version": "research-v1",
}
