# Encoding-only CPU acceleration

This adapter preserves the original TREC-COVID package, frozen experiment,
dependencies, and cache. It imports committed embedding shards into a separate
cache namespace and benchmarks 2/4/6 threads without relevance judgments.
Retrieval, L6/L2 reranking, all selection methods and comparisons remain at two
threads in fresh processes. No manuscript changes are made.

Commands, from the repository root:

```bash
backend/.venv/bin/python -m research.fourth_dataset_cpu_v1 prepare
backend/.venv/bin/python -m research.fourth_dataset_cpu_v1 check
backend/.venv/bin/python -m research.fourth_dataset_cpu_v1 benchmark
backend/.venv/bin/python -m research.fourth_dataset_cpu_v1 freeze
backend/.venv/bin/python -m research.fourth_dataset_cpu_v1 launch
```

Stop and verify the old supervisor/worker before `prepare`. Do not run the old
supervisor again while this new campaign is active. `prepare` only copies
checksummed committed shards, preserving array bytes, scores, timings and the
original two-thread provenance. New encoding restores the selected thread count
after inherited constructors reset it and asserts the count before inference.

The fixed pilot uses 256 deterministic chunks, batch size eight, two warm-up
batches and three repetitions in a separate process per profile. Choose median
throughput, require at least 10% improvement over two threads, and prefer fewer
threads within 5% of the fastest qualifying profile. Otherwise use two threads.
Outputs must agree with the two-thread reference within rtol=1e-5/atol=1e-6 and
remain finite and normalized. This is preparation profiling, not accuracy tuning.

Study: `research/runs/fourth_dataset_cpu_v1_trec_covid/`.
Cache: `research/cache/fourth_dataset_cpu_v1/trec-covid/`.
Monitor `execution.json`, `supervisor.log`, `logs/encode.log`,
`encoding_progress.json`, then `collection_progress.json`. Checkpoint JSON files
use a checksummed `payload` wrapper. `cpu_benchmark.json` records the pilot;
`encoding_profiles.json` eventually records actual mixed-profile encoding work.

Stop gracefully using the current PID from `supervisor.pid` after checking its
process command. Resume with:

```bash
backend/.venv/bin/python -m research.fourth_dataset_cpu_v1 launch --resume
```

Manual `encode`, `run --resume`, `evaluate`, `report`, and `status` commands are
also available. Do not run manual stages alongside the supervisor. Fingerprint
or checkpoint errors stop progression. The unchanged scientific gates are
evaluated after all 50 queries. Failed scientific outcomes are retained.

Small floating-point differences from threading are possible; numerical
agreement is checked, and identical rankings are not assumed. Encoding pilot
throughput does not demonstrate a Grover or online pipeline speedup. Complete
pipeline timings remain two-thread measurements, with loading and encoding
costs separate. Earlier FiQA failures remain preserved.
