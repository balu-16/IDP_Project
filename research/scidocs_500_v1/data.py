"""Official BEIR snapshot, strict loader, and immutable inventory."""
from collections import Counter
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import unicodedata
import urllib.request
import zipfile

from research.accuracy_v2.storage import ROOT, digest, sha, write_checked, read_checked

URL = "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/scidocs.zip"
CATALOGUE = "https://github.com/beir-cellar/beir/wiki/Datasets-available"
MD5 = "38121350fc3a4d2f48850f6aff52e4a9"
DATA = ROOT / "research/data/scidocs_500_v1/scidocs"
ARCHIVE = ROOT / "research/downloads/scidocs_500_v1/scidocs.zip"
FILES = ("corpus.jsonl", "queries.jsonl", "qrels/test.tsv")


def md5(path):
    h = hashlib.md5()
    with Path(path).open("rb") as handle:
        for part in iter(lambda: handle.read(1 << 20), b""):
            h.update(part)
    return h.hexdigest()


def prepare():
    """Never replace a corrupt completed archive or an existing extracted file."""
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    if not ARCHIVE.exists():
        partial = ARCHIVE.with_suffix(".zip.part")
        # A partial HTTP transfer has no trusted identity; restart only this transfer.
        with urllib.request.urlopen(URL, timeout=60) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out, length=1 << 20)
            out.flush()
            os.fsync(out.fileno())
        if md5(partial) != MD5:
            raise ValueError("Downloaded SCIDOCS archive differs from the published MD5")
        os.replace(partial, ARCHIVE)
    if md5(ARCHIVE) != MD5:
        raise ValueError("Existing SCIDOCS archive corrupt; refusing replacement")
    with zipfile.ZipFile(ARCHIVE) as archive:
        members = archive.namelist()
        if len(members) != len(set(members)):
            raise ValueError("Duplicate archive members")
        for relative in FILES:
            member = f"scidocs/{relative}"
            expected = hashlib.sha256(archive.read(member)).hexdigest()
            target = DATA / relative
            if target.exists():
                if sha(target) != expected:
                    raise ValueError(f"Extracted dataset corrupt: {relative}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".pending-", delete=False) as out:
                temporary = Path(out.name)
                try:
                    with archive.open(member) as source:
                        shutil.copyfileobj(source, out)
                    out.flush()
                    os.fsync(out.fileno())
                except BaseException:
                    temporary.unlink(missing_ok=True)
                    raise
            os.replace(temporary, target)
    return inventory()


def _json_rows(path):
    seen = set()
    with Path(path).open() as handle:
        for line in handle:
            row = json.loads(line)
            did = row.get("_id")
            if not isinstance(did, str) or not did or did in seen:
                raise ValueError(f"Invalid or duplicate ID in {path}: {did}")
            seen.add(did)
            yield did, row


def load(base=DATA, expected=True):
    base = Path(base)
    corpus = {}
    for did, row in _json_rows(base / "corpus.jsonl"):
        text = (row.get("title", "") + " " + row["text"]).strip()
        corpus[did] = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()
    queries = {qid: row["text"] for qid, row in _json_rows(base / "queries.jsonl")}
    if any(not isinstance(q, str) or not q.strip() for q in queries.values()):
        raise ValueError("Missing query text")
    judgments = {qid: {} for qid in queries}
    with (base / "qrels/test.tsv").open() as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames != ["query-id", "corpus-id", "score"]:
            raise ValueError("Unexpected BEIR qrels header")
        for row in reader:
            qid, did, raw = row["query-id"], row["corpus-id"], row["score"]
            grade = int(raw)
            if qid not in queries or did not in corpus or did in judgments[qid] or grade not in (-1, 0, 1, 2):
                raise ValueError(f"Invalid, duplicate, or dangling judgment: {row}")
            judgments[qid][did] = grade
    if any(not any(g > 0 for g in rel.values()) for rel in judgments.values()):
        raise ValueError("Every evaluation query requires positive judgments")
    if expected and (len(corpus) != 25657 or len(queries) != 1000):
        raise ValueError("Official SCIDOCS corpus/query coverage mismatch")
    return corpus, queries, judgments


def inventory(base=DATA, archive=ARCHIVE):
    base, archive = Path(base), Path(archive)
    if md5(archive) != MD5:
        raise ValueError("Official archive MD5 mismatch")
    with zipfile.ZipFile(archive) as zipped:
        hashes = {p: sha(base / p) for p in FILES}
        for p, expected in hashes.items():
            if hashlib.sha256(zipped.read(f"scidocs/{p}")).hexdigest() != expected:
                raise ValueError(f"Local file differs from official archive: {p}")
    corpus, queries, judgments = load(base)
    return {"dataset": "scidocs", "source_url": URL, "checksum_source": CATALOGUE,
            "archive_md5": MD5, "archive_sha256": sha(archive), "files": hashes,
            "corpus_count": len(corpus), "corpus_ids_sha256": digest(sorted(corpus)),
            "query_ids": sorted(queries), "query_texts_sha256": digest(queries),
            "graded_judgments_sha256": digest(judgments),
            "grade_histogram": dict(sorted(Counter(str(g) for r in judgments.values() for g in r.values()).items())),
            "split": "test only; fixed 500-query ID-only subset; no development split or tuning"}


def save_ids(output):
    corpus, queries, judgments = load()
    value = {"corpus_ids": sorted(corpus), "query_ids": sorted(queries), "graded_judgments": judgments}
    output = Path(output)
    if output.exists():
        if read_checked(output) != value:
            raise ValueError("Dataset inventory artifact changed")
    else:
        write_checked(output, value)
    return sha(output)
