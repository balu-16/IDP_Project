# Manuscript prose revision

> Historical record: this log describes the preceding revision. The current manuscript and its verification are documented in `AUTHOR_VOICE_CHANGELOG.md`.

The revision starts from Git commit `1f8e65ae3547682e2cddda8ec2dc7e9ae664b8c2`. It changes the article's prose while retaining the recorded experiments and the disclosure of AI assistance. No new experiment, numerical result, reference, or unsupported claim was added.

The two supplied Turnitin reports are **AI-writing reports**, not source-similarity reports. The report for the current baseline shows 77%; the earlier draft's report shows 76%. Neither identifies matching sources. A new report is needed to establish any similarity or AI-writing score for the revised PDF.

## Section changes

The percentages estimate the share of original editable sentences without an exact normalized match after revision. They exclude protected equations, tables, figures, propositions, and proof environments. Sentence splitting is approximate; these percentages measure editing, not plagiarism, originality, or AI detection.

| Section | Approximate sentences changed | Main changes |
|---|---:|---|
| Abstract | 100% | Reframed the evidence-budget problem, findings, and limits in a shorter narrative. |
| Introduction | 100% | Clarified the selection problem, conference extension, reported configurations, and scope of the claims. |
| Related Work | 100% | Grouped retrieval, set-selection, and quantum-search literature by their role; rewrote the paragraph previously identical to the conference manuscript. |
| Problem Formulation and System Boundaries | 95% | Clarified parent-versus-passage judgments, candidate ceilings, and simulation boundaries. |
| Relevance-Guided Subset Search | 85% | Reorganized the prose around fusion, objective encoding, refinement, guarantees, and controller costs. |
| Data and Experimental Protocol | 97% | Reframed collection selection, passage construction, controls, tuning, inference, and timing. |
| Recorded Retrieval Results | 100% | Clarified dataset-specific outcomes, matched controls, uncertainty, and latency. |
| Coverage, Failure, and Cost Diagnostics | 94% | Reworked explanations of candidate opportunity, query-level losses, seed variation, and request costs. |
| Resource Study and Precision Sensitivity | 94% | Clarified simulator boundaries, reversible resources, precision, and validation limits. |
| Discussion, Limitations, and Reproducibility | 98% | Reorganized the interpretation, limitations, reproducibility, and future work. |
| Conclusion | 100% | Restated the supported findings and limits without adding claims. |
| Appendix A | 86% | Reworded the explanations around unchanged quantization and constraint calculations. |
| Appendix B | 93% | Clarified validation and reporting conventions around unchanged calculations. |

## Remaining source and citation review

- The local comparison with the accepted conference paper still finds shared technical material, particularly the method and control lists in `sections/protocol.tex`, parts of the amplitude-amplification procedure in `sections/method.tex`, numerical tables, and the common author affiliation. The named methods, values, and protected tables are retained. This comparison covers only the local conference paper and is not a publisher similarity score.
- A separate ten-token comparison of approximate LaTeX prose, excluding protected environments, inline math, citations, and commands, fell from 118 of 8,628 tokens (1.37%) to 95 of 8,048 tokens (1.18%). It compares only the conference manuscript and cannot predict Turnitin results.
- In the separate PDF-body ten-token diagnostic, shared tokens fell from 723 of 12,729 to 699 of 12,142, while their share rose from 5.68% to 5.76% as the body became shorter. It includes tables, equations, and headers; it does not establish an improvement in Turnitin or any other similarity score.
- Dataset and model descriptions in the protocol rely on citations already present in Related Work, rather than repeating them beside every description. Authors should check whether the target journal wants citations repeated locally. The existing citation commands and bibliography were kept unchanged as requested.
- The acknowledgment identifies Codex assistance, but the current bibliography has no Codex entry. `AUTHOR_REVIEW.md` already flags the publisher's AI-disclosure/citation requirement for author review. Adding a citation would require changing the protected citations and bibliography.
- No source-match report was supplied, so other potentially close passages cannot be identified or ruled out from these reports. Authors should inspect an actual source-similarity report and confirm the final manuscript before submission.

## Verification

- The revised PDF has 19 pages. The abstract has 225 words; all 52 bibliography entries are cited. The complete pdfLaTeX/BibTeX build reports no warnings, unresolved references, or box diagnostics.
- All seven figures and 13 tables remain present and referenced. All 19 pages were visually reviewed. The independently compiled source ZIP has identical extracted text and page pixels.
- An independent comparison checked 140 citation/reference/label commands, 46 protected environments, 119 inline-math expressions, per-file numeric-literal and LaTeX-macro counts, all 12 generated include files, seven figure files, 47 template assets, the bibliography, and the main document outside the abstract. No differences were found in these protected items. See `evidence/rewriting_verification.json`.
- Reproduce the source comparison with `python3 -B journal/ieee/scripts/verify_rewrite.py --baseline-ref 1f8e65ae3547682e2cddda8ec2dc7e9ae664b8c2 --output journal/ieee/evidence/rewriting_verification.json` from the project root.
