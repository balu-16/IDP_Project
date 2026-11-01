# Standalone IEEE Access LaTeX source

Compile `main.tex` with **pdfLaTeX**, then BibTeX, then pdfLaTeX twice. On Overleaf, select pdfLaTeX. The source ZIP places the publisher class, style, font and logo assets at its root and needs no Python, experiment directories, model downloads, credentials, or JSON files.

`template_compat.tex` repairs zero-width container diagnostics in the class without editing the publisher files or changing their fonts, colors, page geometry, or visual placements. Standard ragged-bottom columns retain natural paragraph spacing around floats.

The class/font assets are preserved without edits. The direct May 2026 IEEE download returned HTTP 403 in the preparation environment, so the supplied assets were obtained from a pinned public mirror of that template. Exact equivalence to the inaccessible official ZIP is not independently certified. The complete artifact records URLs, commit, and SHA-256 hashes in `evidence/template_download.json`.

This is a submission manuscript. Its journal DOI and volume have not been assigned. Funding/conflict declarations, biographies, the conference extension statement, and AI-use disclosure require author review before submission.
