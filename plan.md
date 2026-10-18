# Grover evidence selection: dataset evaluation and paper revision plan

## Current status — 18 October 2026 (Asia/Kolkata)

**FiQA, the queued application checks, and the independent resource study
have finished. No dataset or resource collection remains running.** Older
launch instructions below are historical records; do not restart either batch.

### FiQA full-test outcome

All **648 queries, 27 methods, and five seeds** were collected, sealed,
independently evaluated, and reported. The scientific gate **failed**:

| Check | Matched baseline | Protected refinement | Outcome |
|---|---:|---:|---|
| nDCG@5 | 0.357490 | 0.357490 | Unchanged |
| Recall@8 | 0.434063 | 0.422768 | −2.601978% relative; fails 98% retention |
| Mean redundancy | 0.531244 | 0.487500 | −8.234319% relative |

The failed outcome is preserved without test-set retuning. The manuscript's
headline uses the disclosed earlier FiQA configuration; the new failure is
reported separately. Do not mix the new redundancy with the earlier recall.

- Report: `research/runs/accuracy_v3_redundancy_fiqa_test/REPORT.md`.
- State: `research/runs/accuracy_v3_redundancy_fiqa_full_execution.json`
  (`gate_failed`, all execution stages completed).
- Recovery launcher: `build/accuracy_v3/launch_fiqa_full_test.py`.
  No recovery or new launch is currently needed.

### Application verification completed

Backend regression tests, frontend contract/retry tests, TypeScript, lint,
production build, and local pinned-L6 smoke checks all passed **after FiQA's
timed collection ended**. Two backend skips remain documented in the logs;
no cloud answer-generation or physical-device check is claimed. The first
verification attempt and its corrected test expectation are retained under
`build/application_gas/attempt_1/`.

- State: `build/application_gas/verification.json` (`passed`).
- Logs: `build/application_gas/`; implementation details remain in the
  historical launch record and `backend/README.md`.

### Technical Comment 2.3 resource study completed

The separate package `research/resource_study_v1/` reads saved confirmation
features and scores; it does not retrieve, encode corpora, or tune parameters.
It started after FiQA and all queued application checks finished.

- Froze **32 deterministic queries per dataset**, the six tail-pool sizes,
  four coefficient precisions, five seeds, and source/dependency/input hashes
  before measurement. Every smaller pool retains its recorded baseline tail.
- Compared compact GAS with independent exact-float and exact-quantized
  selection. Saved fresh timing, separately replayed allocation memory,
  process RSS, phase/oracle counts, gaps, and termination reasons.
- **178/178 tasks completed**, including **80 native synthesis cells**.
  Pools 16/20 use clearly labelled synthetic stress cases because the frozen
  real sample has no eligible pools of those sizes. All real-data availability
  counts, including exclusions, are preserved.
- The new native oracle computes cardinality, all three score constraints,
  signed integer improvement, and compute–phase–uncompute. All decision,
  arithmetic, comparator, and flag qubits are counted; signed bounds include
  invalid-cardinality states. Pinned Qiskit/Aer, `u/cx`, optimization level 1,
  and transpiler seed 0 are unchanged.
- Complete-iteration synthesis includes preparation/reflection for at most
  eight decisions. **Six native iterations validated; 42 additional native
  simulation attempts were refused by the memory guard.** Native simulation
  is restricted to at most five decisions. Independent nontrivial two-bit toy
  tests also check marking, reflection, normalization, and clean workspace.
- Each native worker retains the **120-second / 2-GiB** limits. Larger
  complete simulation, hardware connectivity/noise, QPU, energy, and monetary
  measurements remain unperformed. Compact and native timings are separate.
- The eight-task pilot ran before the detached collection, with a conservative
  **6.3–18.9-minute** projection. Final supervisor session: **10:57–11:02 IST**;
  earlier pilot work is separately recorded. No supervisor remains active.

Current records:

- `research/runs/resource_study_v1_final/REPORT.md` and `summary.json`.
- `native_resources.csv`, `resource_table.tex`, `manifest.json`,
  `report_manifest.json`, `protocol.json`, `verification.json`.
- `tasks.json`, `inputs/`, `results/`, `logs/`, `source_snapshot/`.
- `execution.json`, `supervisor.log`, `supervisor.pid`.
- `manuscript_support/records/resource_hardware.json` (host during collection).

The earlier `research/runs/resource_study_v1/` engineering pilot is preserved
separately, including its native memory-estimation refusal. It is not the
completed study or a substitute for its final provenance.

Monitoring and recovery, from the repository root:

```bash
backend/.venv/bin/python -m research.resource_study_v1 status
# Recreate summaries only from verified, completed checkpoints:
backend/.venv/bin/python -m research.resource_study_v1 report
# Only after interruption; preserves committed tasks and validates identity:
backend/.venv/bin/python -m research.resource_study_v1 run --resume --background
```

A foreground run can stop with Ctrl-C. To stop a future detached run, first
validate the PID's `/proc/<pid>/cmdline` identifies this study and directory,
then send SIGTERM. The supervisor retains committed results and logs the
session boundary. Never delete checkpoints or change dependencies to bypass
corruption or incompatible-resume rejection. Existing completed studies need
no restart; changed protocols require a separate namespace.

### Manuscript delivery

The paper now includes a compact measured constrained-oracle table and its
bounded coverage, replacing the analytical-only resource table. The reviewer
response distinguishes completed synthesis from limited native simulation.
The FiQA failure, NFCorpus confirmation exception, follow-up test reuse, and
matched classical results remain explicit. No Grover superiority claim is made.

- Clean upload folder: `new_paper/`; PDF: `new_paper/main.pdf`.
- Portable sources: `manuscript_support/latex_source.zip`.
- Evidence mapping: `manuscript_support/paper_sources.json`.
- Reviewer response: `manuscript_support/reviewer_response.md`.
- Current status/check records: `manuscript_support/REVISION_STATUS.md`
  and `manuscript_support/records/`, including `resource_final_audit.json`
  (98 saved inputs, all 178 tasks, and 3,360 completed compact cells verified).

The complete manuscript remains **eight pages including references**, with
embedded fonts, resolved references, no overfull boxes, a 189-word abstract,
and a single 150-word conclusion. All eight pages were visually inspected;
standalone-folder compilation and archive integrity are checked separately.
The preceding checked source/PDF is preserved in
`manuscript_support/before_resource_revision.zip`. Author/organizer PDF
validation and any submission remain external actions.

## Historical execution records

The following sections preserve previous plans and progress notes. Their
present-tense running/pending statements are historical; current status is
recorded above.

## Historical launch record — 18 October 2026 (Asia/Kolkata)

**FiQA is running in the background. Backend implementation and minimal
frontend wiring are complete; full application verification is deferred until
the FiQA supervisor finishes.** The latest instruction authorizes concurrent
source edits, with model inference, simulator checks, and heavy builds held
until benchmark timing ends. No manuscript updates are included.

### FiQA launch and progress

- Launched at approximately **09:45 IST**, supervisor PID **16656**. Treat this
  PID as a recorded value; use the launcher's process-identity validation for
  monitoring or stopping it, rather than assuming a PID remains current.
- Fresh cache-only preflight passed; the existing successful 100-query
  confirmation was verified and frozen without repeating confirmation.
- Collection targets **648 queries, 27 methods, seeds 0–4**. At **09:55 IST**,
  **110 queries** had been committed. Initial query checksums, 27-method
  coverage, and stochastic seed coverage were checked successfully.
- The frozen FiQA baseline remains lexical weight **0**, diversity penalty
  **0.025**, with the established 15-to-eight baseline and protected-five
  refinement. No benchmark source or dependency versions were changed.
- Initial throughput projects approximately **50–70 more minutes**, including
  post-collection checks, subject to query difficulty and CPU availability.
  This is an updated estimate, not a promised completion time.
- The detached supervisor automatically evaluates all complete results,
  independently checks metrics, generates the report, and records `completed`
  or `gate_failed`. Technical/integrity failures stop the supervisor. Failed
  scientific outcomes remain failed and do not trigger test-set retuning.

Monitor or recover from the repository root:

```bash
backend/.venv/bin/python build/accuracy_v3/launch_fiqa_full_test.py --status
tail -n 20 research/runs/accuracy_v3_redundancy_logs/fiqa_full_run.log
# Only if a graceful stop is requested:
backend/.venv/bin/python build/accuracy_v3/launch_fiqa_full_test.py --stop
# After interruption, with the same sources/configuration:
backend/.venv/bin/python build/accuracy_v3/launch_fiqa_full_test.py --resume
```

State: `research/runs/accuracy_v3_redundancy_fiqa_full_execution.json`.
Supervisor log: `research/runs/accuracy_v3_redundancy_fiqa_full_supervisor.log`.
Final report: `research/runs/accuracy_v3_redundancy_fiqa_test/REPORT.md`.
The launcher, source snapshot, exclusive lock, PID, stage artifacts, and
session boundaries are retained separately from older batch state. Do not
restart the original three-dataset batch or confirmation-only controller.

### Application changes implemented

- Added `l6_gas` to both chat and query APIs, with eligible owner/session/ready
  passages filtered before dense/BM25 ranking. The new path uses exact cosine
  over eligible passages, dense top64, a union of hybrid top15 lists, pinned
  L6 logits, baseline GAS, and protected-five refinement to return up to eight
  unique passages. Multiple passages from one PDF are allowed.
- Added an independent application profile: lexical weight **0.25**, baseline
  diversity penalty **0.05**, eight-/16-bit coefficients, 64 phase calls,
  32 trials per stage, growth factor 1.2, seed 0, and existing 15-second /
  200,000-state budgets. These application defaults are separate from the
  frozen FiQA configuration and are not tuned claims about uploaded PDFs.
- Added lazy, serialized local-only L6 loading at the pinned revision. Raw
  logits, normalized relevance, cosine scores, and embeddings remain separate.
  Original shortlist scores are reused during expansion. Inputs exceeding the
  512-token pair budget are rejected; missing models return explicit 503s.
- Packaged unchanged selection mathematics in application-local kernels with
  source checksums and rewritten package imports only. Phase marking and
  amplification remain actual simulator operations. Backend runtime imports
  do not depend on benchmark runners or data loaders.
- Preserved source/page citations, persisted provenance, actual method,
  separate baseline/refinement outcomes and resource counts, termination
  reasons, and complete pipeline timings. Model loading/warm-up are also
  reported separately. No physical-QPU or quantum-superiority claim is made.
- Minimal frontend wiring now defaults new requests to L6-guided GAS and
  eight passages. Existing choices/design remain. Submitted settings and run
  IDs are reused on retry, and old persisted source records remain compatible.
- Added regression coverage for kernel parity, constraints/budgets, independent
  objectives, scores/token limits, document isolation, both endpoints,
  unavailable models, persisted/idempotent results, and supervisor recovery.

Implementation entry points: `backend/services/gas_retrieval.py`,
`backend/services/l6_scorer.py`, `backend/services/gas_profile.py`, and
`backend/services/gas_selector/`. Operational details and model provisioning
are documented in `backend/README.md`.

### Verification status and automatic deferred checks

Passed during collection: **three lightweight frontend contract/retry tests**,
Python AST parsing for changed/new modules, JSON parsing, kernel-origin hash
checks, running research-source fingerprint checks, and `git diff --check`.
No application inference, simulator tests, TypeScript build, or production
build were run during timed collection.

The detached application verifier waits for the FiQA supervisor to exit with
`completed` or `gate_failed`, then runs backend regressions, frontend contract
tests, TypeScript, lint, the production build, and a local pinned-L6 smoke
check. It records a source identity, per-check logs and exit codes, stops on
the first failing check, and updates the completion block below. If FiQA fails
technically or is interrupted, verification stops with an explicit reason.
It does not alter experimental results, deploy the app, or call Gemini.

Launcher: `backend/.venv/bin/python build/application_gas/verify_after_fiqa.py`.
After interruption, use the same command with `--resume`; source changes
require review and rerunning the documented checks against the changed code.
State: `build/application_gas/verification.json`.
Supervisor log: `build/application_gas/verification_supervisor.log`.
This background verifier avoids continuous assistant monitoring. Full backend
correctness and model smoke verification remain **pending** until it passes.

<!-- APPLICATION_GAS_CHECKS_START -->
Application verification status: **passed** (2026-10-18T05:11:03.844190+00:00).
Detailed results: `build/application_gas/verification.json`; per-check logs are beside it.
- backend_regressions: passed (exit 0).
- frontend_contracts: passed (exit 0).
- typescript: passed (exit 0).
- frontend_lint: passed (exit 0).
- frontend_build: passed (exit 0).
- local_l6_smoke: passed (exit 0).
<!-- APPLICATION_GAS_CHECKS_END -->

## Accepted plan prepared 17 October — historical checklist

The checklist below records the plan before launch. Its references to
"tomorrow", waiting for a start instruction, or implementing the launcher are
historical. The active execution record above is the current source of status.

### 1. Verified starting point

- SciFact and NFCorpus full v3 follow-up test results are already preserved.
  Do not rerun either dataset.
- FiQA's 100-query confirmation is complete, sealed, evaluated, and reported.
  Its gate passed: nDCG@5 was unchanged, mean Recall@8 decreased **0.962572%**,
  and mean redundancy decreased **8.855904%** against the matched baseline.
  These are confirmation results, not full-test results.
- The continuation state is `paused_after_fiqa_confirmation`, with
  `fiqa_full_test_started=false`. The new FiQA full-test directory and frozen
  confirmation configuration do not yet exist.
- Confirmation input:
  `research/runs/accuracy_v3_redundancy_fiqa_confirmation/`.
- Preserve the older FiQA full-test results and all historical artifacts.
  The manuscript currently uses the older 648-query FiQA result; replacing
  manuscript values is a separate follow-up after verified new results exist.

### 2. FiQA-only full evaluation

- [ ] Recheck the confirmation checksums and coverage, current source and
  dependency fingerprints, pinned models, token limits, free storage, and the
  existing corpus embedding cache. Stop on missing or corrupt inputs; do not
  rebuild embeddings or change dependencies to bypass an incompatibility.
- [ ] Freeze the existing successful confirmation without rerunning or tuning
  its 100 queries.
- [ ] Collect **648 official test queries, all 27 methods, and seeds 0–4**.
  Keep FiQA's development-selected v2 baseline configuration and the v3
  refinement configuration unchanged. Do not substitute the application's
  default profile for the frozen FiQA profile.
- [ ] Retain the established baseline 15-candidate/eight-output configuration,
  eight-bit baseline and 16-bit refinement coefficients, 64 phase calls and
  32 trials per stage, growth factor 1.2, and existing time/basis budgets.
- [ ] Build a dedicated detached FiQA-only supervisor outside the fingerprinted
  research packages. Create its run identity and execution state before model
  initialization, use an exclusive lock, save the PID, and retain separate
  supervisor and stage logs. Verify that the child remains running and has
  committed initial progress, then leave it running without continuous
  assistant monitoring.
- [ ] Preserve stage checkpoints, source snapshots, per-query atomic commits,
  recorded timings, and session boundaries. Resume verified completed work
  rather than recollecting it. Stop on execution errors or integrity failures.
- [ ] Check complete query/method/seed/artifact coverage before sealing. Run
  independent `trec_eval` checks, seed-within-query aggregation, paired
  confidence intervals, evaluation, and reporting.
- [ ] Report each acceptance condition separately: nDCG@5 unchanged within
  `1e-12`, mean Recall@8 at least 98% of the matched baseline, and lower mean
  clipped-positive pairwise cosine redundancy. Include nDCG@8, per-query recall
  losses, full-pipeline median/P95 latency, optimization outcomes, fallback
  counts, and separate baseline/refinement work. Record scientific gate
  failures explicitly without retuning against the test judgments.

**Do not resume the original three-dataset batch:** it still enforces the
NFCorpus confirmation failure. The existing
`build/accuracy_v3/continue_nfcorpus_then_fiqa.py` controller deliberately ends
after FiQA confirmation and cannot launch FiQA's full test.

The existing CLI stage commands, to be supervised tomorrow from the repository
root, are:

```bash
backend/.venv/bin/python -u -m research.accuracy_v3 preflight
backend/.venv/bin/python -u -m research.accuracy_v3 freeze \
  --directory research/runs/accuracy_v3_redundancy_fiqa_confirmation \
  --output research/runs/accuracy_v3_redundancy_fiqa_frozen.json
backend/.venv/bin/python -u -m research.accuracy_v3 run \
  --dataset fiqa \
  --directory research/runs/accuracy_v3_redundancy_fiqa_test \
  --frozen research/runs/accuracy_v3_redundancy_fiqa_frozen.json
backend/.venv/bin/python -u -m research.accuracy_v3 evaluate \
  --directory research/runs/accuracy_v3_redundancy_fiqa_test
backend/.venv/bin/python -u -m research.accuracy_v3 report \
  --directory research/runs/accuracy_v3_redundancy_fiqa_test
```

The preflight command checks existing inputs/caches for all three datasets; it
does not collect benchmark rankings or encode a corpus. Only FiQA receives
new ranking collection. The supervisor must stop when a stage fails and retain
the completed stage records.

**Planned launcher interface, to be implemented tomorrow:**
`backend/.venv/bin/python build/accuracy_v3/launch_fiqa_full_test.py`;
add `--resume` after an interruption. This launcher does not exist yet. It must
detach, refuse duplicate execution, and resume the same stage/directory rather
than create replacement results. Collection itself supports the existing
`run` command above with `--resume` appended.

**Planned monitoring and recovery paths:**

- State: `research/runs/accuracy_v3_redundancy_fiqa_full_execution.json`.
- Supervisor log: `research/runs/accuracy_v3_redundancy_fiqa_full_supervisor.log`.
- PID and lock: the same `accuracy_v3_redundancy_fiqa_full` prefix with `.pid`
  and `.lock` suffixes under `research/runs/`.
- Stage logs: `research/runs/accuracy_v3_redundancy_logs/fiqa_full_<stage>.log`.
- Final report: `research/runs/accuracy_v3_redundancy_fiqa_test/REPORT.md`.

For a requested stop, validate the recorded PID/process identity and signal the
supervisor with SIGTERM. The supervisor must forward a graceful interrupt to
its active child, await its exit, and record an interrupted state. Keep all
committed artifacts and use the launcher with `--resume` to continue; do not
delete checkpoints or use an unverified historical PID.

**Estimated runtime:** approximately **1.5–2 hours** for FiQA collection and
checks, depending on CPU availability and cache integrity. This excludes
application implementation and verification. Describe the new official-test
results as follow-up evaluations because these test judgments were examined
previously. Do not claim Grover speed, cost, or effectiveness superiority
without supporting matched comparisons.

### 3. Backend update after FiQA completes

- [ ] Add a distinct `l6_gas` retrieval strategy to both query and chat paths.
  Keep the existing strategies available with their existing meanings.
- [ ] Scope to the authenticated owner, session, metadata filters, and ready
  uploaded documents before ranking. Compute cosine and BM25 over eligible
  passages, take dense top64, and form the deduplicated union of hybrid top15
  lists at lexical weights `{0, 0.25, 0.5}`. Multiple passages from one PDF are
  permitted; return up to eight unique passages when the pool is undersized.
- [ ] Score the original shortlist first using raw pinned L6 logits; preserve
  those scores before scoring additional union candidates. Run baseline GAS,
  protect its first five passages, and refine the remaining three under the
  existing componentwise L6-score constraints and redundancy objective.
  Preserve prefix order and order the selected tail by raw L6 score.
- [ ] Use an explicit application profile: lexical weight 0.25, baseline
  diversity penalty 0.05, eight-bit baseline coefficients, 16-bit refinement
  coefficients, 64 phase calls and 32 trials per stage, growth factor 1.2,
  seed 0, and bounded search time/basis size. This is an application default,
  not a development-tuned profile for uploaded PDFs.
- [ ] Load the pinned `cross-encoder/ms-marco-MiniLM-L6-v2` revision
  `233902d25c440f23af6f7d6e94d2946bac0bee0a` once with bounded blocking work.
  Check the 512-token pair limit explicitly and preserve raw logits separately
  from normalized relevance, cosine scores, and embeddings. Separate model
  loading/warm-up from online timing.
- [ ] Package the selector independently of benchmark runners, preserving
  actual phase marking and amplitude amplification. Verify agreement with the
  frozen research implementation using identical inputs, seeds, and budgets.
  Keep fingerprinted research files, `backend/config.py`, existing circuit,
  quantum-search and worker modules, and benchmark dependency versions intact;
  add application settings in a separate module.
- [ ] Preserve source IDs, document/page citations, session isolation, chat
  persistence, and run-ID idempotence. Add the actual method, separate raw
  scores, stage timings, termination reasons, and baseline/refinement resource
  accounting to response provenance. Do not present amplitude probabilities
  as relevance scores.
- [ ] Return an explicit service-availability error if L6 cannot load; do not
  silently report another method as GAS. Budget exhaustion returns the
  feasible incumbent and records the actual termination reason.

### 4. Frontend update

- [ ] Make **L6-guided GAS** the default for new chatbot requests and request
  eight passages. Retain the older retrieval choices with distinct labels.
- [ ] Extend the validated response contract for new scores/provenance while
  keeping older persisted chat records readable.
- [ ] Display the actual retrieval method, source count, retrieval time, source
  citations, and relevant fallback/termination information. Preserve existing
  authenticated document links.
- [ ] Capture retrieval settings in the submitted message variables so retry
  retains the original strategy, parameters, and run ID even if the dropdown
  changes after the first attempt.
- [ ] Describe this as a passage-based application adaptation. Prefix stability
  and score constraints do not establish benchmark accuracy guarantees for
  uploaded PDFs or guarantee true relevance.

### 5. Verification and handover

- [ ] Test selector parity, preserved prefixes, unique outputs, small/empty
  pools, ties, negative/constant logits, invalid values, reproducible seeds,
  phase/reflection behavior, normalized states, improving updates, and budget
  termination.
- [ ] Test document lifecycle/owner/session isolation, unavailable-model
  responses, both retrieval endpoints, persisted provenance, and retry
  settings/idempotence. Use fixtures and mocked generation for routine tests.
- [ ] Run relevant backend regression tests, frontend contract/retry tests,
  TypeScript, lint, and the production build. Record pre-existing warnings
  separately from regressions.
- [ ] After FiQA finishes, perform a small local pinned-L6 inference check and
  a citation/source smoke check. Do not run application inference, heavy
  builds, or simulator checks concurrently with timed benchmark collection.
- [ ] Record the final FiQA gate results, report paths, commands, passed checks,
  application changes, and unresolved limitations here. Do not mark planned
  tests as passed before they actually execute.

## Historical record — superseded execution instructions

Everything below is retained as historical context. Wording such as "now
runs", "live", "latest instruction", and recorded PIDs describes the earlier
session, not a current process or a command to restart. The 18 October plan
above is the next-work checklist.

### Completed manuscript revision — supersedes older paper notes

The user authorized a complete manuscript update using the new full SciFact
and NFCorpus tests and **only the older 648-query FiQA test**. The unified
method label is **L6-guided GAS**; one table note and the method description
disclose the configuration difference. FiQA's 100-query confirmation is
excluded. No new benchmark ranking collection, model inference, or experimental
source/result modifications are authorized as part of this paper update.

The live manuscript is `new_paper/main.tex`, its source mapping is
`manuscript_support/paper_sources.json`, and generated evidence is under
`manuscript_support/records/`. Required LaTeX fragments are in
`new_paper/includes/`; `new_paper/` contains only the standalone upload files.
Older loose scripts, notes, images, and tables are preserved in
`manuscript_support/history.zip`. The manuscript-only exporter verifies sealed
inputs and recomputes saved-ranking summaries. Optional `--check-metrics`
checks existing rankings with NIST trec_eval without running retrieval or
selectors. The supplied conference IEEEtran class is copied unchanged.

Build/reviewer response: `manuscript_support/build_manuscript.py`. See
`manuscript_support/README.md` for commands and the later one-directory FiQA replacement.
The build checks 6–8 pages, fonts, references, overflow, and mathematical claims;
the conclusion is one generated 150–200-word paragraph. Every page requires
visual inspection. No external submission is performed.

Scientific reporting retains SciFact's recall loss, the NFCorpus failed
confirmation and continuation exception, test reuse, matched classical
agreement, and full pipeline timing. Complete native constrained-oracle depth
studies remain unperformed, and FiQA's full refinement test remains future work.
There is no established Grover speed, cost, or superiority claim. Historical
execution notes below are retained and are not a description of a live process.

Completed manuscript verification: 119,124 independently recomputed
query/method metrics and 145,290 saved-ranking metric checks through NIST
trec_eval; 1,233 score/count-constraint cases and 180 quantization/regret cases;
8-page PDF, 189-word abstract, one 172-word conclusion; all fonts embedded,
no unresolved references or overfull boxes. Every page was visually inspected,
including the balanced references page. The supplied class, experimental source
identities, mapped result hashes, and generated evidence hashes were verified.
`manuscript_support/records/publication_checks.json` and
`manuscript_support/records/visual_inspection.json` retain evidence.
No new dataset collection or model inference was started during paper revision.
The cleaned folder also compiled in isolation without Python or JSON inputs;
its visible text and all eight rendered pages matched the prior checked PDF.

## Accuracy v3: latest authorized execution

**Latest instruction: continue NFCorpus's full test evaluation despite its
failed confirmation recall gate, then run only FiQA's first 100 confirmation
queries, evaluate/report them, and stop for the night.** The user explicitly
authorized this exception after seeing the failure. No ranking parameters or
global acceptance thresholds are changed, and failed gate outcomes remain
reported as failed. The earlier interrupted run's 25 SciFact checkpoints remain
preserved.

SciFact's 300-query test run is complete and passed its gates. The original
supervisor (298939) stopped automatically after NFCorpus's 100 confirmation
queries: recall fell 2.1561% relative, beyond the 2% limit, while redundancy fell
3.0812% and nDCG@5 remained unchanged. Its original `gate_failed` state and sealed
results are retained.

A separate detached continuation controller (PID **345058**) now runs
`build/accuracy_v3/continue_nfcorpus_then_fiqa.py`. It preserves the frozen v3
package and records the exception in
`research/runs/accuracy_v3_redundancy_nfcorpus_continuation_protocol.json`.
The full NFCorpus test run snapshots this controller, binds the protocol hash
into its identity, and uses the same 27 methods/five seeds/configuration. Its
evaluation/report explicitly disclose the failed confirmation gate. Technical
or integrity failures still stop progression; NFCorpus's final scientific gate
does not prevent the specifically authorized FiQA confirmation stage.

Live continuation state:
`research/runs/accuracy_v3_redundancy_continuation_execution.json`.
Supervisor log:
`research/runs/accuracy_v3_redundancy_continuation_supervisor.log`.
Per-stage logs and dataset directories retain the usual `accuracy_v3_redundancy`
prefix. The controller has no FiQA freeze or full-test stage: after exactly 100
FiQA confirmation queries plus independent evaluation/report, it records
`paused_after_fiqa_confirmation` and exits. FiQA's full test requires a later
user instruction. Chat monitoring ends once initial progress is verified.

If interrupted, resume this continuation with the same source and protocol:

```bash
backend/.venv/bin/python -u build/accuracy_v3/continue_nfcorpus_then_fiqa.py --resume
```

The original batch's `--resume` still enforces its original gate and is not the
continuation entrypoint. The continuation authorization is dataset/stage scoped,
recorded separately, and does not relabel a failed confirmation as passing.

The user authorized implementation, verification, and detached background
evaluation of SciFact → NFCorpus → FiQA with the wider-pool, protected-prefix
Grover refiner. This authorization supersedes the historical pause notes below.
The user permits at most a **2% relative mean Recall@8 decrease** against the
matched v2 GAS baseline: candidate recall must be at least 0.98 × baseline
recall. nDCG@5 must remain unchanged and the original redundancy metric must
decrease. No manuscript or chatbot/backend changes are included.

Implementation: `research/accuracy_v3/`, independently versioned and snapshotted.
All existing v2 Python files, caches, frozen configurations, and sealed runs are
preserved. Dense top64 feeds the deduplicated union of hybrid top15 lists at
lexical weights 0, .25, .5. Original shortlist L6 scores take precedence; only
additional union candidates receive additional inference. Each seed preserves
the original GAS first five IDs, then refines the three-document tail under
componentwise L6-score dominance. The tail is L6 ordered; it is intentionally
not a global L6 sort when new candidates score above the protected prefix.
GAS uses 16-bit pair coefficients, 64 refinement phase calls, 32 trials, growth
1.2, and seeds 0–4. Original and refinement oracle work are recorded separately.

The sequence is **100 fresh training confirmation queries → independent metrics
and report → freeze → full test collection → independent metrics and report**
for each dataset, in order. The supervisor explicitly requires exactly 100
sealed and evaluated confirmation queries before freezing. Any failed accuracy
or redundancy criterion records `gate_failed`, stops the entire batch before
test collection, and prevents the next dataset from starting. Resuming checks
this gate again rather than bypassing it. Confirmation sampling uses
`accuracy-v3-confirmation-v1`, excludes recorded historical development/test/
pilot IDs, and records the exclusion sources and selected IDs. The v2 lexical,
penalty, MMR and legacy parameters are reused without retuning. No judgments
enter selection. Failures of confirmation or complete-test acceptance gates
stop the batch; failed results remain intact. Do not retune against test data.

There are 27 methods: the original 20 plus protected-prefix constrained GAS,
local-swap greedy, exact float, exact quantized, matched random search, global
union L6, and protected-prefix union L6. Exact/greedy/random refiners receive the
same prefix, scores, and eligibility rules. All inherited-prefix methods carry
five seed results, including deterministic controls conditioned on that prefix.
Fresh online timing includes retrieval, lexical processing, original/additional
L6 inference, baseline selection and refinement where required. Loading and
warm-up remain separate. No physical quantum speed/cost claim is established.

Commands (from repository root):

```bash
backend/.venv/bin/python -u -m research.accuracy_v3 preflight
backend/.venv/bin/python -u -m research.accuracy_v3 smoke
backend/.venv/bin/python build/accuracy_v3/launch_background.py
# Recovery with the identical source, data, packages and frozen configuration:
backend/.venv/bin/python build/accuracy_v3/launch_background.py --resume
```

The active/default batch name is `accuracy_v3_redundancy`.
`--batch-name` selects a separate namespace; the older interrupted
`accuracy_v3` experiment is preserved and cannot be resumed with changed source.
The refreshed preflight, smoke, and detached launch commands above were
executed after the user's renewed start instruction. Verification evidence
matches the updated source. No manuscript changes are included.

Monitoring: `research/runs/accuracy_v3_redundancy_execution.json`,
`research/runs/accuracy_v3_redundancy_supervisor.log`, and per-stage
`research/runs/accuracy_v3_redundancy_logs/<dataset>_<stage>.log`. The execution record
contains the supervisor/child PIDs, stage progress, and a stage time estimate
after committed queries appear. Collection directories are
`research/runs/accuracy_v3_redundancy_<dataset>_{confirmation,test}`; frozen configuration
files are outside sealed confirmation directories. Reports and aggregate
summaries appear only after collection integrity and metric coverage checks.

Graceful stop: send SIGTERM to the live `supervisor_pid` recorded in the
execution JSON; it forwards SIGTERM to the active child. Resume the same batch
with `--resume`. Retrieved inputs, original scores, expanded features, and
complete query results are separate atomic checkpoints. Completed queries are
verified and skipped; original timings and session boundaries are retained.
Corruption or incompatible provenance causes an explicit error, not replacement
of committed work. A failed scientific gate requires investigation; resuming
does not bypass the gate or authorize retuning.

Refreshed verification passed before the active launch: all three cache/token/model/data preflights;
12 synthetic selector, pipeline, gate, recovery, and supervisor tests; exact
replay of 1,920 saved prototype seed requests (128 queries × 3 datasets × 5
seeds); 3,840 independent trec_eval metric checks; and two local L6 inference
pairs. Evidence is recorded in `build/accuracy_v3/{preflight,smoke}.json` and
matches the active source revision, including the explicit 100-query gate and
separate batch namespace. Verification was rerun only after the user requested
execution again.

Historical supervisor launched at **2026-10-17 14:27:41 UTC**
(19:57:41 Asia/Kolkata), PID **294933**, beginning SciFact confirmation, and
stopped at **14:29:57 UTC** with 25 committed queries. Its state is
`research/runs/accuracy_v3_execution.json` (`interrupted`); both recorded
processes are no longer running. Keep its checkpoints and source snapshots.

Previous batch timings: 28.30 minutes SciFact, 30.91 minutes NFCorpus, 103.23
minutes FiQA, approximately 2h42m total. Budget approximately **2–3 hours after
v3 launch**, excluding implementation/verification, assuming comparable CPU
availability and cache hits. Fresh confirmation throughput refines the estimate.

Official-test results are post-hoc follow-up evaluations because these tests
were already examined. Keep numerical ties within 1e-12, average seeds within
queries, cross-check nDCG@5/Recall@8 with trec_eval, and report nDCG@8, individual
query losses, classical controls, statuses, unchanged/fallback counts, and
confidence intervals. A passing empirical mean gate is not a proof of
non-inferiority. Mean embedding cosine is a proxy, not a duplicate percentage.

## Current evaluation execution

The user explicitly authorized fresh full evaluation of **SciFact, NFCorpus and
FiQA**, in that order, on 17 October 2026. **The full v2 batch is now complete.**
All 12 stages exited successfully: 1,271 test queries, 20 methods per dataset,
and 101,680 official trec_eval metric checks. Final artifacts for all datasets
were verified again after completion. Manuscript updates remain outside this
execution stage.

Each dataset runs development tuning, frozen-configuration test collection,
independent evaluation and reporting before the next dataset begins. All neural
controls and the older Grover comparison are enabled (`--legacy-grover`), giving
20 test methods and all five seeds. Existing embedding caches and historical
results are preserved. Failures stop progression; interrupted stages resume their
committed work.

Live machine status: `research/runs/accuracy_v2_execution.json`.
Supervisor log: `research/runs/accuracy_v2_supervisor.log`.
Stage logs: `research/runs/accuracy_v2_logs/<dataset>_<stage>.log`.
Run directories: `research/runs/accuracy_v2_<dataset>_{dev,test}`.
Completed summaries are in `research/runs/accuracy_v2_summary.{json,md}`. Use the
audited comparisons in `research/runs/accuracy_v2_statistics_audit/` for
significance claims: seed averaging introduced floating-point differences near
1e-16 for otherwise identical nDCG values, which the raw evaluator could mark
significant. The separate audit treats per-query differences at most 1e-12 as
numerical ties, repeats the paired tests and Holm correction, and preserves all
sealed raw runs. GAS and matched L6-only have equal nDCG on all three datasets;
there is no demonstrated extra nDCG benefit from GAS in these results.

The durable supervisor is
`build/accuracy_v2/run_all_datasets.py`; restart an interrupted batch with its
`--resume` flag, without changing the recorded code or flags.

## Prior checkpoint (dataset pause superseded by the authorization above)

**Latest authorized stage, 17 October 2026: accuracy-v2 code implementation and
bounded verification only. Full dataset evaluations and manuscript updates are
still paused.** The user subsequently authorized unit tests, preflight checks,
saved development-feature replay, and small local inference checks. Those checks
do not authorize full development sweeps or new test-set evaluations.

The corrected historical SciFact evaluation is
complete and its results are logged in `new_paper/scifact_results.md` and
`new_paper/scifact_results.json`. The active NFCorpus evaluation and automatic
evaluation chain remain stopped. Do not restart benchmark runs, secondary
studies, or paper builds until the user explicitly requests them.

Start NFCorpus only when the user explicitly requests it. That instruction will
authorize NFCorpus alone; do not automatically continue to FiQA or other studies.
See `new_paper/RESUME.md` and `new_paper/evaluation_checkpoint.json` for the exact
completed/partial run paths, preserved caches, and future commands. The remaining
sections describe the future work, not authorization to execute it now.

The user authorized the evaluation and paper-revision phases earlier today;
that authorization is now limited by this explicit stop. Preserve every run and
use only corrected, complete, verified artifacts for publication claims.

Subsequent discussion requested a stronger hyperparameter proposal before
another SciFact experiment. The research-only follow-up is recorded in
`new_paper/hyperparameter_recommendation.md` and
`new_paper/proposed_hyperparameters.json`: primary candidate lambda 0.05,
eight-bit coefficients, and unchanged 15/8 pool/output and 64/32 search budgets.
That document predates the implemented v2 variant described below. Its values
remain unselected on full development data. No full development sweep or dataset
run has restarted. Preserve the original results and do not use test-set
performance to choose parameters.

The later accuracy review is recorded in `new_paper/accuracy_analysis.md` and
`new_paper/accuracy_diagnostics.json`. The priority proposal is a separately
versioned L6-guided GAS experiment: relevance from the existing pinned L6
cross-encoder, initialization and final ordering by that same score, and a
matched L6-only control. A cheaper hybrid-guided branch, context coverage and
candidate coverage are separate comparisons. Those analysis documents predate
the small development tests and the new versioned code; the v2 status below is
the current implementation record. The manuscript and historical research code
were not changed in this implementation stage.

Implemented code:

- `research/selection.py`: compact ideal Grover Adaptive Search (GAS), the
  relevance/redundancy objective, bounded search, result traces, classical
  comparators, and selection metrics.
- `research/selection_features.py`: deterministic representative-chunk features
  and optional, explicitly loaded neural rerankers.
- `research/selection_circuits.py`: small Qiskit reference circuits for unit
  checks. This intentionally does not claim scalable 15-candidate native circuit
  execution or an efficient Dicke-state implementation.
- `research/selection_experiment.py`: opt-in dataset runner, development tuning,
  per-seed artifacts, source snapshots, checksums, evaluation/reporting, and a
  standalone feature-file selector CLI.
- `research/run.py`: `--profile gas` dispatch; legacy remains the default.
- FiQA registration in the existing dataset configuration/loader. The official FiQA archive has now been obtained and checksum-verified;
  split/token checks are recorded in `new_paper/data_preflight.json`.
- `research/test_selection.py`: artificial numerical inputs, mocked models,
  temporary feature files, and small reference-circuit unit checks only.

An updated manuscript draft and generation tools were prepared before the pause;
final tables, figures, reviewer response, and publication PDF remain pending.
No manuscript source or research implementation was changed while recording
this stop. Preserve existing research runs. The working tree already contained
a modified `Patent.docx` and a deleted `new_paper/main.pdf` before this task;
do not treat those as new changes, restore them, or overwrite the supplied
reference PDFs automatically.

The raw-tokenizer initialization defect found during the 17 October audit has
been corrected. Earlier initial runs are superseded and retained; see
`new_paper/preprocessing_correction.md`. Only freshly collected corrected runs
may supply the paper. Corpus embedding caches bind exact chunk text, model
revision, code, and versions, with integrity checks.

## Accuracy v2: implemented code and verification

The new entrypoint is `backend/.venv/bin/python -m research.accuracy_v2`.
Its implementation lives entirely under `research/accuracy_v2/`; the historical
runner, sealed results, original input datasets, and manuscript are preserved.
The older protocol in sections 1–8 below describes the original cosine-guided
study. Use this section for the new accuracy variant.

### Pipeline and comparisons

1. Pinned dense MiniLM retrieves the top 64 parents using maximum chunk cosine.
2. Choose 15 using `h = (1-beta)*d + beta*b`, initially beta 0.25;
   `d=(1+cosine)/(1+maximum shortlist cosine)` and
   `b=BM25/maximum shortlist BM25`. With zero lexical maximum, use the dense
   channel alone. A near-zero dense denominator uses `(1+cosine)/2`.
3. Score each parent's maximum-cosine representative passage with the pinned
   MS MARCO MiniLM L6 cross-encoder. Preserve raw logits, raw cosine, normalized
   relevance, passage IDs, and embeddings as separate fields. Scores are not
   calibrated relevance probabilities. Refuse inputs exceeding 512 tokens.
4. Normalize logits within the fixed pool using min–max; a range at most 1e-12
   receives equal relevance 0.5. Initialize GAS from raw L6's top eight.
5. GAS selects eight jointly, using the same relevance/redundancy objective and
   original representative embeddings. Order the result by unrounded L6 logits,
   then document ID. Defaults are lambda 0.05, eight bits, 64 phase calls,
   32 trials, growth 1.2, and seeds 0–4.

The phase oracle and uniform reflection really execute in the compact simulator.
All subset-energy enumeration is counted as classical simulator work. This is
not physical quantum execution or a demonstrated quantum speedup.

Default collection includes 19 methods: guided GAS, same-pool L6-only, guided
greedy, quantized and continuous exact solutions, independently tuned guided
MMR, budget-matched guided random search; the original cosine/GAS/MMR/greedy/
exact/random/RRF controls; and L2/L6 on dense top 15 and top 64. Add
`--legacy-grover` consistently to tuning and collection for the twentieth,
older probability-based circuit control. `--no-neural-controls` omits only the
four additional neural controls, never the primary L6 scorer.

`online_total_ms` charges query encoding, retrieval, representative features,
lexical scoring/prefilter where needed, the full L6 inference cost where needed,
and selection. Sharing cached features does not make that cost disappear.
Loading, warm-up, corpus encoding/cache restoration, hardware, dependency
versions, and resumed-session boundaries are recorded separately.

### Recovery guarantees and limits

- Run metadata and source snapshots are saved before model setup/encoding.
- Atomic, checksummed files preserve retrieved features, scored features, and
  each complete query's full method/seed results. Resume validates and skips
  completed work; an unfinished work unit may be recomputed.
- New corpus encoding commits 512-row shards with eight-item inference batches.
  Verified completed shards survive interruption; assembly can restart without
  re-encoding them. Existing whole SciFact/NFCorpus caches remain compatible.
- Stop with Ctrl+C or SIGTERM. Use the identical command and directory plus
  `--resume`. SIGKILL/power loss can lose the uncommitted work unit, not earlier
  durable commits. A process lock prevents concurrent writers.
- Changed data, model files, dependencies, configuration, or source code cause
  explicit rejection. Do not bypass this by editing checkpoints or deleting
  checksums. Restore recorded code/options or start a distinct run; validated
  corpus caches may still be reused.
- Do not resume the old partial NFCorpus run as v2: its algorithm/schema differ.
- Completion requires exact query/method/seed coverage. Evaluation refuses
  incomplete or corrupt runs. Final manifests bind the original artifacts;
  independent metric checks and reports bind that manifest without rewriting it.

### Checks actually performed

- Compatibility regression command: **94 tests, one expected skip**, passed.
  After the final v2 lifecycle and baseline-accounting additions, its
  **20-test focused suite** passed.
- Fault injection before/after feature and result commits reproduced uninterrupted
  synthetic rankings; committed scoring/results were not repeated. Atomic rename
  failure, corrupt files/shards, incompatible identities, concurrent writers,
  incomplete coverage, and actual SIGTERM handling were checked.
- The synthetic CLI exercised development tuning, frozen-configuration loading,
  collection with 19 methods, completed-run resume, independent evaluation and
  reporting. These synthetic scores are never publication evidence.
- All three official archives/local inputs passed checksum, split, reference,
  query-length, first-document offset, chunk-budget and capacity preflight:

  | Dataset | Parents | Dev queries | Test queries | Chunks | Maximum pair-token bound |
  |---|---:|---:|---:|---:|---:|
  | SciFact | 5,183 | 161 | 300 | 13,505 | 255 |
  | NFCorpus | 3,633 | 324 | 323 | 9,970 | 219 |
  | FiQA | 57,638 | 500 | 648 | 92,391 | 233 |

- Actual SciFact and NFCorpus cache restoration passed with corpus encoding
  patched to raise if attempted. The historical SciFact manifest still verifies.
- Replayed all 32 saved exploratory development queries: exact hybrid shortlists,
  **960 saved-metric comparisons**, **160 zero-penalty equalities**, and **960
  official trec_eval metric checks** passed. Maximum rounding discrepancy was
  0.0000471928, below 0.000051. Reproduced means: nDCG@5 0.7618479899,
  Recall@8 0.843750. These means still equal the matched L6-only control.
- Two local L6 query/passage predictions reproduced stored logits within 2e-5.
  A separate single previously explored development query exercised actual dense
  cache restoration, all neural scorers, hybrid selection and all 19 methods/
  five GAS seeds. It reproduced candidates and logits without reading test
  judgments or re-encoding the corpus.

Evidence is under `build/accuracy_v2/`: `preflight.json`, `smoke.json`,
`cache_reuse.json`, `local_pipeline.json`, `verification.json`, `final_tune/`,
and `final_run/`. The final synthetic lifecycle independently checked 560
per-request metric values; these are synthetic checks, not benchmark results.
These are ignored local artifacts. Preflight records exact source/dependency/
model identities; code changes intentionally make it stale.

Repeat code-only checks when needed:

```bash
PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 TOKENIZERS_PARALLELISM=false \
  backend/.venv/bin/python -m unittest research.accuracy_v2.test_accuracy -v

backend/.venv/bin/python -m research.accuracy_v2 preflight --dataset all
backend/.venv/bin/python -m research.accuracy_v2 smoke
```

### Dataset execution protocol (completed on 17 October 2026)

Preflight is required before real development tuning or collection. The code
checks that it matches the current data, models, dependencies and sources. No
model download, corpus encoding, development sweep, or test ranking is generated
by preflight. Smoke uses saved development features and two local L6 predictions.

When the user explicitly starts a dataset, tune beta `{0, 0.25, 0.5}` and lambda
`{0, 0.01, 0.025, 0.05}` on that dataset's development split only, using all five
seeds. Require both mean nDCG@5 and Recall@8 to match or exceed same-pool L6-only.
Choose highest nDCG, then recall, lower redundancy, smaller lambda, smaller beta;
retain zero penalty if it wins. Independently tune the MMR comparator. Freeze
before test collection. SciFact uses its fixed 161 train-derived queries;
NFCorpus and FiQA use their official 324/500-query development splits.

Future commands below illustrate **one dataset**. They are not an automatic
three-dataset chain. Keep control flags identical between tune and run.

```bash
ACCURACY_DATASET=scifact

backend/.venv/bin/python -m research.accuracy_v2 tune \
  --dataset "$ACCURACY_DATASET" \
  --directory "research/runs/accuracy_v2_${ACCURACY_DATASET}_dev" \
  --legacy-grover

backend/.venv/bin/python -m research.accuracy_v2 run \
  --dataset "$ACCURACY_DATASET" \
  --directory "research/runs/accuracy_v2_${ACCURACY_DATASET}_test" \
  --frozen "research/runs/accuracy_v2_${ACCURACY_DATASET}_dev/frozen.json" \
  --legacy-grover

backend/.venv/bin/python -m research.accuracy_v2 evaluate \
  --directory "research/runs/accuracy_v2_${ACCURACY_DATASET}_test"
backend/.venv/bin/python -m research.accuracy_v2 report \
  --directory "research/runs/accuracy_v2_${ACCURACY_DATASET}_test"
```

Resume interrupted `tune` or `run` by adding `--resume` to the same command.
Run `evaluate` only after collection seals; reporting requires that evaluation.
The explicit `--preflight PATH` option supports a different preflight report.

Full development selection, test-set collection, independent metric checks and
reporting have completed for all three datasets. Selected (beta, lambda) values
were SciFact (0.25, 0), NFCorpus (0.5, 0.05), and FiQA (0, 0.025). The separate
paired-statistics audit covers all three completed datasets. Remaining work is
scientific interpretation and manuscript updates using the audited statistics;
the manuscript has not been edited in this evaluation stage.

## 1. Original study: research question and claims

The new pipeline is:

1. Encode and score the corpus using the existing pinned MiniLM encoder.
2. Retrieve a classical exact-cosine shortlist of 64 parent documents.
3. Pass its top **15 parent documents** to the selector.
4. Use GAS to select **8 documents jointly**.
5. Order those eight by original cosine score, then document ID.

This is **Grover-based evidence-set selection with classical within-set ordering**.
It does not mean that Grover reorders all 64 documents. Keep this distinction
consistent in the abstract, diagrams, algorithms, results, and reviewer response.
The old probability-based Grover reranker is retained as a comparison method.

Primary hypothesis: lower mean embedding redundancy than MMR while preserving
nDCG@5 within **0.01 absolute**. Confirm it only if paired confidence intervals
support both conditions. Speed, CPU work, memory, optimization success, and
comparisons against neural rerankers are additional measured outcomes.

The compact engine is a classical, ideal simulation of Grover phase marking and
reflection in the valid-subset basis. **It is not physical quantum execution or
full native Qiskit-circuit timing.** Preparing all subset energies is classical
work and is charged to its timing and counters. The exact optimizer must remain
a strong comparator: if the simulator has computed every subset energy,
classical argmin may solve the same objective more cheaply. Do not hide that
fact, subtract that work, or claim quantum speedup from compact simulation.

## 2. Fixed algorithm and objective

For a selected set S of size m:

    U(S) = mean(r_i for i in S) - lambda * mean(d_ij for i < j in S)
    r_i = (1 + cosine(query, representative_chunk_i)) / 2
    d_ij = max(0, cosine(representative_chunk_i, representative_chunk_j))

- Representative: the maximum-query-cosine chunk of the parent, with the lowest
  original chunk index resolving exact ties. Retain the exact passage text.
- Default pool/output: 15/8; feasible subsets: 6,435.
- Default coefficient precision: **6 bits**. Relevance coefficients are rounded
  from `63 * r_i`; pair penalties from `63 * 2 * lambda / (m - 1) * d_ij`.
  Minimize negative relevance plus these pair penalties. Use ties-to-even rounding.
- Trace both quantized energy and unquantized utility. They are distinct.
- Initial incumbent: cosine top eight. Accept strictly lower integer energy.
- Adaptive window: start at 1, grow by 6/5 on a failed improvement, reset after
  an improvement, cap at sqrt(number of feasible subsets). Do not use the number
  of better states or the exact optimum to choose iterations or stop the search.
- Per seed: at most 64 phase-oracle applications, 32 measured trials, or 15 s.
  One sampled subset per trial. Time checks are cooperative, between operations;
  the limit is not a hard operating-system preemption guarantee.
- Seeds: 0, 1, 2, 3, 4. Never select the best seed for the primary result.
- A failed improvement search returns its best incumbent, with its budget/time
  status. Include it in denominators. Zero budgets and undersized pools are
  explicit cases, not successful amplification.
- Logical register-width estimates are computed separately from compact RAM.
  With six-bit coefficients, 15/8 can require about 26 logical qubits under
  conservative bounds; the earlier 24-qubit estimate used four-bit coefficients.
  Do not equate compact amplitude storage with full-circuit memory consumption.

## 3. Prepare the next session before touching test data

1. Review the code diff and rerun the synthetic unit tests. Do not install or
   upgrade the working Qiskit/PyTorch environment merely to remove deprecations.
2. Confirm the organizer's camera-ready deadline (user supplied 21 October 2026)
   and any additional requirements supplied by email. Target the complete
   reviewable package by 20 October. Do not send email or submit files without
   an explicit user instruction.
3. Obtain/cache the official BEIR FiQA archive using its upstream source and
   preserve archive/file checksums. The loader itself never downloads data.
4. Confirm official corpus/query/qrel layout and licenses for all three datasets.
   Check positive test-query counts: SciFact 300, NFCorpus 323, FiQA 648.
   Verify query text exists for every judged test ID; do not silently skip any.
5. Confirm development/test disjointness. SciFact uses the existing deterministic
   20% train-derived sample; NFCorpus and FiQA use their official dev splits.
6. Check whether any FiQA query exceeds the frozen 190-content-token query
   policy. The current encoder raises rather than truncating. If this occurs,
   decide and document one explicit preprocessing policy before all runs;
   implement/test it and rerun affected comparisons consistently. Never drop
   long queries or choose a policy after inspecting test effectiveness.
7. Retain the existing encoder revision and 190-content-token chunks with
   32-token overlap. Verify parent-score aggregation and representative identity.
8. Explicitly resolve and record the neural model snapshots before test runs.
   The `--neural-baselines` flag can download models on that future invocation;
   its resolved revisions are written to each manifest. Reuse the same snapshots
   across datasets and check that revisions do not drift between runs.
9. Set a consistent two-thread CPU environment. Record host CPU, RAM, versions,
   thread limits, background load, and timing boundaries. Ensure disk space for
   representative embeddings, passages, traces, and source snapshots.

Old September results passed data/result checksums during planning, but their
source verification already failed on `backend/config.py`. Preserve those runs.
Do not bypass their verifier or reseal them using today's source. New code and
new claims require new runs with the new source snapshot.

## 4. Development pilot and configuration freeze

1. Select 16 development queries per dataset using deterministic query-ID hashing
   (independent of relevance/performance). Persist the chosen IDs.
2. Check pool membership, representative text, similarity matrices, fixed output
   cardinality, sorting, budget limits, timeout states, and seed reproducibility.
3. Check that GAS energy never beats the exact quantized optimum, that accepted
   incumbents improve integer energy, and that energy-table preparation is fully
   represented in the counters and latency. Inspect objective-quantization gaps.
4. Compare native MMR ordering, native reciprocal-rank-fusion ordering, GAS plus
   cosine ordering, and neural ordering. Do not silently replace a comparator's
   usual ordering with cosine and then call it the original reranker.
5. Profile real representative inputs, including query encoding, classical
   retrieval, feature construction, selector preparation, search, model loading,
   and neural scoring. Prior synthetic timing estimates are not final results.
6. Rerun optional small Qiskit equivalence checks with representative numerical
   coefficients. Native 10/8, 12/8, and 15/8 generic circuits are now additionally
   constructed by `new_paper/additional_studies.py` for synthesis-only resource
   accounting, with 2/4/6 coefficient bits and a 180-second per-case cap. Small
   equivalence tests pass. These circuits do not replace the compact engine or
   implement efficient Dicke preparation; never call compilation QPU timing.
7. Tune positive lambda values {0.1, 0.25, 0.5} on full development judgments
   using the exact quantized objective. Choose lowest redundancy among settings
   with mean nDCG@5 >= cosine baseline minus 0.01; ties prefer higher nDCG, then
   smaller lambda. If none passes, retain 0.1 and record the failed target.
8. Inspect/freeze `config`, `tuning`, model revisions, split IDs, source hashes,
   and hardware before test evaluation. Do not retune from test outcomes.
9. Independently tune MMR's diversity weight on development data over
   {0, 0.1, 0.25, 0.5, 0.75, 1}. Maximize mean nDCG@5; ties prefer lower
   redundancy, then smaller weight. Freeze `mmr_tuning` separately from GAS.
   Use the frozen GAS objective to score all sets for comparable utility and
   exact-optimum gaps; the MMR selection weight controls its own ordering only.

The runner now performs the development pilot before full test collection.
`research.selection_studies` implements secondary ablations and fresh-process
feature-level memory measurements. Primary manifests fix 64 secondary query IDs
per dataset using `gas-secondary-studies-v1` before their outcomes are examined.
These samples are secondary studies, not replacements for complete test sets.

## 5. Full evaluation commands — authorized workflow

From the project root, after completing the preparation and pilot:

```bash
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 backend/.venv/bin/python -m research.run run \
  --profile gas --dataset scifact --encoder dense --tag gas_scifact_final \
  --neural-baselines --legacy-grover

OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 backend/.venv/bin/python -m research.run run \
  --profile gas --dataset nfcorpus --encoder dense --tag gas_nfcorpus_final \
  --neural-baselines --legacy-grover

OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 backend/.venv/bin/python -m research.run run \
  --profile gas --dataset fiqa --encoder dense --tag gas_fiqa_final \
  --neural-baselines --legacy-grover
```

Each command prints its new timestamped run directory. For each resulting run,
replace the literal example below with that exact directory, then run:

```bash
backend/.venv/bin/python -m research.run evaluate \
  --run 'research/runs/REPLACE_WITH_NEW_RUN_DIRECTORY'

backend/.venv/bin/python -m research.run report \
  --run 'research/runs/REPLACE_WITH_NEW_RUN_DIRECTORY'
```

Run status is recorded in `new_paper/REVISION_STATUS.md`; commands below
describe the reproducible workflow, not evidence of completion by themselves. The three test sets contain
1,271 judged queries in total. Corpus encoding and neural baselines dominate the
rough 2–4 hour planning budget; this duration is not a guaranteed measured total.
Gate-level resource studies, dataset acquisition, ablations, and manuscript work
are additional tasks.

Baseline set:

- Classical cosine top eight.
- Native BM25/dense reciprocal-rank fusion over the same candidate pool, k=60.
- Native MMR, using its independently development-tuned, frozen diversity weight.
- Greedy maximization of the encoded objective, with cosine final ordering.
- Independently computed vectorized exact quantized and exact float optimizers.
- Uniform random search, with an objective budget matched to
  `2 * GAS phase calls + measured candidate evaluations + initial incumbent`.
  This is a logical-access comparison; GAS's exhaustive classical simulator
  preparation remains charged separately in real CPU costs.
- GAS with five seeds.
- Cross-encoder MiniLM L2 and L6 on the matched fifteen candidates, returning
  eight in neural-score order; also report their top-64 pipeline variants.
- Legacy probability-based Grover reranking over the top-64 shortlist, truncated
  to eight. The new profile retunes its threshold on development nDCG@5 and
  times independent single-seed requests. Label that configuration explicitly;
  it is not the unchanged September nDCG@10 experiment.

## 6. Acceptance checks, statistics, and resource studies

- Require exact query/method/seed coverage; no duplicate IDs, invalid outputs,
  missing judgments, NaN scores, dropped timeouts, or best-seed reporting.
- Average stochastic metrics within query before inference. Seeds and shots
  are not independent observations.
- Primary quality: nDCG@5. Secondary: nDCG@8, Recall@5/@8, MRR@5/@8, P@5,
  embedding redundancy, encoded optimum hit rate/gap, and float-utility gap.
- Use paired query bootstrap confidence intervals (10,000 resamples, seed 0),
  paired sign-randomization tests (10,000, seed 1), and Holm correction for
  additional nDCG comparisons. Cross-check metric conventions with TREC/BEIR.
- Primary target passes only if the lower 95% bound of GAS-minus-MMR nDCG@5 is
  above -0.01 AND the upper 95% bound of GAS-minus-MMR redundancy is below zero.
  Report failed/inconclusive targets honestly. Passing MMR does not establish
  parity or superiority against the neural baselines.
- Report median/P95 from actual single-seed requests, with separate selector
  and retrieval totals. Do not divide aggregate five-seed P95 by five.
- Show query encoding/model loading/corpus encoding/index or lexical setup
  separately. Add query encoding when presenting online end-to-end latency.
- The code's `process_peak_rss_bytes` is a whole-process lifetime high-water
  mark. It is NOT an isolated per-method memory measurement. Run separate fresh
  worker processes for memory comparisons before using memory as an advantage.
- Measure CPU-seconds; do not invent monetary savings from operation counts.
  Any money/energy claim requires its own documented measurement/pricing model.
- Keep native-circuit and compact-simulator timing in separate tables.
- Study pool sizes {10, 12, 15, 20} with output size fixed at eight, so a pool-size
  experiment does not also change the output budget. Use 10/5 only as a separate
  small correctness/resource reference, not a causal quality comparator to 15/8.
- Study coefficient precision {2, 4, 6} and lambda=0 as declared ablations.
  Additional ablation runs must use frozen development choices and carry their
  own manifests. Do not select a favorable test configuration afterward.
- Treat lower embedding redundancy as a proxy, not demonstrated topic coverage,
  answer correctness, OCR quality, or user satisfaction.

## 7. Manuscript changes — only after validated results exist

Do not reuse the legacy table generator with new GAS artifacts without adapting
it. Tomorrow, add a generator that verifies the GAS schema/source/result hashes
and reads the new `scores.json` and `traces.jsonl`. Generate all numerical tables,
plots, and findings; do not type improved benchmark values into the manuscript.

Update `new_paper/main.tex` and its generated inputs as follows:

1. Abstract/introduction: state the evidence-selection question, the actual
   implementation and tested operating point, and findings supported by data.
   Distinguish applying an established GAS algorithm from inventing a new
   quantum optimization algorithm. Audit nearby primary literature.
2. Related work: add GAS, Dicke/state preparation where relevant, MMR, subset
   optimization, and neural reranking references; verify publication metadata.
3. Datasets: add FiQA, full corpus/split/query counts, checksums, representative
   passage policy, and candidate coverage at both 64 and 15. A larger corpus
   with a fixed 15-document quantum pool is not quantum corpus-size scaling.
4. Method: specify the set objective, quantization, feasible-subset state,
   incumbent oracle, adaptive iteration schedule, budgets, seed protocol,
   fallback/status handling, and final cosine ordering. Separate offline tuning
   from online selection; explain compact simulation and classical preparation.
5. Protocol: fully describe hardware/software, comparator ordering, matched and
   full-pipeline cases, timing boundaries, statistical families, and hypotheses.
6. Results: effectiveness/redundancy, neural comparisons, actual selector and
   retrieval latency, quantized/float gaps, timeout/budget counts, precision/pool
   studies, logical resources, and any properly measured isolated memory results.
7. Limitations: classical upstream retrieval, small selection pool, noiseless
   compact simulation, exhaustive simulator energy preparation, representation
   costs, quantization, dataset coverage, and no unsupported quantum speedup.
8. Conclusion: one paragraph of 150–200 words describing measured contributions,
   limitations, and the supported conclusion.
9. Figures/layout: cite every retained figure in text with sequential labels;
   remove invalid subfigure labels, replace peripheral interface screenshots
   when space is needed, and use readable IEEE floats without forced empty pages.
10. Metadata: keep accepted authors/order/title consistent with submission
    records, affiliations, bibliography, PDF metadata, and copyright paperwork.

Use the supplied IEEE template without shrinking margins or prescribed fonts.
Keep the final paper within eight pages including references, unless the
organizer explicitly supplies a different limit. Keep detailed traces/ablation
tables in a companion reproducibility report. Check applicable IEEE disclosure
requirements for retained AI-generated content.

## 8. Reviewer response and final delivery

Create a response covering every acceptance-letter comment:

| Comment | Evidence/change needed |
|---|---|
| Only two datasets | FiQA plus complete cross-domain test evaluation. |
| Classical dependence limits advantage | Honest pipeline/oracle accounting and scoped claims. |
| High Grover P95 | Direct per-seed measurements, timing boundaries, and explanation. |
| Incomplete hardware | Recorded CPU, RAM, software versions, and thread settings. |
| Missing advanced rerankers | Matched and top-64 L2/L6 neural results. |
| Figures uncited | Explicit sequential references and corrected labels. |
| Conclusion format | Single paragraph, 150–200 words. |
| Threshold/fallback sensitivity | Legacy development threshold study; adaptive GAS incumbent/status analysis. |
| Score transformation | Replace probability-as-relevance scoring with set selection and cosine final order; retain legacy comparison. |
| Candidate/precision resources | Pool/precision studies with real representation and oracle costs. |
| Additional classical methods | Fusion, MMR, greedy, random, and exact optimization comparisons. |
| Larger collections | FiQA evaluation and explicit limits of the fixed candidate pool. |

For each response, provide the actual change, supporting table/figure/run, and
final section/page reference. Do not mark an unresolved experiment as completed.

Final review: clean build, resolved citations/references, embedded fonts, readable
tables/plots, visual inspection of every page, and agreement between text and
sealed numerical artifacts. Deliver revised source/PDF, results/reproducibility
report, and reviewer response. PDF eXpress, copyright, presentation/registration,
and submission remain separate author actions; do not submit automatically.

## Fast synthetic regression checks

```bash
OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2 backend/.venv/bin/python \
  -m unittest research.test_selection -q

backend/.venv/bin/python -m research.selection_experiment --help
backend/.venv/bin/python -m research.run run --help
```

These unit checks use artificial arrays, mocked neural predictions, temporary
feature JSON, and small synthetic circuits. They load no corpus, qrels, trained
encoder, or cross-encoder weights. They do not establish publication readiness
or benchmark superiority. Future real-dataset behavior remains to be checked.
