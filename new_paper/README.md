# Manuscript build and research-table regeneration

The repository includes the IEEEtran source, figures, generated table fragments, and the verified PDF. Dataset archives and sealed experiment runs are intentionally excluded because they are local research artifacts. Consequently, a fresh clone can compile the included manuscript but cannot regenerate its numerical fragments without those inputs.

## Regenerate tables

The table generator verifies the sealed manifests and reads the official BEIR layout under `research/data/`. The dataset loader does not download datasets. Obtain the two final sealed run directories and the matching SciFact/NFCorpus BEIR files from the authors, place them at the paths below, and install the backend/research dependencies before running:

```sh
backend/.venv/bin/python new_paper/generate_tables.py \
  --scifact-run research/runs/20260918T170818Z_minilm_final_reproducible \
  --nfcorpus-run research/runs/20260918T170715Z_minilm_final_reproducible
```

The generated fragments are written to `new_paper/generated/` by default. Do not hand-edit their numerical contents; regenerate them from verified run artifacts.

## Compile the manuscript

Use Tectonic 0.17.0 or a compatible LaTeX installation. From this directory:

```sh
build_dir="$(mktemp -d)"
tectonic --outdir "$build_dir" main.tex
```

The first Tectonic build may download IEEEtran and TeX resources. The command writes the preview PDF and build log to a temporary directory rather than replacing the checked-in `main.pdf`.
