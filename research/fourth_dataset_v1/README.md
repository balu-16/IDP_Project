# TREC-COVID transfer evaluation

This package reuses the frozen v2/v3 selection kernels without changing them.
It evaluates every official BEIR test query using a predeclared transfer profile;
there is no tuning or confirmation split. Existing FiQA failures remain intact.

Use `backend/.venv/bin/python -m research.fourth_dataset_v1 COMMAND` from the
repository root. Commands set CPU threads to two and load pinned models offline.

Preparation, in order:

```bash
backend/.venv/bin/python -m research.fourth_dataset_v1 download
backend/.venv/bin/python -m research.fourth_dataset_v1 preflight
backend/.venv/bin/python -m research.fourth_dataset_v1 smoke
backend/.venv/bin/python -m research.fourth_dataset_v1 freeze
backend/.venv/bin/python -m research.fourth_dataset_v1 encode --pilot-shards 2
backend/.venv/bin/python -m research.fourth_dataset_v1 launch
```

`launch` detaches a supervisor that completes encoding, collection, evaluation,
and reporting. It stops on technical/integrity errors. Scientific gates are
evaluated only after all 50 queries, and failed outcomes are reported and kept.
Check the PID and committed embedding/query progress before claiming success.

The study is `research/runs/fourth_dataset_v1_trec_covid/`. Monitor
`execution.json` (checksummed wrapper), `supervisor.log`, `logs/encode.log`,
`logs/run.log`, `encoding_progress.json`, and `collection_progress.json`.
Run `... status` for the execution state. Final files are `test/REPORT.md` and
`test/evaluation.json`; all source snapshots and raw checkpoints are retained.

Stop gracefully using the PID in `supervisor.pid`:

```bash
kill -TERM "$(cat research/runs/fourth_dataset_v1_trec_covid/supervisor.pid)"
backend/.venv/bin/python -m research.fourth_dataset_v1 launch --resume
```

Check that the PID still belongs to this supervisor before sending a signal.
Recovery verifies fingerprints, committed shards, completed queries, and stage
artifacts. Do not modify the frozen package, old research sources, model files,
or benchmark dependencies while collecting. Do not delete failed results to
rerun a more favorable configuration. Interrupted uncommitted work is recomputed;
committed timings and results are retained.

Manual stages are available as `encode`, `run [--resume]`, `evaluate`, `report`.
Do not run manual stages concurrently with the supervisor. `freeze` records
configuration, 27 methods, five seeds, all query IDs, corpus IDs, graded qrels,
model hashes, source snapshots and dependencies before model initialization.
Only the separate cache namespace `research/cache/fourth_dataset_v1/trec-covid/`
can receive new embeddings. The pilot saves reusable 512-row encoding shards.

Recall/precision use grade >0; nDCG uses linear graded gains to match existing
experiments and trec_eval. Preserve the snapshot's two grade -1 entries as
explicitly unjudged. Grade-zero documents remain judged nonrelevant;
unjudged documents count as nonrelevant in official metrics. Judged coverage
is reported separately. Paired statistics average seeds inside each query and
treat differences within 1e-12 as ties. Larger classical corpus coverage does
not establish a Grover speedup or quantum corpus-search scaling.

Official snapshot/checksum:
https://github.com/beir-cellar/beir/wiki/Datasets-available

No manuscript integration, application changes, or dependency updates are part
of this experiment.
