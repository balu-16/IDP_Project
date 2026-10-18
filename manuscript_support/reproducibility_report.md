# Reproducibility and evidence boundaries

## Selected experiments

The central mapping is `paper_sources.json`. SciFact's full 300-query and NFCorpus's full 323-query tests use the protected-prefix constrained GAS extension. FiQA's full 648-query test uses base L6-guided GAS. The unified public method name identifies a family, not identical configurations. The FiQA 100-query training confirmation supplies no manuscript result.

Data comprise 5,183 / 3,633 / 57,638 parent documents and 13,505 / 9,970 / 92,391 dense chunks for SciFact / NFCorpus / FiQA. Base tuning uses 161 / 324 / 500 development queries. Features preserve raw cosine, raw logits, normalized relevance, and embeddings separately. All three models are pinned by immutable revisions and per-file hashes in the run identities.

The base pipeline is dense top64 → frozen hybrid top15 → original L6 inference → 8-bit GAS selecting eight → raw-L6 ordering. Frozen `(lexical weight, diversity penalty)` values are SciFact `(0.25, 0)`, NFCorpus `(0.5, 0.05)`, and FiQA `(0, 0.025)`. L6-MMR's independently selected diversity weight is zero on each dataset. The original cosine-guided GAS and legacy Grover controls have distinct policies and must not be conflated with these base settings.

The extension unions three hybrid top15 lists at lexical weights 0, .25, .5; retains original logits before scoring additional candidates; protects each baseline seed's first five IDs; and chooses the three-document tail under sorted raw-logit dominance. Its 16-bit pair objective includes all 28 selected pairs. Each stage has a separate 64-phase/32-trial budget, growth 1.2, cooperative 15-second limit, and seeds 0–4. Prefix preservation takes precedence over a global L6 sort.

## Provenance and verification

The exporter opens completed runs without entering collection sessions or changing any checkpoint. It checks current source/dependency/data identities, source snapshots, every sealed artifact hash, query IDs, method and seed coverage, original-logit preservation, cardinality, tail feasibility, improvements, and timing validity. Recorded model identities must agree between selected runs.

Independent metric definitions recompute nDCG@5/@8, Recall@8, and clipped-positive pair-cosine redundancy from every saved ranking. Every query/method mean and reported online/selector median/P95 is compared to the sealed evaluation. Optional final `--check-metrics` runs the existing NIST executable only on those saved rankings; no neural inference or selector is executed. The verification result and NIST executable hash are written outside experiment directories.

Development threshold evidence uses stored matched-sampling scores and saved raw cosine candidates. It does not construct new rankings. Threshold results are descriptive of the frozen development runs, not a new test-tuned configuration.

Paired inference averages seeds within query. Protected-run inference uses the recorded 10,000-query bootstrap/randomization draws and all 36 comparison/metric tests in each Holm family. Base-only FiQA uses its existing six-comparator nDCG audit with differences ≤1e-12 treated as ties. That audit is bound to the original results; experiment files are not rewritten to fix statistical reporting. Pointwise confidence intervals are not simultaneous intervals.

## Timing and hardware

The CPU is a 13th Gen Intel Core i7-1355U, 12 logical CPUs; recorded RAM is 16,461,398,016 bytes. OMP/MKL/OpenBLAS are configured to two threads. Linux, Python 3.12.3, full package versions, per-session load, restore time, and artificial-query warm-up are retained in `evidence.json` and source artifacts.

Composed online latency charges applicable query encoding, dense search, representative feature construction, Python BM25/lexical work, hybrid/union construction, original/additional L6 inference, baseline selection, and refinement. Shared upstream observations are attributed to each relevant pipeline. Model loading, corpus cache restore, and warm-up are separate. Combined selector percentiles are computed from per-request baseline-plus-refinement totals, not by summing medians or P95s. Refinement-only time is never called end-to-end time. Shared-host timing is not physical quantum runtime or proof of monetary/energy savings.

## Protocol exceptions and findings

All newer official-test evaluations are follow-up studies after earlier test results were observed. The initial deterministic training-confirmation rule required equal nDCG@5, Recall@8 at least 98% of matched base, and lower mean redundancy. NFCorpus confirmation lost 2.1561% relative recall and failed. An explicitly recorded continuation collected its full test without changing the method or global gate. Its eventual full-test result passing is not relabeled confirmation success. See `research/runs/accuracy_v3_redundancy_nfcorpus_continuation_protocol.json` and the test identity's embedded protocol and snapshot hashes.

SciFact refinement loses about 0.93% relative mean recall and reduces redundancy about 3.21%; NFCorpus gains about 1.95% relative mean recall and reduces redundancy about 2.63%. Prefix nDCG@5 is unchanged by construction. Some individual queries lose recall. Greedy and exact-float refiners match the aggregate quality on these two tests. These findings support constrained selection, not a uniquely Grover-derived improvement. FiQA base has the same reported nDCG/recall as its L6-only control.

The new full 648-query FiQA refinement follow-up completed and failed the
frozen gate: nDCG@5 remained unchanged, relative recall fell 2.601978%, and
redundancy fell 8.234319%. Its sealed results remain under
`research/runs/accuracy_v3_redundancy_fiqa_test/`; they were not retuned or mixed
into the older headline row. The resource protocol binds this follow-up's
manifest/evaluation hashes, and the paper discloses the failure.

## Resource analysis and outstanding work

Compact simulation exhaustively builds objective arrays before amplification and stores complex128 amplitudes over cardinality-feasible subsets. The controller receives neither optimum nor marked-state count. Recorded phase and reversible objective counts are distinct from simulator objective enumeration. The latter is real classical work; exact argmin can use it without amplification.

Observed primary refinement pools and times come from saved traces. The new
resource study freezes 32 confirmation queries per dataset, five search seeds,
six tail-pool sizes, and four pair precisions. All 178 tasks completed,
including 80 native synthesis cells; artificial 16/20-candidate stress cells
are labelled. Real pool availability is recorded per dataset/seed. Native
representatives are the first two eligible frozen seed-zero queries for each
dataset/pool, held identical across precisions.

The native oracle implements cardinality, three L6 threshold counts, signed
integer improvement, and compute/phase/uncompute. Its full logical width is
M+w+2c+3, where c=ceil(log2(M+1)) and w bounds the signed polynomial over all
bit strings. Every counter, comparator carry, and flag register is included.
The u/cx basis, optimization level 1, and seed 0 are fixed; counts assume
unrestricted connectivity. Complete-iteration synthesis includes generic
fixed-weight preparation/reflection for at most eight decisions.

Six native complete iterations passed phase-sensitive checks; 42 additional
simulation attempts were refused by the simulator's conservative memory
estimator. Limits remain 120 seconds and 2 GiB per circuit worker. Small native
verification also includes a nontrivial five-decision/two-bit toy instance.
MPS uses zero configurable truncation and bond cap 128; inverse independent
expected-state preparation and local Z expectations bound state infidelity
and workspace leakage by 1e-8. Larger native simulations are explicitly
unperformed. Construction/transpilation, native simulation, and compact
selection times remain separate. Per-method allocation profiling is a second
replay excluded from selector timings; process RSS covers the fresh query
worker's complete grid. Full data are in `resource_study_v1_final/`.

Complex128 amplitudes use 16*choose(M,3) bytes, excluding energies/layouts and
process memory. NumPy integer widths are fixed. The quantization proof bounds
an exact quantized minimizer on the same domain; it does not imply each GAS
request is globally optimal. `records/resource_hardware.json` records the host
during collection and is bound into manuscript provenance.

There is no physical-device routing/noise sweep, QPU run, energy/money
measurement, comprehensive modern-reranker comparison, or generated-answer
evaluation. Larger complete-iteration preparation and simulation remain
unperformed. The older-objective circuit helper was not used to stand in for
the new constrained oracle. The 98% mean recall gate is not a statistical
noninferiority proof. These limits remain in the paper and reviewer response.

## Build and replacement

See `README.md` for exact regeneration/build commands and the one-directory FiQA replacement procedure. The prior LaTeX and working notes were backed up under `build/paper_revision_before/`; historical experiment sources/results remain untouched. The supplied IEEEtran class is copied unchanged. The local checker verifies page count, embedded fonts, citations/references, figure/table use, and arithmetic claims. Page images must be inspected before delivery, and organizer/PDF eXpress validation remains an external author action.
