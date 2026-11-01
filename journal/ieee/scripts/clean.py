"""Remove reproducible IEEE build files while retaining sources and audit evidence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

PAPER = Path(__file__).resolve().parents[1]
DIRECTORIES = ('build', '.cache', '.tmp', 'tools', 'template/reference_papers', 'scripts/__pycache__')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidates() -> list[Path]:
    paths = [PAPER / relative for relative in DIRECTORIES if (PAPER / relative).exists()]
    tex = '\n'.join(p.read_text() for p in PAPER.rglob('*.tex')
                    if 'build' not in p.relative_to(PAPER).parts and 'tools' not in p.relative_to(PAPER).parts)
    paths.extend(p for p in sorted((PAPER / 'figures').glob('*.png'))
                 if p.with_suffix('.pdf').is_file() and p.name not in tex)
    obsolete = PAPER / 'evidence/cleanup.json'
    if obsolete.exists():
        paths.append(obsolete)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='List removal targets without writing anything')
    args = parser.parse_args()
    paths = candidates()
    if not paths:
        print('IEEE folder is already clean')
        return
    files = []
    for path in paths:
        assert path.parent.resolve().is_relative_to(PAPER), f'Outside-paper target: {path}'
        for item in sorted(path.rglob('*')) if path.is_dir() and not path.is_symlink() else [path]:
            if item.is_file() or item.is_symlink():
                files.append({'path': str(item.relative_to(PAPER)), 'bytes': item.lstat().st_size})
    if args.dry_run:
        for path in paths:
            print(path.relative_to(PAPER))
        print(f'{len(files)} files; {sum(f["bytes"] for f in files):,} logical bytes')
        return
    checks = json.loads((PAPER / 'evidence/publication_checks.json').read_text())
    integrity = json.loads((PAPER / 'evidence/artifact_integrity.json').read_text())
    visual = json.loads((PAPER / 'evidence/visual_inspection.json').read_text())
    assert not checks['issues'] and not checks['warnings']
    assert checks['pdf_sha256'] == integrity['pdf_sha256'] == sha(PAPER / 'main.pdf')
    assert integrity['source_archive_sha256'] == sha(PAPER / 'latex_source.zip')
    assert visual['pdf_sha256'] == integrity['pdf_sha256']
    assert all(p['reviewed'] for p in visual['pages'])
    assert [p['render_sha256'] for p in visual['pages']] == [p['render_sha256'] for p in integrity['pages']]
    manifest = PAPER / 'evidence/cleanup_inventory.json'
    record = {'started_at_utc': datetime.now(timezone.utc).isoformat(), 'status': 'planned',
              'size_convention': 'Logical file sizes; hard-linked compiler files may be counted repeatedly.',
              'targets': [str(p.relative_to(PAPER)) for p in paths], 'removed_files': files,
              'retained_pdf_sha256': sha(PAPER / 'main.pdf'),
              'retained_source_archive_sha256': sha(PAPER / 'latex_source.zip')}
    manifest.write_text(json.dumps(record, indent=2) + '\n')
    for path in paths:
        if path.is_symlink() or path.is_file():
            path.unlink()
        else:
            shutil.rmtree(path)
    record.update(status='complete', completed_at_utc=datetime.now(timezone.utc).isoformat())
    manifest.write_text(json.dumps(record, indent=2) + '\n')
    print(f'Removed {len(files)} reproducible/duplicate files; final PDF, sources, template and evidence retained')


if __name__ == '__main__':
    main()
