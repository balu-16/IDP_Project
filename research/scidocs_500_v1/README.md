# SCIDOCS-500 fixed test-subset evaluation

Standalone, predeclared transfer evaluation against all 25,657 corpus documents.
SCIDOCS has no BEIR dev split. Freeze 500 IDs using the existing ID-only helper
and namespace `scidocs-500-transfer-v1`. The first 100 are a **test stopping
checkpoint**, not a development or confirmation sample. Never tune or replace
queries based on results.

Use `backend/.venv/bin/python -m research.scidocs_500_v1 COMMAND` from the repo:

1. `download` — official BEIR archive; published MD5 and SHA-256 inventory.
2. `preflight` — full token/reference/model/storage checks, without rankings.
3. `smoke` — artificial integration, recovery, gate, selector and inference checks.
4. `freeze` — immutable ordered IDs, configuration, source/model/data identities.
5. `encode --pilot-shards 2` — reusable 1,024-row encoding pilot and ETA.
6. `launch` — detached supervisor: finish encoding; checkpoint100 collection,
   independent evaluation, report, frozen outcome; continue400 **only on PASS**;
   merge all 500 query records, independently evaluate and report.
7. `status` — read-only progress/PIDs. No continuous assistant monitoring required.

Default study: `research/runs/scidocs_500_v1/`.
Cache: `research/cache/scidocs_500_v1/scidocs/`.
Every stage remains two CPU threads / one inter-op thread, encoding batch eight.
No dependency changes. Earlier TREC-COVID work stays paused.

## Stop and recover

Send SIGTERM to the PID in `supervisor.pid`. Its worker is stopped and all
committed embedding shards, features, complete query results, timings and session
logs survive. Resume using `launch --resume`. Incompatible identities or corrupt
checkpoints raise explicit errors; do not delete evidence to bypass checks.
A failed scientific checkpoint is terminal: `--resume` never authorizes retuning
or collecting the remaining 400. No automatic restart is scheduled after errors.

Manual stages (do not run concurrently with the supervisor):

```
encode
run --stage checkpoint [--resume]
evaluate --stage checkpoint
report --stage checkpoint
freeze-checkpoint
run --stage continuation [--resume]
evaluate --stage continuation
report --stage continuation
evaluate --stage aggregate
report --stage aggregate
```

Continuation is independently blocked by the manual `run` command unless the
sealed 100-query outcome passed all checks: nDCG@5 unchanged within 1e-12,
Recall@8 retention ≥98%, strictly lower redundancy (numerical ties within1e-12).
Final means are recomputed over500 individual query records; seeds averaged
within each query; deterministic controls once/query. Stage means are not averaged
equally. A final scientific failure is retained without tuning.

Monitoring: `execution.json`, `supervisor.log`, `logs/*.log`,
`encoding_progress.json`, `checkpoint_progress.json`, `continuation_progress.json`.
Reports: `checkpoint/REPORT.md` (explicit100-query partial),
`continuation/REPORT.md` (stage diagnostic), `aggregate/REPORT.md` (final500).
Evaluation JSON preserves all 27 methods, timings, work, statuses, paired CIs,
Holm decisions and individual recall losses. Raw qrels and all corpus/query IDs
are retained in `dataset_inventory.json`. `selected_queries.json` freezes order.

## Interpretation

Exclude identical query/document IDs before dense top64 for every method;
keep original judgments. BM25 corpus statistics use the full corpus. Retrieve
representative chunks exactly as before; preserve original L6 logits in the
expanded union. Loading, encoding and warm-up are outside online latency.
Actual Grover phase marking/amplification use the unchanged v2/v3 kernels.
No speed/cost/quantum superiority claim is implied by this classical simulation.

The [dense model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
lists S2ORC/SPECTER training. Exact training/test disjointness is unverified;
neither confirmed leakage nor clean zero-shot evaluation is asserted.
Early stopping uses test judgments: inferential findings remain exploratory and
conditional on that rule. No manuscript integration is automatic.
