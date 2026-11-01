# Proposal for a second journal paper: quantum circuit design and resource evaluation

**Status: faculty-review plan only.** Quantum Information Processing is the proposed venue, pending faculty confirmation. No quantum manuscript, new circuit implementation, or experiment has been created or run for this proposal. The existing application, conference manuscript, IEEE Access draft and saved experiments remain unchanged by the proposed research.

Working title: **Predicate-Aware Reversible Oracles for Constrained Fixed-Cardinality Grover Search**.

## 1. The idea in simple terms

The application already retrieves and scores documents. Its selector then chooses a three-document tail while preserving five earlier results. The existing resource study describes quantum circuits that could check whether a candidate tail meets the constraints and improves the encoded objective.

The proposed paper studies **how to perform that same check with a different circuit**. We would try to remove redundant checks and unnecessary workspace, then measure the resulting qubits, gates and circuit depth. The old and new circuits must mark exactly the same candidate subsets. A change in which subsets are accepted is a correctness failure, not an accuracy improvement.

The new measurements would run on a classical computer using circuit synthesis and bounded quantum simulation. They would use features already saved from SciFact, NFCorpus and FiQA. They would not require a fourth dataset, fresh embeddings, new language-model inference, new retrieval rankings, or changes to the running application. Fewer qubits would not by itself establish faster execution on a physical quantum computer.

## 2. Proposed venue and publication distinction

Target: **Springer Nature, Quantum Information Processing (QIP), Regular Article**. Its [aims and scope](https://link.springer.com/journal/11128/aims-and-scope) include quantum algorithms and quantum computer science. A paper centered on a reversible oracle, correctness arguments and measured circuit resources is a plausible fit; acceptance and scientific novelty are not established by that fit.

The two papers would address different questions:

| Work | Main question | Status of evidence |
| --- | --- | --- |
| Accepted conference manuscript | How does the Grover-inspired retrieval policy behave, and what are its bounded implementation resources? | Existing prior work, including the native resource study |
| IEEE Access manuscript in `../ieee/` | What do candidate coverage, query-level failures, seed stability and complete request costs reveal about the completed retrieval experiments? | Existing manuscript and secondary analyses |
| Proposed QIP paper | Can an equivalent constraint oracle use fewer resources, and what tradeoffs remain after complete circuit accounting? | New design, proofs and experiments proposed here; no new findings yet |

The existing resource study is a **reference implementation**, not a new QIP contribution. The new paper must explicitly distinguish its new construction, proof and paired measurements from both earlier manuscripts. It must not reproduce the old resource figures and present them as a new experiment. The IEEE manuscript does not need to lose its existing resource discussion for this proposal to proceed.

Before claiming originality, compare the proposed construction with primary work on constrained Grover search, modular population counters, reversible predicates, comparators, Boolean phase oracles and fixed-weight search. If the design is already known, identify a defensible new contribution with the faculty or revise the proposal. A new title or longer exposition is insufficient.

## 3. Research questions and proposed contributions

1. **Correctness:** Can the optimized oracle implement the identical marking predicate on every decision bit string and return all workspace to zero?
2. **Resource accounting:** How do explicit qubits, oracle CX count and depth change at the same input, precision and synthesis configuration?
3. **Complete iteration:** How much of an oracle saving remains when the same state preparation, reflection and uncomputation are included?
4. **Practical limits:** Which circuits can actually be validated within the fixed CPU, memory and time limits, and where do resource refusals remain?

Candidate contributions are a specialized oracle construction, an all-input correctness argument, explicit register accounting, paired resource measurements and a reproducible implementation. These are research objectives. Numerical savings, asymptotic improvements and novelty remain unverified until the study is completed and compared with the literature.

## 4. Existing implementation and sources of truth

Read the following project sources without modifying them:

- `research/resource_study_v1/circuits.py`: the current counter, native oracle, complete iteration, synthesis and small-circuit validation.
- `research/resource_study_v1/problem.py`: objective coefficients, the incumbent, threshold groups and safe signed width.
- `research/runs/resource_study_v1_final/`: sealed protocol, task list, saved inputs, results and native-resource report.
- `manuscript_support/paper_sources.json`: the selected retrieval/resource mappings.

The completed resource study contains 80 native cells, four pair-coefficient precisions (4, 8, 12 and 16 bits), and requested tail-pool sizes 3, 5, 8, 12, 16 and 20. Availability varies by dataset. Pools of 16 and 20 in this native matrix are explicitly synthetic stress cases, not additional retrieval datasets. The earlier study recorded six validated complete iterations and 42 simulation attempts refused by its memory guard. Those are historical observations, not outcomes of the proposed designs.

Keep the failed FiQA refinement and other original outcomes intact. The new study changes circuit implementation for frozen inputs, not retrieval tuning or the scientific interpretation of prior tests.

## 5. Proposed circuit designs

### 5.1 Shared marking predicate

Let `x` be an `M`-bit decision string and `S(x)` its selected tail candidates. The tail has size three. Let `theta_1 <= theta_2 <= theta_3` be the sorted original-tail score thresholds, with the existing numerical tolerance already incorporated. Define the nested groups

```text
G_j = {i : saved_logit_i >= theta_j},  j = 1, 2, 3.
```

Every retained candidate must belong to `G_1`, as a consequence of the existing prefilter. Verify that assumption from the actual frozen input before constructing an optimized circuit. Do not remove a constraint if its premise fails.

The oracle marks a state if and only if:

```text
|S(x)| = 3
|S(x) intersect G_1| >= 3
|S(x) intersect G_2| >= 2
|S(x) intersect G_3| >= 1
integer_energy(x) < incumbent_energy
```

Reuse exactly the original rounded coefficients, incumbent and saved scores. Keep the signed objective register large enough for **all decision bit strings**, including invalid-cardinality states. Do not shrink it using only the valid three-element subsets.

### 5.2 Three variants for a controlled comparison

| Variant | Construction | Purpose |
| --- | --- | --- |
| P0: reference | Current four-flag oracle, shared full-width counter and comparator workspace | Establish correctness and resource parity with the sealed reference |
| P1: redundancy ablation | Remove only the `G_1` threshold test after verifying prefilter membership; preserve cardinality, remaining comparators and arithmetic | Isolate the effect of removing the redundant test |
| P2: proposed oracle | Retain full cardinality checking; replace the `G_2` comparison by a two-bit modulo-four count and the `G_3` comparison by a Boolean OR; remove comparator workspace | Evaluate a further equivalent implementation |

For P2, a globally valid state selects exactly three candidates, so its selected count inside `G_2` lies in `[0,3]`. A two-bit modulo-four counter is therefore exact on that branch, and its high bit identifies counts two or three. Outside that branch the cardinality flag prevents marking, even if a modular count wraps. Nonemptiness in `G_3` can be computed as an OR using a complemented all-zero test, without a population-count comparator. Explicitly handle the gate construction and uncompute each temporary value.

Do not substitute a saturated counter that discards information without accounting for reversibility. Do not silently restrict correctness to the prepared fixed-weight subspace: the core proposal retains a correct all-bitstring oracle.

### 5.3 Register-accounting targets to prove

Write `c = ceil(log2(M+1))` and let `w` be the unchanged safe signed objective width. Under the stated register layout and an ancilla-free decomposition of the multi-controlled gates, the proposed accounting is:

```text
P0: M + w + 2c + 3
P1: M + w + 2c + 2
P2: M + w + c + 3
```

These are construction targets to verify, not measured results. Count any extra ancillas introduced by actual gate decomposition and revise the totals if needed. A predicted register saving does not establish a CX, depth or runtime improvement; the direct OR may introduce an expensive multi-controlled gate. Report tradeoffs and adverse outcomes.

State preparation and diffusion remain identical across variants. The initial study does not propose a new Dicke-state preparation algorithm or claim a new amplitude-amplification schedule.

## 6. Correctness work before measurement

The mathematical treatment should establish:

1. The equivalence of sorted-score dominance and the threshold-count predicate.
2. Redundancy of the first threshold test under verified prefilter membership and cardinality three.
3. Correctness of the modular count and direct OR after conjunction with the cardinality flag, including invalid bit strings.
4. Preservation of the original strict integer-improvement predicate and safe signed arithmetic.
5. Clean uncomputation and the intended phase action for arbitrary superpositions of decision strings with zero-initialized workspace.
6. The exact register requirements of each implemented circuit.

Items already established in the conference paper must be cited as background. The new proof should focus on the changed circuit and its equivalence, rather than relabeling an old metric or quantization guarantee as new.

Use an independent classical predicate based on sorted saved logits and an explicit pair-energy sum; do not validate the circuit only against another implementation of its own counter logic.

Proposed checks include exhaustive classical enumeration for small decision spaces; repeated scores and tolerance boundaries; strict energy ties; empty marked sets; signed-range boundaries; invalid cardinalities; and clean workspace. Validate phase action on coherent superpositions, not only output probabilities. Separate two-bit toy circuits can test nontrivial marking when larger real circuits exceed simulation limits.

## 7. Proposed experimental protocol — pending faculty approval

### Inputs and comparison matrix

- Reuse the **same 80 saved native cells**, retaining their exact parent-input, pool, query, precision and synthetic labels.
- Construct P0, P1 and P2 for each cell: **240 proposed paired worker tasks**. Do not replace unavailable real pools with fabricated real examples.
- Run a small, preregistered 18-task pilot (six cells across the three variants) first. Choose those cells and their source hashes before measurement; include both real and synthetic cases and more than one precision. Reuse successful pilot tasks in the full matrix rather than collecting them twice.
- Freeze all input hashes, source/dependency versions, variant definitions, task order and analysis rules before measurement. Do not select cases after seeing which design performs best.

### Environment and resource limits

Use the existing pinned Qiskit 0.46.0, Aer 0.13.3 and NumPy 1.26.4 environment if it still matches the saved identities. Any necessary dependency change requires a separately recorded environment within the quantum artifact; do not alter the application environment.

Proposed defaults are one worker at a time, two CPU threads, a 2 GiB process address-space limit and a 120-second limit per task. The 240-task timeout ceiling is approximately eight worker-hours, excluding preparation and reporting; it is not a predicted runtime. Use the pilot to estimate actual completion time and obtain faculty confirmation of the full run budget.

Synthesize into unrestricted logical `u/cx`, optimization level one and transpiler seed zero, matching the reference boundary. Record oracle-only and complete-iteration counts separately. Complete-iteration synthesis remains limited to `M <= 8`, and native validation remains limited to `M <= 5` for this first study. Larger cells provide synthesis evidence only.

For native validation retain the prior noiseless MPS configuration: zero configurable truncation threshold, maximum bond dimension 128 and acceptance tolerance `1e-8`. Preserve simulator refusals, timeouts and failed validations as separate outcomes. Do not relax the memory guard to obtain a favorable completion rate.

### Measurements and analysis

Record logical qubits by register, CX count, total gates, depth, construction time, transpilation time, validation time, peak process RSS and task status. Record preparation/reflection costs separately from the oracle. If timing is a substantive comparison, predeclare three timed repetitions within the same bounded worker and report their median; repeated timings are not independent problem instances.

Compare variants on identical input/precision cells. Report paired absolute differences and ratios, with explicit denominators for completed pairs. Show the full availability/status matrix so that completion failures do not disappear from averages. Keep real and synthetic summaries separate. Coefficient precisions from one query are related observations, not independent evidence for a significance claim. Qubit and gate counts are deterministic synthesis measurements; a p-value is not automatically required for them.

The first study includes no new retrieval-effectiveness benchmark, physical-device run, noise sweep, routing model, energy measurement or monetary comparison. Such extensions would require a separately defined study and approval. No end-to-end application-speedup claim follows from the proposed measurements.

## 8. Suggested paper structure and figures

1. **Introduction:** fixed-cardinality constraint checking, resource motivation, precise research questions and relationship to previous work.
2. **Related work:** Grover adaptive search, reversible arithmetic, cardinality/threshold predicates, phase oracles and resource-estimation practice.
3. **Problem and reference oracle:** frozen objective, score constraints, access assumptions and the full correctness domain.
4. **Circuit construction and correctness:** P1/P2 derivations, register diagrams, uncomputation and proofs.
5. **Experimental protocol:** frozen cells, environment, synthesis settings, controls, validation and resource limits.
6. **Results and ablations:** complete measured comparison, effects of precision and pool size, complete-iteration accounting and failed/limited cases.
7. **Discussion and limitations:** tradeoffs, related-work distinction, sampling limitations and what synthesis cannot establish about hardware.
8. **Conclusion, declarations and reproducibility:** only conclusions supported by completed measurements and verified proofs.

Proposed figures are the three oracle layouts, qubits versus pool size/precision, paired CX/depth comparisons, and validation/resource-limit coverage. Proposed tables cover predicate equivalence, register accounting, input availability, the measured paired matrix and explicit failure statuses. Produce plots from sealed exports, without illustrative invented result values. Use one vector figure format per figure and retain only the required final deliverables after verification.

The final abstract and contribution list should be written after results are available. Do not create a results-bearing abstract or a publication-ready PDF from this plan alone.

## 9. Literature and journal-format preparation

Use the [official QIP submission instructions](https://link.springer.com/journal/11128/submission-guidelines) and their linked Springer Nature LaTeX template after the venue is confirmed. Use the supplied class and numerical citation style rather than restyling the IEEE manuscript.

Three relevant published QIP exemplars to examine in full are:

- Alonso et al., **Multi-Unary: a dense input encoding scheme for the quantum circuit model** (2026), [DOI 10.1007/s11128-026-05316-9](https://link.springer.com/article/10.1007/s11128-026-05316-9). Relevant to encoding, counters and resource-oriented oracle presentation; it is not a locally evaluated baseline.
- Choi et al., **Precision-aware fixed-point emulation of Grover's algorithm: asymptotic error bounds and design guidelines** (2026), [DOI 10.1007/s11128-026-05235-9](https://link.springer.com/article/10.1007/s11128-026-05235-9). Relevant to separating a defined arithmetic model from broader hardware claims; its emulator precision problem differs from coefficient quantization here.
- Guţoiu, Tănăsescu and Popescu, **Simple exact quantum search** (2024), [DOI 10.1007/s11128-024-04548-x](https://link.springer.com/article/10.1007/s11128-024-04548-x). Relevant to stating access assumptions and proving exactly what changes in an oracle/diffuser construction.

Inspect two to three actual PDFs for author layout, proof structure, captions, equations and references before authoring. The current QIP instructions contain both an 80–100-word abstract statement and a generic 150–250-word statement. Record that conflict and resolve the applicable requirement with the faculty/editor before finalizing the abstract; do not silently assert that either range has been confirmed. Both sections request four to six keywords.

Use verified author and affiliation details only. Obtain author-contribution, funding and competing-interest statements from the authors. Follow the current Springer disclosure requirements for generative drafting/code assistance; do not invent declarations or author approval. Cite the accepted conference manuscript with its real publication status and describe the relationship to the IEEE draft accurately, including its submission/publication status at the time.

## 10. Reproducibility and future file organization

If the faculty confirms this study, keep all new sources, frozen inputs, protocols, checkpoints, logs, results, analysis and paper assets under `journal/quantum/`. Read the original project sources and sealed runs without changing them. Avoid invoking old experiment commands whose default outputs write into `research/runs/`.

The later implementation should provide a frozen task manifest, atomic per-task commits, checksum-verified resume, complete failure accounting, machine-readable exports and figures generated from those exports. It should reject incompatible sources or corrupt completed results rather than delete or overwrite them. Keep temporary tools/caches inside the quantum artifact and clean them after successful validation.

Once results support a distinct paper, deliver its own LaTeX, bibliography, vector figures, official template, source ZIP, final PDF and verification notes. Audit citations and every numerical claim, compile without unresolved diagnostics, and inspect every final page. Keep the existing IEEE artifact independent and unchanged.

## 11. Faculty decision and proposed sequence

Present this plan to the faculty before new circuit development or experiment collection. Confirm the QIP venue, whether the proposed construction/analysis is a sufficient distinct contribution, author responsibilities, experiment scope and compute budget. If the contribution needs strengthening, revise the plan before collecting the full matrix.

After that confirmation, the proposed order is:

1. Complete the focused literature/novelty comparison and freeze the exact scope.
2. Specify the circuits and complete the correctness/register reasoning.
3. Implement isolated variants and independent small-instance checks.
4. Freeze inputs and protocol; complete the bounded pilot and estimate the full-run budget.
5. Collect the approved paired matrix, preserving unsuccessful outcomes.
6. Verify exports and analyze all completed/limited cases.
7. Write the paper around the actual findings; compile, inspect and review it with the authors.

If correctness, distinctness or adequate evidence cannot be established, retain the honest feasibility/gap report rather than label an incomplete proposal a finished QIP article. **The current authorized deliverable ends with this plan.**
