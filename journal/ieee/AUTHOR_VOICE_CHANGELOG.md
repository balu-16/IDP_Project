# Author-voice revision

This revision uses the preceding 19-page journal manuscript as its baseline. It restructures prose around the documented design, observations, and limits; it adds no experiment, result, reference, or unconfirmed explanation. The existing acknowledgment of Codex assistance remains unchanged.

## Diagnosis

The first priority was the abstract, introduction, related work, discussion, and conclusion: their framing and limitations sometimes repeated the same point, and the application-specific literature appeared as a list. The method, protocol, results, and diagnostics were the next priority: their facts were specific, but some passages could more clearly connect a design choice or measurement to its consequences. The formulation and resource study received a lighter pass. The appendix explanations and protected proofs were retained.

These priorities are editorial judgments, not AI-detection findings. The available reports show 76% and 77% for earlier drafts. The detector score for this revision has **not** been measured; the authors must rerun the detector. No claim is made that a particular score has been achieved.

The literature context was checked against the original [GAS paper](https://quantum-journal.org/papers/q-2021-04-08-428/), [SciFact paper](https://aclanthology.org/2020.emnlp-main.609/), and [retrieval-augmented generation paper](https://arxiv.org/abs/2005.11401). Existing citation commands and bibliography entries were not changed.

## Changes by section

| Section | Revision |
|---|---|
| Abstract | Reframed the relevance--redundancy question, policy, collection-specific results, and limits. |
| Introduction | Connected the evidence budget to the protected-prefix design and distinguished the journal analysis from conference work. |
| Related Work | Grouped retrieval, set selection, and quantum-search approaches by the decisions they address; retained the separately contextualized application citations. |
| Problem Formulation and System Boundaries | Clarified parent-versus-passage judgments, candidate ceilings, and the different simulation boundaries. |
| Relevance-Guided Subset Search | Explained the consequences of local score normalization, retained logits, tail constraints, and pre-amplification enumeration. |
| Data and Experimental Protocol | Clarified passage construction, development choices, the failed confirmation and recorded continuation, and timing boundaries. |
| Recorded Retrieval Results | Emphasized the different dataset configurations, matched classical controls, recall tradeoffs, and limits of statistical interpretation. |
| Coverage, Failure, and Cost Diagnostics | Reworked the candidate-coverage argument and the two recorded query-level losses; kept the timing and seed interpretations tied to the saved results. |
| Resource Study and Precision Sensitivity | Clarified compact versus native accounting, the search/precision tradeoff, and the limits of validation. |
| Discussion, Limitations, and Reproducibility | Connected the protected-prefix guarantee, classical controls, measured costs, and validity limits. |
| Conclusion | Restated the supported findings, negative outcomes, and boundaries without extending the claims. |
| Appendices A and B | Reviewed; their existing text, equations, and reporting conventions were left unchanged. |

## Author input requested

The following `% TODO(author)` comments are in the LaTeX source and do not add unconfirmed statements to the PDF:

1. `sections/introduction.tex`: explain the original choice of candidate-pool and output sizes, if documented.
2. `sections/protocol.tex`: explain how the recall-retention threshold was chosen, if documented.
3. `sections/related_work.tex`: clarify how the application-specific papers inform the scope of this retrieval study.

The current acknowledgment identifies Codex assistance, but the bibliography does not contain an AI-system citation. The [IEEE Access submission guidelines](https://ieeeaccess.ieee.org/authors/submission-guidelines/) call for a citation in sections using AI-generated text. This remains an author-review item because citation commands and bibliography entries were protected from modification.

## Verification

- The PDF has 19 pages and a 217-word abstract. The full pdfLaTeX/BibTeX build has no warnings or unresolved references; all 52 bibliography entries, seven figures, and 13 tables are present. All pages were visually reviewed, and the independently compiled source ZIP has identical extracted text and page pixels.
- The baseline comparison found no changes to 140 citation/reference/label commands, 46 protected environments, 119 inline-math expressions, per-file numeric-literal and LaTeX-macro counts, the bibliography, generated includes, figures, or template assets. See `evidence/author_voice_verification.json`.
- The exact pre-revision source and PDF are retained in `evidence/author_voice_baseline.zip`. To repeat the comparison, extract that archive to a directory and run `python3 -B journal/ieee/scripts/verify_rewrite.py --baseline-dir <extracted-directory> --output <report.json>` from the project root.

The preceding prose revision and its historical measurements remain documented in `REVISION_CHANGELOG.md`; they are not scores for this PDF.
