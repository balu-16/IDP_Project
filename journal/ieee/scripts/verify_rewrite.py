"""Compare a prose revision with an explicitly selected Git or directory baseline."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unicodedata

JOURNAL = Path(__file__).resolve().parents[1]
ROOT = JOURNAL.parents[1]
COMMANDS = re.compile(r"\\(?:cite|ref|eqref|label)(?:\[[^\]]*\])?\{[^{}]*\}")
PROTECTED = re.compile(
    r"\\begin\{(equation\*?|align\*?|gather\*?|multline\*?|displaymath|"
    r"table\*?|figure\*?|proposition|IEEEproof)\}.*?\\end\{\1\}", re.S
)
INLINE_MATH = re.compile(
    r"(?<!\\)\$(?:\\.|[^$])*?(?<!\\)\$|\\\(.*?\\\)|\\\[.*?\\\]", re.S
)
NUMBERS = re.compile(r"(?<![a-zA-Z])\d+(?:[.,]\d+)*")
MACROS = re.compile(r"\\[A-Za-z]+\*?")


def git_bytes(ref: str, name: str) -> bytes:
    return subprocess.check_output(
        ["git", "show", f"{ref}:journal/ieee/{name}"], cwd=ROOT
    )


def git_files(ref: str, folder: str) -> set[str]:
    result = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", ref, f"journal/ieee/{folder}"],
        cwd=ROOT, text=True,
    )
    return {str(Path(p).relative_to("journal/ieee")) for p in result.splitlines()}


def sentences(source: str) -> list[str]:
    """Approximate editable sentences; locked floats, proofs and equations are omitted."""
    source = PROTECTED.sub(" ", source)
    source = INLINE_MATH.sub(" MATH ", source)
    source = re.sub(r"(?<!\\)%[^\n]*", " ", source)
    source = re.sub(r"\\PARstart\{A\}\{n\}", "An", source)
    source = re.sub(r"\\(?:sub)*section\*?\{[^{}]*\}", " ", source)
    source = re.sub(r"\\(?:cite|ref|eqref|label)\{[^{}]*\}", " REF ", source)
    source = re.sub(r"\\path\{[^{}]*\}", " MODEL_PATH ", source)
    source = source.replace(r"\%", "%").replace("~", " ")
    source = re.sub(r"\\[A-Za-z]+\*?(?:\{[^{}]*\})?", " VALUE ", source)
    source = re.sub(r"\b(Fig|Eq|Sec|et al)\.", r"\1<dot>", source)
    source = re.sub(r"\s+", " ", source).strip()
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", source)
    return [re.sub(r"\s+", " ", part.lower()).strip() for part in parts if part.strip()]


def section_texts(name: str, source: str) -> dict[str, str]:
    if name == "main.tex":
        abstract = source.split(r"\begin{abstract}", 1)[1].split(r"\end{abstract}", 1)[0]
        return {"Abstract": abstract}
    chunks = re.split(r"\\section\{([^{}]+)\}", source)
    return {chunks[i]: chunks[i + 1] for i in range(1, len(chunks), 2)}


def prose_tokens(source: str) -> list[str]:
    """Approximate editable prose for a conference-only phrase comparison."""
    source = PROTECTED.sub(" ", source)
    source = INLINE_MATH.sub(" ", source)
    source = re.sub(r"(?<!\\)%[^\n]*", " ", source)
    source = re.sub(r"\\(?:cite|ref|eqref|label|path|url)\{[^{}]*\}", " ", source)
    source = re.sub(r"\\(?:sub)*section\*?\{[^{}]*\}", " ", source)
    source = re.sub(r"\\[A-Za-z]+\*?(?:\{[^{}]*\})?", " ", source)
    return re.findall(r"[a-z]+|\d+", unicodedata.normalize("NFKC", source).lower())


def conference_prose_overlap(commit: str, tex: list[str]) -> dict:
    conference = subprocess.check_output(
        ["git", "show", f"{commit}:new_paper/main.tex"], cwd=ROOT
    ).decode()
    body = conference.split(r"\begin{abstract}", 1)[1].split(r"\bibliography", 1)[0]
    prior = prose_tokens(body)
    width = 10
    phrases = {tuple(prior[i:i + width]) for i in range(len(prior) - width + 1)}

    def measure(original: bool) -> dict:
        parts = []
        for name in tex:
            if name.endswith("biographies.tex"):
                continue
            source = git_bytes(commit, name).decode() if original else (JOURNAL / name).read_text()
            if name == "main.tex":
                source = section_texts(name, source)["Abstract"]
            parts.append(source)
        tokens = prose_tokens("\n".join(parts))
        covered: set[int] = set()
        for i in range(len(tokens) - width + 1):
            if tuple(tokens[i:i + width]) in phrases:
                covered.update(range(i, i + width))
        return {"tokens": len(tokens), "tokens_in_shared_phrases": len(covered),
                "percent": round(100 * len(covered) / len(tokens), 2)}

    return {
        "source": "new_paper/main.tex at baseline commit",
        "source_sha256": hashlib.sha256(conference.encode()).hexdigest(),
        "phrase_words": width,
        "method": "Approximate LaTeX prose tokens after removing protected environments, inline math, citations and commands; not a publisher similarity or AI-writing score.",
        "original": measure(True),
        "revised": measure(False),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    baseline = parser.add_mutually_exclusive_group(required=True)
    baseline.add_argument("--baseline-ref", help="Git commit containing the original paper")
    baseline.add_argument("--baseline-dir", type=Path, help="Snapshot directory containing the original paper")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    commit = None
    if args.baseline_ref:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--verify", f"{args.baseline_ref}^{{commit}}"], cwd=ROOT, text=True
        ).strip()
        read_before = lambda name: git_bytes(commit, name)
        files_before = lambda folder: git_files(commit, folder)
    else:
        baseline_dir = args.baseline_dir.resolve(strict=True)
        if not baseline_dir.is_dir() or not (baseline_dir / "main.tex").is_file():
            parser.error("--baseline-dir must contain the original journal sources")
        read_before = lambda name: (baseline_dir / name).read_bytes()
        files_before = lambda folder: {
            str(p.relative_to(baseline_dir)) for p in (baseline_dir / folder).rglob("*") if p.is_file()
        }
    tex = ["main.tex", *(str(p.relative_to(JOURNAL)) for p in sorted((JOURNAL / "sections").glob("*.tex")))]
    issues: list[str] = []
    counts = Counter()
    change_estimates = {}
    for name in tex:
        old = read_before(name).decode()
        new = (JOURNAL / name).read_text()
        for label, pattern in [("commands", COMMANDS), ("protected_environments", PROTECTED), ("inline_math", INLINE_MATH)]:
            before = [m.group() for m in pattern.finditer(old)]
            after = [m.group() for m in pattern.finditer(new)]
            counts[label] += len(before)
            if before != after:
                issues.append(f"{name}: {label} changed")
        for match in PROTECTED.finditer(old):
            counts[match.group(1).rstrip("*") + "_environments"] += 1
        if Counter(MACROS.findall(old)) != Counter(MACROS.findall(new)):
            issues.append(f"{name}: LaTeX macro occurrences changed")
        if Counter(NUMBERS.findall(old)) != Counter(NUMBERS.findall(new)):
            issues.append(f"{name}: numeric-literal occurrences changed")
        if name == "main.tex":
            def without_abstract(text: str) -> str:
                return re.sub(r"(?<=\\begin\{abstract\}).*?(?=\\end\{abstract\})", "", text, flags=re.S)
            if without_abstract(old) != without_abstract(new):
                issues.append("main.tex: content outside the abstract changed")
        if name.endswith("biographies.tex"):
            if old != new:
                issues.append(f"{name}: author biographies changed")
            continue
        old_sections = section_texts(name, old)
        new_sections = section_texts(name, new)
        if old_sections.keys() != new_sections.keys():
            issues.append(f"{name}: section headings changed")
            continue
        for title, text in old_sections.items():
            before, after = sentences(text), sentences(new_sections[title])
            unchanged = sum((Counter(before) & Counter(after)).values())
            change_estimates[title] = {
                "original_sentences": len(before),
                "unchanged_exact_sentences": unchanged,
                "estimated_percent_changed": round(100 * (len(before) - unchanged) / len(before)) if before else 0,
            }
    for folder in ("includes", "figures", "template/assets"):
        before = files_before(folder)
        after = {str(p.relative_to(JOURNAL)) for p in (JOURNAL / folder).rglob("*") if p.is_file()}
        if before != after:
            issues.append(f"{folder}: file inventory changed")
        for name in sorted(before & after):
            if read_before(name) != (JOURNAL / name).read_bytes():
                issues.append(f"{name}: protected file changed")
        counts[folder + "_files"] = len(before)
    for name in ("references.bib", "template_compat.tex"):
        if read_before(name) != (JOURNAL / name).read_bytes():
            issues.append(f"{name}: protected file changed")
    result = {
        "baseline_commit": commit,
        "baseline_directory": str(baseline_dir) if args.baseline_dir else None,
        "original_pdf_sha256": hashlib.sha256(read_before("main.pdf")).hexdigest(),
        "revised_pdf_sha256": hashlib.sha256((JOURNAL / "main.pdf").read_bytes()).hexdigest(),
        "checks": "Exact ordered comparisons of citation/reference/label commands, protected environments, and inline math; per-file LaTeX-macro and numeric-literal counts; unchanged main document outside abstract; byte comparisons of bibliography, template, tables and figures.",
        "sentence_method": "Approximate share of original editable sentences without an exact normalized match after revision; protected environments are excluded. This is not a similarity or AI-detection score.",
        "counts": dict(counts),
        "section_changes": change_estimates,
        "conference_prose_overlap": conference_prose_overlap(commit, tex) if commit else None,
        "issues": issues,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"counts": result["counts"], "section_changes": change_estimates, "issues": issues}, indent=2))
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
