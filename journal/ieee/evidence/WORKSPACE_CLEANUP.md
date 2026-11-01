# Project-wide cache cleanup — 25 October 2026

The user approved removal of all project-local caches and downloaded dataset archives, while retaining installed dependencies, extracted datasets, saved experiment records, application documents/vector data and papers.

Removed 18,983 inventoried files. The checksums of all 81,297 protected files passed, with three explicitly recorded documentation/preservation-checker updates. A final metadata check also passed after dependency smoke checks. The original preservation snapshots were retained.

## Removed

- Research corpus embeddings and partial encoding shards under `research/cache/`.
- Project-local model downloads under `backend/model_cache/`.
- Dataset download archives under `research/downloads/`.
- Python bytecode, pytest/tool caches, Vite caches and generated frontend output.
- Only source-backed bytecode was removed inside the installed Python environment; one stale Python 3.11 application bytecode file with no source was also removed.

## Preserved and verified

- Installed Python/frontend package code and binaries; lightweight backend and frontend imports passed.
- All saved research runs, feature records, protocols, source snapshots, outcomes and extracted source datasets.
- Uploaded application documents and ChromaDB files, configuration/secrets, lockfiles and existing user edits.
- Conference and IEEE manuscript sources, PDFs, figures, numerical evidence, and the quantum faculty-review plan.
- User-wide caches, Git history and Docker volumes.

All selected cache locations are absent after verification. No models were loaded, no embeddings were regenerated, and no benchmark or circuit study was run. The retained journal artifact check passed. The preservation guard accepted the authorized removals and rejected unrelated file changes, unexpected cache recreation and a corrupt cleanup inventory in isolated checks.

## Recovery

The model downloads and research embeddings were intentionally deleted. Restore the pinned model revisions and rebuild/revalidate the required embeddings before affected research resumes. Existing partial-encoding progress notes describe historical files that are no longer present. Archive-dependent provenance checks require the original dataset archives to be downloaded and checksum-verified again. The backend may download its embedding model on first use; frontend production output is recreated by its build command. No automatic restoration or study restart was performed. TREC-COVID remains deferred, the SCIDOCS stop remains in force, and the quantum paper remains a plan awaiting faculty confirmation.

The machine-readable report is `workspace_cleanup.json`; its checksummed `workspace_cleanup_inventory.json.gz` contains the pre-deletion file inventory. The report records allocated workspace size and recovered disk space after cleanup.

Recovered approximately **1.85 GB (1.72 GiB)** of allocated workspace space.
