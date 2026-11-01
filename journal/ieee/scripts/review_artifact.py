"""Check the delivered PDFs, source archive, template bytes, and local text reuse.

Run with the system Python, which supplies PyMuPDF. All outputs stay in journal/.
Phrase matching is a local diagnostic, not publisher similarity certification.
"""
from __future__ import annotations

from collections import Counter
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import unicodedata
import zipfile

import fitz

JOURNAL = Path(__file__).resolve().parents[1]
ROOT = JOURNAL.parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_report(name: str, payload: dict) -> None:
    (JOURNAL / "evidence" / name).write_text(json.dumps(payload, indent=2) + "\n")


def body_tokens(document: fitz.Document) -> list[str]:
    # Preserve PDF content order. Geometric row sorting interleaves the two
    # columns and can place bibliography entries before the REFERENCES heading.
    text = "\n".join(page.get_text() for page in document)
    # Bibliographies and subsequent biographies are outside this body diagnostic.
    assert re.search(r"\n\s*REFERENCES\s*\n", text), "Reference heading not found"
    text = re.split(r"\n\s*REFERENCES\s*\n", text, maxsplit=1)[0]
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    return re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKC", text).lower())


def overlap_diagnostic(current: fitz.Document) -> dict:
    source_path = ROOT / "new_paper/main.pdf"
    with fitz.open(source_path) as conference:
        prior = body_tokens(conference)
    now = body_tokens(current)
    width = 10
    phrases = {tuple(prior[i:i + width]) for i in range(len(prior) - width + 1)}
    covered: set[int] = set()
    matches: Counter[str] = Counter()
    for i in range(len(now) - width + 1):
        phrase = tuple(now[i:i + width])
        if phrase in phrases:
            covered.update(range(i, i + width))
            matches[" ".join(phrase)] += 1
    return {
        "source": str(source_path.relative_to(ROOT)),
        "conference_sha256": sha(source_path),
        "journal_pdf_sha256": sha(JOURNAL / "main.pdf"),
        "normalization": "PDF content order; lowercase ASCII alphanumeric tokens after Unicode NFKC and line-hyphen repair; text before REFERENCES, including tables, headers and equations.",
        "exact_phrase_words": width,
        "conference_body_tokens": len(prior),
        "journal_body_tokens": len(now),
        "journal_tokens_in_shared_phrases": len(covered),
        "covered_fraction": len(covered) / len(now),
        "shared_phrases": [{"phrase": p, "occurrences": n} for p, n in matches.most_common()],
        "interpretation": "Diagnostic against this conference PDF only. This is neither an iThenticate score, a scientific-novelty percentage, nor certification of the journal's similarity threshold.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--saved', action='store_true',
                        help='Check retained artifacts without rebuilding or writing previews')
    args = parser.parse_args()
    checks = json.loads((JOURNAL / "evidence/publication_checks.json").read_text())
    assert checks["pdf_sha256"] == sha(JOURNAL / "main.pdf")
    assert checks["source_sha256"] == sha(JOURNAL / "main.tex")
    assert not checks["issues"] and not checks["warnings"]
    template = json.loads((JOURNAL / "evidence/template_download.json").read_text())
    for filename, record in template["files"].items():
        assert sha(JOURNAL / "template/assets" / filename) == record["sha256"]
    with zipfile.ZipFile(JOURNAL / "latex_source.zip") as archive:
        assert archive.testzip() is None
        for name in archive.namelist():
            assert not name.startswith("/") and ".." not in Path(name).parts
        for filename, record in template["files"].items():
            assert hashlib.sha256(archive.read(filename)).hexdigest() == record["sha256"]
        sources = [JOURNAL / n for n in ['main.tex', 'template_compat.tex', 'references.bib', 'SOURCE_README.md']]
        for folder, pattern in [('sections', '*.tex'), ('includes', '*.tex'), ('figures', '*.pdf')]:
            sources.extend((JOURNAL / folder).glob(pattern))
        for source in sources:
            assert archive.read(str(source.relative_to(JOURNAL))) == source.read_bytes()
    exported = json.loads((JOURNAL / 'evidence/export_verification.json').read_text())
    assert exported['exporter_sha256'] == sha(JOURNAL / 'scripts/export_evidence.py')
    for relative, digest in exported['generated_sha256'].items():
        assert sha(JOURNAL / relative) == digest
    standalone = json.loads((JOURNAL / "evidence/standalone_check.json").read_text())
    assert standalone["source_archive_sha256"] == sha(JOURNAL / "latex_source.zip")
    native = JOURNAL / "evidence/native_resources.csv"
    source = ROOT / "research/runs/resource_study_v1_final/native_resources.csv"
    assert native.read_bytes() == source.read_bytes()
    if args.saved:
        integrity = json.loads((JOURNAL / 'evidence/artifact_integrity.json').read_text())
        visual = json.loads((JOURNAL / 'evidence/visual_inspection.json').read_text())
        assert integrity['pdf_sha256'] == visual['pdf_sha256'] == sha(JOURNAL / 'main.pdf')
        assert integrity['source_archive_sha256'] == sha(JOURNAL / 'latex_source.zip')
        assert all(p['reviewed'] for p in visual['pages'])
        assert [p['render_sha256'] for p in integrity['pages']] == [p['render_sha256'] for p in visual['pages']]
        with fitz.open(JOURNAL / 'main.pdf') as pdf:
            assert len(pdf) == checks['pages'] == len(integrity['pages']) == len(visual['pages'])
        print('Retained PDF, source ZIP, evidence, template and review records verified; no files written')
        return
    (JOURNAL / 'build/pages').mkdir(parents=True, exist_ok=True)
    with fitz.open(JOURNAL / "main.pdf") as document, fitz.open(
        JOURNAL / "build/standalone/output/main.pdf"
    ) as other:
        assert len(document) == len(other) == checks["pages"]
        pages = []
        for index, (page, counterpart) in enumerate(zip(document, other), 1):
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False)
            second = counterpart.get_pixmap(matrix=fitz.Matrix(1.4, 1.4), alpha=False)
            assert pixmap.samples == second.samples, f"Standalone visual mismatch: page {index}"
            target = JOURNAL / "build/pages" / f"page_{index:02}.png"
            pixmap.save(target)
            pages.append({"page": index, "render_sha256": sha(target), "standalone_pixels_match": True})
        write_report("prose_overlap_diagnostic.json", overlap_diagnostic(document))
    write_report("artifact_integrity.json", {
        "pdf_sha256": sha(JOURNAL / "main.pdf"),
        "source_archive_sha256": sha(JOURNAL / "latex_source.zip"),
        "unchanged_template_assets": len(template["files"]),
        "native_csv_matches_sealed_report": True,
        "render_dpi": 100.8,
        "pages": pages,
    })
    # A recompilation changes PDF timestamps. Reuse the recorded visual review
    # only when every page image is byte-identical to the inspected rendering.
    visual_path = JOURNAL / 'evidence/visual_inspection.json'
    if visual_path.exists():
        visual = json.loads(visual_path.read_text())
        same_pages = ([p['render_sha256'] for p in pages]
                      == [p['render_sha256'] for p in visual['pages']])
        if not same_pages:
            raise SystemExit('Page renderings changed; inspect the previews and update the visual review before cleanup')
        if visual['pdf_sha256'] != sha(JOURNAL / 'main.pdf'):
            visual['prior_review_pdf_sha256'] = visual['pdf_sha256']
            visual['pdf_sha256'] = sha(JOURNAL / 'main.pdf')
            visual['identical_render_rebuild_at_utc'] = datetime.now(timezone.utc).isoformat()
            write_report('visual_inspection.json', visual)
    print(f"Verified {len(pages)} pixel-identical standalone pages and {len(template['files'])} unchanged template assets")


if __name__ == "__main__":
    main()
