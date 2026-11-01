# QubitChat UROP report

- `QubitChat_UROP_Report.pdf` is the seven-page PDF compiled from LaTeX.
- `QubitChat_UROP_Report.tex` is the editable LaTeX source; keep `srm_emblem.png`, `observed_tradeoffs.pdf`, and `cost_decomposition.pdf` beside it when compiling. These files are also in `QubitChat_UROP_LaTeX.zip`.
- `QubitChat_UROP_Report.docx` is the editable Word version.
- `build_report.py` holds the shared report text and generates both the `.tex` and `.docx` files. It uses `python-docx`; its two high-resolution chart PNGs are used for the Word version.

The two evaluation figures are copied from `../journal/ieee/figures/`. The report retains their original scales and identifies the different dataset configurations in the captions and text.

To regenerate both editable files after changing the shared content:

```sh
python -m pip install python-docx
python build_report.py
pdflatex -interaction=nonstopmode -halt-on-error QubitChat_UROP_Report.tex
pdflatex -interaction=nonstopmode -halt-on-error QubitChat_UROP_Report.tex
```

Run these commands from this directory. Direct edits to the `.tex` or `.docx` file are not incorporated into `build_report.py` and will be overwritten if the generator is run again. The page breaks and contents-page numbers are fixed for this version; after editing, check both the PDF and a Word-to-PDF rendering for pagination, borders, and contents accuracy. Font availability and Word/LibreOffice versions can affect the Word layout.
