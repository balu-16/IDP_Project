# Constrained GAS resource study

This is a separate, versioned study for technical comment 2.3. It reads saved
confirmation features and results; it never loads a language model, builds
corpus embeddings, retrieves documents, or tunes production parameters.

Run from the repository root with the existing backend environment:

    backend/.venv/bin/python -m research.resource_study_v1 check
    backend/.venv/bin/python -m research.resource_study_v1 freeze
    backend/.venv/bin/python -m research.resource_study_v1 pilot
    backend/.venv/bin/python -m research.resource_study_v1 run --background

Use run --resume --background after interruption. Use status to read execution
state and report to verify/recreate summaries from completed checkpoints.
All commands accept --directory for a separate study namespace. Changed
sources or dependencies require a new namespace or the recorded source snapshot.
Do not delete completed checkpoints to bypass a resume rejection.

The default output is research/runs/resource_study_v1_final/. The earlier
resource_study_v1/ directory preserves an engineering pilot whose native
high-precision simulation was refused by the pinned simulator's memory
estimator. It is not silently relabelled as the completed study.
The final study contains:

- protocol.json, verification.json, source_snapshot/: frozen IDs, parameters,
  prerequisite outcomes, dependencies, and source identities before measurement.
- inputs/, frozen_inputs.json, tasks.json: immutable features, baseline seeds,
  real-pool coverage, two deterministic native representatives per dataset/pool,
  and explicitly labelled artificial stress cases for missing sampled sizes.
- requests/, pending/, results/, logs/: atomic tasks and complete worker logs.
- execution.json, supervisor.pid, supervisor.log: detached-process/session state.
- manifest.json, summary.json, REPORT.md, native_resources.csv, resource_table.tex:
  coverage verification and complete outcome records.

The compact engine runs 32 fixed training-confirmation queries per dataset,
all five baseline/search seeds, pool sizes 3/5/8/12/16/20 where available, and
4/8/12/16-bit coefficients. Each pool retains the baseline tail. GAS, exact
float, and exact quantized selection use the same features and constraints.
Allocation profiling is a separate replay, excluded from selector timing.
RSS is the whole fresh query worker's high-water mark, not isolated method RSS.

The new native oracle computes the fixed-head pair constant, head-tail linear
terms, tail-tail quadratic terms, exact cardinality, and all three L6 threshold
counts. A signed improvement flag controls phase marking; all value, count,
comparison, and flag workspace is uncomputed. Arithmetic bounds include all
bit strings, so invalid-cardinality states cannot cause unnoticed sign overflow.
Float-redundancy acceptance guards remain classical controller work.

Circuit statistics use unrestricted logical u/cx synthesis, optimization level
1, seed 0, and the pinned Qiskit/Aer versions. Native cells have 120-second and
2-GiB address-space limits; limited outcomes are preserved rather than omitted.
Complete-iteration synthesis includes generic fixed-weight preparation and
reflection only for at most eight decisions. Simulation validates at most five
decisions with noiseless MPS, a bond cap of 128, and zero configurable truncation.
Inverse independently expected-state preparation and local Z expectations
bound phase-sensitive infidelity and workspace leakage by 1e-8.
The simulator's conservative memory refusals remain explicit outcomes; the
two-GiB OS address-space limit is never relaxed. Small-state checks do not establish large-QPU
scaling, and no physical routing, noise, energy, or monetary advantage is claimed.

The existing older-objective circuit helper is not used for native resources.
FiQA's failed full-test recall gate remains failed. This resource-only study
does not authorize retuning or replace headline effectiveness results.
