"""Build and check the manuscript, without running dataset experiments."""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PAPER = ROOT / "new_paper"
INCLUDES = PAPER / "includes"
RECORDS = HERE / "records"
OUTPUT = ROOT / "build/manuscript_verified"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def mathematical_checks():
    """Independent finite counterexamples/exhaustive checks; no retrieval/model calls."""
    count = 0
    logits = list(itertools.combinations_with_replacement((-2., -1., 0., 1., 2.), 3))
    for old, new in itertools.product(logits, repeat=2):
        ordered = all(a >= b - 1e-12 for a, b in zip(new, old))
        thresholds = all(sum(z >= old[j] - 1e-12 for z in new) >= 3-j for j in range(3))
        require(ordered == thresholds, "Sorted/count constraint equivalence failed")
        count += 1
    # Values close to the tolerance boundary, including repeated thresholds.
    for old in ((0., 0., 1.), (-1., 0., 1.)):
        for delta in (-2e-12, -5e-13, 0., 5e-13):
            new = tuple(v + delta for v in old)
            require(all(a >= b - 1e-12 for a,b in zip(new,old)) ==
                    all(sum(z >= old[j] - 1e-12 for z in new) >= 3-j for j in range(3)), "Tolerance equivalence failed")
            count += 1
    # Exhaustive small-instance quantization checks with independently defined pairs.
    vectors = [(math.cos(i*0.71), math.sin(i*0.71)) for i in range(12)]
    def red(rank):
        return sum(max(0., min(1., sum(a*b for a,b in zip(vectors[i],vectors[j]))))
                   for i,j in itertools.combinations(rank,2))/28
    ranks = [tuple(range(5)) + tail for tail in itertools.combinations(range(5,12),3)]
    for bits in (2,4,8,12,16):
        scale = 2**bits-1
        energies = [sum(round(scale*max(0.,min(1.,sum(a*b for a,b in zip(vectors[i],vectors[j])))))
                        for i,j in itertools.combinations(rank,2)) for rank in ranks]
        for rank, energy in zip(ranks,energies):
            require(abs(energy/(scale*28)-red(rank)) <= 1/(2*scale)+1e-14, "Pair quantization bound failed")
            count += 1
        picked = min(range(len(ranks)),key=lambda i:energies[i])
        require(red(ranks[picked])-min(map(red,ranks)) <= 1/scale+1e-14, "Exact quantized regret bound failed")
        count += 1
    # Same nontrivial prefix, larger tail logits, lower redundancy, but lost recall.
    old_rank = list(range(8)); new_rank = list(range(7)) + [8]
    rel = {0:1,7:1}
    def ndcg5(rank):
        return sum(rel.get(d,0)/math.log2(i+2) for i,d in enumerate(rank[:5]))/(1+1/math.log2(3))
    require(ndcg5(old_rank) == ndcg5(new_rank), "Protected nDCG invariant failed")
    require(sum(d in rel for d in new_rank)/2 < sum(d in rel for d in old_rank)/2, "Recall counterexample failed")
    require(all(a>=b for a,b in zip(sorted([3.,2.,2.5]),sorted([3.,2.,1.]))), "Counterexample logits fail dominance")
    require(21/28 < 1, "Orthogonal replacement must reduce redundancy")
    # Phase flip plus uniform-state reflection sends one marked item out of four to amplitude one.
    phase = [-.5,.5,.5,.5]
    state = [2*sum(phase)/4-a for a in phase]
    require(state == [1.,0.,0.,0.] and sum(a*a for a in state)==1., "Phase/reflection identity failed")
    return {"sorted_count_cases": len(logits)**2+8, "quantization_and_regret_checks": count-len(logits)**2-8,
            "prefix_invariance": True, "recall_counterexample": True, "phase_reflection_identity": True}


def compiled_location(aux, label):
    found = re.search(r"\\newlabel\{"+re.escape(label)+r"\}\{\{([^}]*)\}\{([^}]*)\}",aux)
    require(found is not None, f"Missing compiled label {label}")
    kind = "Table" if label.startswith("tab:") else "Fig." if label.startswith("fig:") else "Section"
    return f"{kind} {found.group(1)}, p. {found.group(2)}"


def reviewer_response(e, aux):
    loc = lambda label: compiled_location(aux,label)
    rows = [
      ("Technical comments 1.1: only two datasets",
       "The evidence now includes all 300 SciFact, 323 NFCorpus, and 648 FiQA test queries, including FiQA's 57,638 parents. "
       + e["configuration_note"] + " The 100-query FiQA confirmation is excluded. " + loc("tab:headline")),
      ("Technical comments 1.2: classical cosine dependence",
       "The manuscript explicitly charges and describes classical dense/BM25 retrieval, neural relevance scoring, and final ordering. "
       "Grover is used for joint subset search, with classical exact/greedy controls and no claim of quantum corpus search. " + loc("sec:method")),
      ("Technical comments 1.3: high P95 simulation latency",
       "Complete online P50/P95 includes original/additional inference, both selection stages, and upstream retrieval wherever used. "
       "Combined selector and refinement-only boundaries are separate. Expanded scoring increases latency versus matched base selection; "
       "matched classical methods are reported without a Grover speed claim. " + loc("tab:latency") + "; " + loc("tab:execution")),
      ("Technical comments 1.4: incomplete hardware",
       "Added Intel Core i7-1355U, 12 logical CPUs, approximately 15.3 GiB RAM, two compute threads, OS/Python/library versions, "
       "warm-up/loading boundaries, shared-host limitations, and full hardware/session records in the companion evidence. " + loc("sec:protocol")),
      ("Technical comments 1.5: advanced neural comparisons",
       "Added pinned MS MARCO MiniLM L2/L6 cross-encoders on dense-fifteen and dense-sixty-four pools, along with hybrid-fifteen L6-only. "
       "The different pools are disclosed. These are specific neural controls, not an exhaustive state-of-the-art survey. " + loc("tab:comparators")),
      ("Technical comments 1.6: figure citations/numbering",
       "The pipeline diagram is explicitly cited before its appearance and uses consistent classical/base/refinement labels. "
       "Figures and tables use LaTeX cross-references and compiled sequential numbering. " + loc("fig:pipeline")),
      ("Technical comments 1.7: conclusion length",
       f"The conclusion is one generated paragraph containing {e['conclusion_word_count']} whitespace-delimited words (150–200 required). " + loc("sec:conclusion")),
      ("Technical comments 2.1: alternative thresholds and no-marked fallback",
       "The already recorded development comparison at cosine thresholds 0.3/0.5/0.7 is summarized with no-marked rates computed "
       "from saved candidates. The frozen winner is retained; no rankings or thresholds were retuned on test judgments. "
       "Adaptive subset-energy marking replaces the static relevance threshold and preserves a feasible incumbent. " + loc("tab:thresholds")),
      ("Technical comments 2.2: score transformation and relevance order",
       "The mechanism was redesigned rather than claiming an optimized probability-to-relevance formula. "
       "Marked states have symmetric ideal amplification; probabilities do not inherently provide graded relevance. "
       "Raw L6 determines base ordering and tail order, while the protected prefix deliberately takes priority over global sorting. "
       "Cosine remains upstream retrieval and redundancy evidence. The original probability-based policy remains a comparator. " + loc("sec:method")),
      ("Technical comments 2.3: candidate/precision circuit resources — PARTIALLY ADDRESSED",
       "Added observed candidate/basis sizes and simulation time, analytical amplitude-storage and signed-register scaling, "
       "explicit objective enumeration, phase/compute-uncompute accounting, and quantization proofs. "
       "A full native constrained-oracle circuit-depth/precision sweep has not been performed. "
       "The paper labels this outstanding and does not reuse incompatible legacy depths as new-method measurements. " +
       loc("tab:resources_observed") + "; " + loc("tab:resources_analytic")),
      ("Technical comments 2.4: additional classical rerankers",
       "Included RRF, independently development-tuned MMR, L6-only, greedy, exact float/integer, and random-search controls. "
       "The aggregate-quality agreement of matched protected controls on SciFact and NFCorpus is reported explicitly. "
       "No uniquely quantum effectiveness gain is asserted. " + loc("tab:comparators")),
      ("Technical comments 2.5: larger document collection",
       "The full 648-query FiQA L6-guided GAS test covers 57,638 parents, versus 5,183 SciFact and 3,633 NFCorpus parents. "
       "This extends domain/classical-corpus coverage, without demonstrating quantum corpus-size scaling. " +
       ("A full FiQA refinement test remains unavailable in this revision. " if not e["runs"]["fiqa"]["refined"] else "") + loc("tab:data")),
    ]
    text = "# Response to technical comments — ICECMSN-1883\n\n"
    text += "Manuscript: **Qubit Chat: A Controlled Evaluation of Grover-Inspired Reranking for Document Retrieval**.\n\n"
    text += ("The revision uses complete verified test runs, without collecting new dataset rankings during manuscript preparation. "
             "The uniform method name does not imply identical configurations. Newer official tests are explicitly follow-up evaluations. "
             "NFCorpus's failed confirmation recall gate and subsequent unchanged-parameter continuation are disclosed in the protocol.\n\n")
    for title, body in rows:
        text += f"## {title}\n\n{body}\n\n"
    text += ("## Evidence and remaining author actions\n\n"
             "`records/evidence.json` and `records/provenance.json` bind values to sealed inputs; `records/all_methods.csv` retains all controls. "
             "Statistical reports preserve numerical ties and complete correction families. The supplied IEEEtran class is unchanged; "
             "the final PDF is checked for page count, fonts, references, and overflow.\n\n"
             "The unperformed native constrained-oracle depth study remains an explicit limitation. "
             + ("The full FiQA refinement test is not included yet. " if not e["runs"]["fiqa"]["refined"] else "") +
             "Local checks do not replace organizer/PDF eXpress acceptance. Nothing has been submitted.\n")
    return text


def package_source():
    """Create an upload ZIP outside the clean LaTeX directory."""
    files = [PAPER / "main.tex", PAPER / "IEEEtran.cls", PAPER / "README.md", *sorted(INCLUDES.glob("*.tex"))]
    archive = HERE / "latex_source.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as handle:
        for path in files:
            handle.write(path, path.relative_to(PAPER))
    with zipfile.ZipFile(archive) as handle:
        require(handle.testzip() is None, "Source ZIP integrity failure")
        for path in files:
            require(hashlib.sha256(handle.read(str(path.relative_to(PAPER)))).hexdigest() == sha(path), "Source ZIP mismatch")
    return {"path": str(archive.relative_to(ROOT)), "sha256": sha(archive), "source_files": len(files),
            "all_main_document_inputs_included": True, "archive_integrity_passed": True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export",action="store_true",help="First regenerate verified inputs (saved rankings only)")
    parser.add_argument("--check-metrics",action="store_true",help="With --export, recheck saved rankings through trec_eval")
    args=parser.parse_args()
    if args.check_metrics and not args.export:
        parser.error("--check-metrics requires --export; it checks existing rankings only")
    if args.export:
        import sys
        subprocess.run([sys.executable,str(HERE/"export_verified_results.py"), *(["--check-metrics"] if args.check_metrics else [])],check=True)
    source=PAPER/"main.tex"
    p=json.loads((RECORDS/"provenance.json").read_text())
    require(p.get("schema")=="qubitchat-manuscript-provenance-v2","Unsupported manuscript provenance")
    require(p["sources_sha256"]==sha(HERE/"paper_sources.json") and p["exporter_sha256"]==sha(HERE/"export_verified_results.py"),"Generated evidence is stale; regenerate it")
    for path,digests in p["inputs"].items():
        require(sha(ROOT/path/"manifest.json")==digests["manifest_sha256"] and sha(ROOT/path/"evaluation.json")==digests["evaluation_sha256"],"Mapped results changed")
    for name,digest in p["generated"].items():
        require(sha(ROOT/name)==digest,f"Generated file changed: {name}")
    template=ROOT/"conference-latex-template/IEEE-conference-template-062824/IEEEtran.cls"
    require(sha(template)==sha(PAPER/"IEEEtran.cls"),"The supplied class must remain unchanged")
    tex=source.read_text()
    require({path.name for path in PAPER.iterdir()}=={"main.tex","main.pdf","IEEEtran.cls","README.md","includes"},
            "The upload folder contains unexpected files")
    require(all(path.is_file() and path.suffix==".tex" for path in INCLUDES.iterdir()),
            "Only LaTeX fragments belong in includes/")
    for name in re.findall(r"\\resultinput\{([^}]+)\}",tex):
        require((INCLUDES/name).is_file(),f"Missing LaTeX input: {name}")
    require(not re.search(r"\\usepackage(?:\[[^]]*\])?\{(?:newtxtext|geometry|cuted)",tex),"Template font/layout override")
    labels=re.findall(r"\\label\{((?:fig|tab):[^}]+)\}",tex)
    require(all(r"\ref{"+label+"}" in tex for label in labels),"Uncited figure/table")
    proofs=mathematical_checks()
    OUTPUT.mkdir(parents=True,exist_ok=True)
    process=subprocess.run([str(ROOT/"build/tools/tectonic"),"--keep-logs","--keep-intermediates","--outdir",str(OUTPUT),str(source)],
                           cwd=PAPER,text=True,capture_output=True)
    (OUTPUT/"build_output.txt").write_text(process.stdout+process.stderr)
    if process.returncode:
        print((process.stdout+process.stderr)[-6000:])
    else:
        print(f"LaTeX completed; complete diagnostics: {OUTPUT / 'build_output.txt'}")
    require(process.returncode==0,"LaTeX build failed; see build_output.txt")
    pdf=OUTPUT/"main.pdf"; aux=(OUTPUT/"main.aux").read_text(); log=(OUTPUT/"main.log").read_text()
    metadata=subprocess.check_output(["pdfinfo",str(pdf)],text=True)
    pages=int(re.search(r"^Pages:\s+(\d+)",metadata,re.M).group(1))
    require(6<=pages<=8,f"Conference page range exceeded: {pages}")
    require(not re.search(r"(?:Citation|Reference) .* undefined|There were undefined|Overfull \\[hv]box",log),"Unresolved reference or overflowing content")
    extracted=subprocess.check_output(["pdftotext","-layout",str(pdf),"-"],text=True)
    require("??" not in extracted and "pending results" not in extracted.lower(),"Unresolved PDF content")
    font_output=subprocess.check_output(["pdffonts",str(pdf)],text=True)
    fonts=[line.split() for line in font_output.splitlines()[2:] if line.strip()]
    require(fonts and all(row[-5]=="yes" for row in fonts),"All PDF fonts must be embedded")
    require(not re.search(r"Type\s+3",font_output),"Bitmap Type 3 font")
    for label in labels:
        compiled_location(aux,label)
    e=json.loads((RECORDS/"evidence.json").read_text())
    # Layout extraction interleaves the right column with the left-column
    # abstract. Count the actual expanded abstract source instead.
    abstract=re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}",tex,re.S).group(1)
    abstract=re.sub(r"\\resultinput\{([^}]+)\}",lambda m:(INCLUDES/m.group(1)).read_text(),abstract)
    abstract_words=len(abstract.split())
    require(abstract_words<=250,f"Abstract exceeds 250 words: {abstract_words}")
    (HERE/"reviewer_response.md").write_text(reviewer_response(e,aux))
    shutil.copy2(pdf,PAPER/"main.pdf")
    checks={"pages":pages,"abstract_words":abstract_words,"abstract_count_method":"Expanded abstract source; PDF layout columns are not mixed",
            "conclusion_words":e["conclusion_word_count"],
            "mathematical_checks":proofs,"supplied_class_sha256":sha(template),"embedded_fonts":True,
            "unresolved_references":False,"overfull_boxes":False,"compiled_labels":{label:compiled_location(aux,label) for label in labels},
            "source_sha256":sha(source),"pdf_sha256":sha(PAPER/"main.pdf"),"builder_sha256":sha(Path(__file__)),
            "provenance_sha256":sha(RECORDS/"provenance.json"),
            "new_rankings_or_model_inference":False,"visual_inspection":"Pending separate page-by-page inspection",
            "latex_archive":package_source()}
    (RECORDS/"publication_checks.json").write_text(json.dumps(checks,indent=2)+"\n")
    print(f"Built and checked {pages} pages; abstract {abstract_words} words; conclusion {e['conclusion_word_count']} words")


if __name__=="__main__":
    main()
