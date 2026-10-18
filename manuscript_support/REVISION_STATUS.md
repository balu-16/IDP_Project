# Manuscript revision status — 18 October 2026

The complete LaTeX revision and compiled **eight-page PDF** include the measured
constrained-oracle resource study. `before_resource_revision.zip` preserves
the preceding checked PDF, source, fragments, and evidence. Nothing has been
submitted externally.


## Latest editorial revision

The current paper has **32 references**, with all 14 additions verified against
publisher or author records and cited beside relevant statements. The original
18 entries remain intact and every entry follows first-citation order. The
acknowledgement section has been removed from all current upload artifacts.

Only supporting literature, repeated explanatory prose, captions, and layout
were revised. Every generated LaTeX fragment, numerical result, and method/proof
source is unchanged from the preceding checked manuscript. Recall reductions
remain disclosed on **page 4, Section V-A**, and **page 6, Table IV and the
conclusion**.

The complete PDF remains eight pages, with a 189-word abstract and one 150-word
conclusion. All eight final page renderings were inspected. Fresh standalone
compilation, embedded fonts, citation numbering, absence of overflow, and the
portable ZIP's exact source coverage passed. No dataset evaluation, selector,
or model inference was run for this revision.

Current layout audit: records/paragraph_spacing_checks.json.
Earlier content audit: records/bibliography_revision_checks.json.
The page-6 paragraph gaps now use natural spacing; the text is unchanged.
Source verification: records/bibliography_sources.json.
Previous checked upload: before_bibliography_revision.zip.

## Effectiveness evidence

The public method name remains **L6-guided GAS** on every dataset. The headline
note and methods explain that SciFact/NFCorpus use protected-prefix refinement
while FiQA uses its earlier configuration. Every metric within a result row
comes from the same recorded policy and query set.

| Dataset | Full-test queries | nDCG@5 | Recall@8 | Redundancy |
|---|---:|---:|---:|---:|
| SciFact | 300 | 0.687833 | 0.801111 | 0.433636 |
| NFCorpus | 323 | 0.368865 | 0.152997 | 0.431771 |
| FiQA | 648 | 0.357490 | 0.434063 | 0.531244 |

The additional 648-query FiQA refinement test is now complete and **failed the
frozen recall gate**: nDCG@5 was unchanged, recall decreased **2.601978%**
relative, and redundancy decreased **8.234319%**. The paper discloses this
follow-up separately; it does not combine the new redundancy with the older
recall. Its 100-query confirmation values are not headline test results. No
retuning against test judgments was performed.

## New measured resources

The independent `research/resource_study_v1/` package reads saved confirmation
features. It ran after FiQA and the queued application checks finished, without
re-encoding a corpus, model inference, or changing the earlier experiments.

- **178/178 tasks completed**, including **80 native synthesis cells**.
- Frozen real sample: **32 queries per dataset**, five compact-search seeds,
  six tail-pool sizes, four pair precisions, and 64-phase/32-trial budgets.
  Pool availability and unavailable cells are explicit; artificial 16/20-tail
  stress instances are labelled.
- The new native oracle implements cardinality, three L6-score constraints,
  signed integer improvement, and compute–phase–uncompute. Widths prevent sign
  overflow over every bit string; all workspace registers are counted.
- Pinned Qiskit/Aer, unrestricted `u/cx`, optimization level 1, transpiler seed
  0, and **120-second / 2-GiB** circuit-worker limits are retained.
- Complete-iteration synthesis covers up to eight decisions. **Six native
  complete iterations validated; 42 further simulation attempts were refused
  by the memory guard.** Native validation simulation covers up to five
  decisions; independent two-bit toy tests include nontrivial phase marking.
- Compact selection, allocation-profile replay, whole-worker RSS, construction,
  transpilation, and native simulation have distinct measurement boundaries.
  Exact-float and exact-quantized objective gaps are saved with search counts
  and termination reasons.

The compact measured table replaces the analytical-only table. The reviewer
response calls this **bounded measured coverage**, without implying a complete
physical-device or large-native-simulation study.

## Completed verification

- Four resource test groups passed: independent objective/constraints, safe
  widths and baseline-preserving pools, native phase/reflection/norm/workspace,
  and interrupted synthetic execution/recovery with corruption rejection.
- All resource tasks, frozen identities/inputs, report files, and manifests
  passed provenance and coverage checks. Sources and dependency pins from the
  earlier experiments remain unchanged.
- The manuscript exporter reverified the selected complete test/development
  runs and independently recomputed **119,124 saved query/method metric
  values**, including nDCG@5/@8, Recall@8, and redundancy. It generated no
  benchmark rankings or neural inference.
- Earlier NIST `trec_eval` verification of **145,290 existing-ranking metric
  values** remains historical evidence bound to the corresponding runs; it
  is not represented as a new native-resource check.
- Checked 1,233 sorted-score/count cases, 180 quantization/regret cases, prefix
  invariance, a recall counterexample, and phase/reflection identity.
- The supplied IEEEtran class is unchanged. The complete PDF has **eight pages
  including references**, a 189-word abstract, and one **150-word conclusion**.
  Fonts are embedded, with no Type 3 fonts, unresolved references, or overfull
  boxes. All eight final page renderings were inspected directly.
- A fresh standalone copy of the cleaned upload folder compiled without Python
  or JSON inputs. Its extracted PDF text matches the delivered PDF; the source
  ZIP exactly matches the upload inputs and passes archive integrity checks.

## Delivered files

- `../new_paper/main.tex`, `main.pdf`, `IEEEtran.cls`, `README.md`, and required
  `includes/*.tex` only.
- `latex_source.zip`: portable Overleaf source archive.
- `paper_sources.json`, `export_verified_results.py`, `resource_integration.py`,
  and `build_manuscript.py`: central mapping, verified import, and build tools.
- `reviewer_response.md`: all twelve acceptance-letter technical comments,
  compiled locations, resource coverage, and scientific exceptions.
- `records/evidence.json`, `provenance.json`, `all_methods.csv`,
  `resource_hardware.json`, `publication_checks.json`, `visual_inspection.json`,
  `resource_standalone_check.json`, and `resource_final_audit.json`.
- `../research/runs/resource_study_v1_final/`: complete protocol, inputs,
  source snapshot, checkpoint results, CSV/JSON summaries, logs, and report.
- `README.md`, `RESUME.md`, and `../plan.md`: commands, status, and recovery.
- `history.zip` and the earlier engineering resource pilot remain preserved.

## Remaining limitations and author actions

Larger native complete-iteration preparation/simulation, device routing/noise,
QPU execution, energy/money measurement, comprehensive modern-reranker
comparisons, and generated-answer experiments remain unperformed. The paper
retains SciFact's recall loss, NFCorpus's failed confirmation and explicit
continuation exception, FiQA's failed full-test refinement gate, test reuse,
classical-control agreement, and increased complete pipeline cost. No uniquely
Grover-derived speed, cost, or effectiveness advantage is established.

Local formatting checks do not replace organizer/PDF eXpress validation or
final author review. No dataset or resource collection remains running.
