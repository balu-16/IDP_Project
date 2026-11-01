# IEEE Access journal manuscript

Main deliverables: [main.pdf](main.pdf), [main.tex](main.tex), [references.bib](references.bib), vector figures in `figures/`, and the self-contained [LaTeX source ZIP](latex_source.zip). See [AUTHOR_VOICE_CHANGELOG.md](AUTHOR_VOICE_CHANGELOG.md), [VERIFICATION.md](VERIFICATION.md), and [AUTHOR_REVIEW.md](AUTHOR_REVIEW.md). The earlier prose revision is recorded in [REVISION_CHANGELOG.md](REVISION_CHANGELOG.md).

The current manuscript is 19 pages with 52 cited references, including all 13 requested application papers. Publisher metadata and the resolved fraud-paper DOI are retained in `../../manuscript_support/records/requested_references.json`; `evidence/reference_update_checks.json` records the earlier reference update; the latest build and visual records are in `evidence/publication_checks.json` and `evidence/visual_inspection.json`.

This manuscript uses the completed SciFact (300 queries), NFCorpus (323 queries), and earlier FiQA base (648 queries) runs selected by the project source mapping. Negative follow-up outcomes remain disclosed. No new benchmark rankings, neural inference, circuit experiments or retuning were performed for this journal artifact.

## Build, verify and clean

Run these commands from the **project root**:

```sh
backend/.venv/bin/python -B journal/ieee/scripts/build.py --standalone --preserve-existing-additions
python3 -B journal/ieee/scripts/review_artifact.py
python3 -B journal/ieee/scripts/clean.py --dry-run
python3 -B journal/ieee/scripts/clean.py
```

The first command recreates temporary directories and, if absent, downloads the pinned TinyTeX compiler into this paper's `tools/` directory. Extra TeX packages are installed only in that local distribution. Configuration, temporary files and caches stay within `journal/ieee/`. The preservation option snapshots files added outside the journal since the original audit, then verifies their hashes after the build; it does not relax the checks on original files. Rebuilding after cleanup therefore requires network access. The source ZIP can also be compiled with pdfLaTeX/BibTeX on Overleaf without Python or experiment data; see [SOURCE_README.md](SOURCE_README.md).

The second command requires system Python with PyMuPDF. It checks the standalone PDF page by page against the main PDF and writes temporary page previews. An identical rendering retains the existing visual review even if a rebuild changes PDF timestamps. A changed rendering requires a fresh page inspection and review record before cleanup. The cleanup commands list/remove those previews, build outputs, caches, tools, downloaded reference-paper copies and duplicate figure PNGs. Required template images, vector figures, sources, final PDF, source ZIP and scientific/verification evidence are retained. Cleanup records its inventory before deleting files and is safe to repeat.

To verify the retained artifact **after cleanup**, without downloading a compiler or writing previews:

```sh
python3 -B journal/ieee/scripts/review_artifact.py --saved
```

This checks the retained files against the saved build/visual-review records; a new compilation requires the build command above.

## Evidence and figures

`evidence/` retains saved-run identities, all-method metrics, query diagnostics, seed metrics, request timing components, the native-resource CSV, bibliographic records, template provenance and verification summaries. These support the manuscript and are not temporary build files. The original research artifacts remain read-only inputs elsewhere in the project.

Figure generation now writes **PDF only**. All seven vector PDFs are used by the manuscript. Publisher PNG logos and bullets in `template/assets/` are separate required assets.

The numerical exporter binds its generated values by SHA-256. To regenerate secondary analyses from verified saved runs and check manifest/evaluation hashes:

```sh
backend/.venv/bin/python -B journal/ieee/scripts/export_evidence.py --refresh-analysis
```

Omit `--refresh-analysis` for full saved-run provenance/metric verification. Neither mode collects experiments or reruns models. To redraw figures after a deliberate analysis change, use `backend/.venv/bin/python -B journal/ieee/scripts/make_figures.py`, then build, review and clean. Relocation and cleanup preserve the existing figure bytes and scientific values.

`evidence/reorganization_inventory.json` records files before relocation/cleanup. `cleanup_inventory.json` records removed files. `reorganization_comparison.json` documents the earlier relocated PDF before the current prose revision. Current page-image hashes remain in the compact review records after their temporary PNG files are removed.

## Source and author status

The current conference and journal manuscripts list four authors: Bala Rakesh Gundapaneni, Abdul Basith Syed, Jagadeeshbabu Borru, and Naga Sravanthi Puppala. The corresponding author remains Naga Sravanthi Puppala. The user-requested authorship update covers the author blocks, PDF metadata, running headers, biographies, conference citation, and portable source ZIPs; see `evidence/authorship_update.json`.

Original tracked-file hashes and the outside-folder metadata snapshot remain intact. The outside-scope `docker-compose.yml` edit detected during preparation is separately recorded and preserved. Project checks continue to reject other unrecorded differences; the snapshots were not reset.

The subsequent user-approved project-wide cache cleanup is recorded in `evidence/workspace_cleanup.json`, with per-file checksums in its compressed inventory and the final preservation-check result in that JSON report. The preservation checker recognizes only the recorded absent cache files and explicitly recorded documentation edits, while retaining the initial snapshots. Saved results, extracted datasets and paper assets remain intact; deleted models, corpus embeddings and source download archives require restoration before cache-dependent research can resume. No benchmark or model run is performed by this cleanup. See `evidence/WORKSPACE_CLEANUP.md` for the final report.

The direct IEEE template download returned HTTP 403. The unchanged publisher assets come from a pinned mirror; direct official-archive equivalence remains an author-review item. Downloaded reading copies are removed, while their publication URLs and provenance records remain.

No publisher submission or upload has been made. The second journal is represented only by the faculty-review plan in `../quantum/PLAN.md`.
