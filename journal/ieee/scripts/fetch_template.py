"""Download publisher template assets, preserving their bytes and provenance."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.request

JOURNAL = Path(__file__).resolve().parents[1]
REPOSITORY = "Code-Yan-ZX/multipage-docvqa-diagnosis"
DIRECTORY = "ACCESS_latex_template_20260513"
MIRROR_COMMIT = "d4fc96ce66226b85e7eb815a3f2321b3525fd5d4"


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Journal template provenance"}), timeout=30) as response:
        return response.read()


def main():
    commit = MIRROR_COMMIT
    listing = json.loads(get(f"https://api.github.com/repos/{REPOSITORY}/contents/{DIRECTORY}?ref={commit}"))
    assets = [a for a in listing if a["name"].endswith((".cls", ".bst", ".sty", ".fd", ".tfm", ".pfb", ".map")) or a["name"] in {"logo.png", "notaglinelogo.png", "bullet.png"}]
    directory = JOURNAL / "template/assets"
    directory.mkdir(parents=True, exist_ok=True)

    def fetch(asset):
        url = f"https://raw.githubusercontent.com/{REPOSITORY}/{commit}/{DIRECTORY}/{asset['name']}"
        content = get(url)
        (directory / asset["name"]).write_bytes(content)
        return asset["name"], {"sha256": hashlib.sha256(content).hexdigest(), "url": url}

    with ThreadPoolExecutor(max_workers=6) as pool:
        records = dict(pool.map(fetch, assets))
    record = {
        "official_preparation_page": "https://ieeeaccess.ieee.org/authors/preparing-your-article/",
        "official_archive": "https://ieeeaccess.ieee.org/wp-content/uploads/2026/05/ACCESS_latex_template_20260513-1-1.zip",
        "official_download_status": "HTTP 403 from this environment; archive bytes could not be compared",
        "mirror": f"https://github.com/{REPOSITORY}/tree/{commit}/{DIRECTORY}",
        "mirror_commit": commit,
        "policy": "Publisher class/style/font assets obtained from a public mirror of the May 2026 template; preserved without edits. Direct archive equivalence is not independently established.",
        "files": records,
    }
    (JOURNAL / "evidence/template_download.json").write_text(json.dumps(record, indent=2) + "\n")
    # Source builds use the preserved publisher assets from the documented mirror.
    print(f"Saved {len(records)} unmodified template assets; mirror commit {commit}")


if __name__ == "__main__":
    main()
