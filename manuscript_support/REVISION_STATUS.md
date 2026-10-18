# Manuscript revision status

The complete LaTeX revision and compiled **eight-page PDF** are ready for author review. This status supersedes the earlier paused cosine-GAS manuscript notes, which were backed up under `build/paper_revision_before/`.

## Delivered evidence

The public method name is **L6-guided GAS** on every dataset. One headline-table note and the methods explain that SciFact and NFCorpus include protected-prefix refinement while FiQA uses the earlier configuration. All metrics within each result row come from that same recorded policy and query set.

| Dataset | Full-test queries | nDCG@5 | Recall@8 | Redundancy |
|---|---:|---:|---:|---:|
| SciFact | 300 | 0.687833 | 0.801111 | 0.433636 |
| NFCorpus | 323 | 0.368865 | 0.152997 | 0.431771 |
| FiQA | 648 | 0.357490 | 0.434063 | 0.531244 |

FiQA's 100-query training confirmation is excluded. No dataset collection, model inference, or selector execution was started for the manuscript revision. Frozen experimental sources, caches, and sealed result directories were preserved.

## Completed checks

- Selected complete test runs and their development sources passed identity, provenance, artifact, query, method, and seed checks.
- Independently recomputed **119,124 query/method metric values** from existing rankings, including nDCG@5/@8, Recall@8, and embedding redundancy; all matched recorded values.
- NIST `trec_eval` independently checked **145,290 existing-ranking metric values**. This checked saved rankings without generating new ones.
- Verified recorded timing aggregates and used complete paired-statistics correction families, including the numerical-tie-corrected FiQA audit.
- Checked 1,233 sorted-score/count-constraint cases, 180 quantization/regret cases, prefix invariance, a recall-loss counterexample, and a phase/reflection identity.
- Built with the supplied IEEEtran class unchanged. The PDF has eight pages, a 189-word abstract, and one 172-word conclusion paragraph. All fonts are embedded; there are no Type 3 fonts, unresolved references, or overfull boxes.
- Visually inspected all eight rendered pages, including tables, equations, diagram, metadata, margins, citations, and the balanced references page. Remaining underfull-box messages concern line justification and do not indicate clipping or overflow.

## Delivery files and future update

- `../new_paper/main.tex`, `../new_paper/main.pdf`, and supplied `../new_paper/IEEEtran.cls`.
- `latex_source.zip`: verified portable Overleaf source with all required generated LaTeX inputs.
- `paper_sources.json`, `export_verified_results.py`, and `build_manuscript.py`.
- `../new_paper/includes/`: required LaTeX fragments only.
- `records/`: complete methods CSV, evidence JSON, provenance hashes, and cleanup/standalone-build checks.
- `reviewer_response.md`: all twelve acceptance-letter comments, with compiled locations and explicit partial coverage of the native circuit-depth request.
- `reproducibility_report.md`, `records/publication_checks.json`, and `records/visual_inspection.json`.
- `README.md` and `RESUME.md`: exact build commands and the later one-directory replacement for a completed full FiQA refinement test.
- `history.zip`: the checksum-verified original upload-folder snapshot, preserving obsolete scripts, notes, tables, and figures.

Folder cleanup did not change the manuscript's wording, numerical fragments,
authors, or formatting. The cleaned folder compiled in isolation with no Python
or JSON inputs. Extracted text and all eight page renderings were identical to
the preceding inspected PDF. Administrative outputs remain outside `new_paper/`.

## Remaining scientific and publication limitations

The full new FiQA refinement test and full native constrained-oracle circuit-depth/precision study are not completed. The paper reports these limits. It retains SciFact's recall loss, NFCorpus's failed confirmation gate and explicit continuation exception, test reuse, matched classical agreement, and the increased complete pipeline cost. No uniquely Grover-derived speed, cost, or effectiveness advantage is established.

The response addresses the acceptance comments with available evidence; the circuit-depth request is **partially addressed**, not claimed complete. Local formatting checks and author review do not substitute for organizer/PDF eXpress validation. Nothing has been submitted externally. Dataset evaluations remain paused until a later user instruction.
