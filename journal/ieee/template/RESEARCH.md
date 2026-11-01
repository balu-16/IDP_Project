# IEEE Access template and published-paper research

IEEE Access is the selected target because its multidisciplinary scope accommodates a controlled retrieval evaluation with quantum-search implementation/resource analysis. The article is prepared as a Research Article. Its class is `ieeeaccess`, not the conference `IEEEtran` layout.

Official instructions: https://ieeeaccess.ieee.org/authors/preparing-your-article/ and https://ieeeaccess.ieee.org/authors/submission-guidelines/ . The official template link inspected on October 24, 2026 points to `ACCESS_latex_template_20260513-1-1.zip`. Direct access returned HTTP 403. The IEEE-authored Overleaf gallery was also inspected (https://www.overleaf.com/latex/templates/ieee-access-latex-template/cdxrhtbjgszv); its displayed source is older and was not used to replace the current class.

The May 2026 class, styles, logos, font maps, metrics, and font programs were retrieved without edits from a public repository containing the template. The pinned commit, source URLs, and SHA-256 hashes are in `../evidence/template_download.json`. This is a mirror fallback, not a verified direct official-archive download. No unrelated mirrored manuscript text, bibliography, results, or author portraits are used.

## Published exemplars

| Paper | Primary publication record | Observed format/structure |
|---|---|---|
| Norimoto, Mikuriya, and Ishikawa, “Quantum Speedup for Multiuser Detection With Optimized Parameters in Grover Adaptive Search,” IEEE Access 12, 83810–83821 (2024) | https://doi.org/10.1109/ACCESS.2024.3413084 ; published PDF https://inspirehep.net/files/68d5994464368da5217b692575524955 | 12 pages; title/authors/affiliation/correspondence on first page; single-paragraph abstract and index terms; Roman-numbered major sections, lettered subsections, gate-count tables, below-figure captions, numbered references, biographies. |
| Ominato, Ohyama, and Yamaguchi, “Grover Adaptive Search With Fewer Queries,” IEEE Access 12, 74619–74632 (2024) | https://doi.org/10.1109/ACCESS.2024.3403200 ; published PDF https://inspirehep.net/files/425f4adac6dad984ce152bd2aee5c2bd | 14 pages; mathematical treatment and simulations in the main body; proofs in appendices; same first-page and reference conventions. |
| Elkiran and Rasheed, “An Empirical Evaluation of Retrieval, Reranking, and Similarity for a Q&A-Based Retrieval Augmented Generation System,” IEEE Access 14, 26053–26066 (2026) | https://doi.org/10.1109/ACCESS.2026.3664852 ; institutional published PDF https://openaccess.izu.edu.tr/bitstreams/1d86a835-3fa9-46ed-a896-ccdd53833a2e/download | 14 pages; related work, system methodology, experimental evaluation, statistical analysis, discussion, conclusion, and biographies; multi-affiliation author block and numbered bracket citations. |

The journal source follows the supplied class's page dimensions, fonts, colors, headings, caption conventions, and bibliography style. It includes a 150–250-word abstract, alphabetized index terms, and short fact-based biographies. No custom geometry, font replacement, or artificial line-spacing compression is used. Tables and figures are placed through ordinary class-supported floats.

`../template_compat.tex` normalizes the class's intentional zero-width footer containers and its abstract/keyword box containers. This resolves diagnostics also reproduced by a minimal template probe, preserving their visual positions, fonts, colors, and page geometry. It does not edit the class or suppress box diagnostics. The standard `raggedbottom` command keeps paragraph spacing natural in columns with floats; unused vertical space remains at the column bottom. Table paragraphs use ordinary ragged-right column alignment.

IEEE Access requires conference-extension disclosure, a cited prior article, similarity below 35%, and AI-generated-content disclosure. Separate highlights and a graphical abstract are not required by the inspected general Research Article checklist and have not been invented as mandatory deliverables. A self-contained architecture diagram serves the technical exposition.
