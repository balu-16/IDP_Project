#!/usr/bin/env python3
"""Generate matching LaTeX and editable Word UROP reports from one content set."""

from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Inches, Mm, Pt, RGBColor

ROOT = Path(__file__).resolve().parent
TEX = ROOT / "QubitChat_UROP_Report.tex"
DOCX = ROOT / "QubitChat_UROP_Report.docx"
TITLE = "QubitChat: Intelligent Document Question Answering with Grover-Inspired Evidence Selection"
STUDENTS = [
    ("Bala Rakesh Gundapaneni", "AP23110010003"),
    ("Jagadeeshbabu Borru", "AP23110010058"),
    ("Abdul Basith Syed", "AP23110011061"),
]

ACK = [
    "We express our sincere gratitude to Dr. Naga Sravanthi Puppala for her guidance, encouragement, and support throughout this UROP project. Her feedback helped us frame the research questions, assess the evidence critically, and develop the project as both a working application and a research study.",
    "We thank SRM University-AP and the School of Engineering and Sciences for providing an environment for this work. We also appreciate the cooperation of our team members, whose contributions to application development, experimentation, and analysis made this project possible.",
]

# Explicit page groups keep both formats aligned and leave the contents accurate.
# Each content item is (kind, text); the table and diagram have dedicated kinds.
PAGES = [
    [
        ("h1", "1. Introduction"),
        ("p", "Large collections of PDFs and scanned documents contain useful information, but finding a relevant passage and checking its source can be slow. Retrieval-augmented generation (RAG) addresses this problem by retrieving evidence before generating an answer [1]. The usefulness of such a system depends not only on fluent responses but also on whether its retrieved passages are relevant and traceable to the documents."),
        ("p", "QubitChat is a web prototype that enables users to upload documents, ask natural-language questions, and inspect cited source passages. It combines document extraction, semantic search, optional lexical and neural reranking, and a language model that is instructed to answer from the retrieved evidence. Its interface also supports authenticated sessions and conversation history."),
        ("p", "The research component investigates a related selection problem: a small evidence set may contain several similar passages while omitting other useful information. The project therefore studies relevance and redundancy together, including a Grover-inspired search procedure. The application and the benchmark study are connected, but benchmark outcomes are not guarantees for a user's uploaded files [9]."),
        ("p", "The project's objectives are to make document search easier, preserve a verifiable link between answers and source pages, and compare alternative evidence-selection policies under a fixed result budget. Researchers, students, and other readers can use the prototype to explore documents, while the evaluation investigates when selecting a less redundant evidence set changes retrieval quality."),
        ("h1", "2. Literature Survey"),
        ("p", "RAG combines retrieval with language generation, making external passages available as evidence [1]. Sentence-BERT demonstrated how independently computed sentence embeddings can support semantic similarity search [2]. BM25 provides a complementary lexical signal based on matching query terms [3], while cross-encoders jointly process a query and passage to estimate relevance more precisely at additional inference cost [4]."),
        ("p", "Maximal marginal relevance balances relevance with novelty when constructing a result list [5]. Grover's search and later Grover Adaptive Search describe quantum search under specified oracle assumptions [6, 7]. The project's compact implementation simulates related amplitude operations on a classical computer; it does not execute on a quantum device. The BEIR benchmark supplies diverse information-retrieval collections for evaluating the approach [8]."),
        ("p", "These approaches address different stages of the problem: an embedding model creates a searchable representation; a lexical retriever identifies term matches; a cross-encoder scores relevance; and a selection method chooses the final set. Comparing a proposed selector with classical alternatives is necessary to determine whether an observed change comes from the selection objective or from the search procedure itself."),
    ],
    [
        ("h1", "3. System Model"),
        ("p", "QubitChat has a React and TypeScript frontend and a Python FastAPI backend. Supabase supports authentication and persistent application records, while ChromaDB stores passage vectors. A user's session provides the scope for uploaded files, questions, and cited sources. The main processing flow is shown below."),
        ("p", "The interface supports sign-in, chat creation, document upload, retrieval-method selection, and conversation review. The API checks the authenticated user's session before processing files or returning source content. Uploaded documents have processing states, and only ready documents enter retrieval; users can also remove documents or entire sessions."),
        ("diagram", ""),
        ("h2", "3.1 Document ingestion and indexing"),
        ("p", "A signed-in user uploads a PDF, PNG, or JPEG to a chat session. The backend validates the file and extracts text page by page; scanned content can be processed with Tesseract OCR. Extracted text is split into overlapping, token-aware passages. Each passage retains its document, page, and position metadata so a result can be traced back to its source."),
        ("p", "The all-MiniLM-L6-v2 sentence encoder converts passages into normalized 384-dimensional vectors, which are indexed in ChromaDB alongside their text and metadata. Processing status distinguishes ready documents from failed or incomplete uploads. A session-scoped query considers only eligible documents, and a user can inspect or remove uploaded sources."),
        ("p", "Chunk overlap helps preserve context near passage boundaries. The stored page and position information connects a retrieved excerpt to the original file, while vector similarity makes it possible to find semantically related wording even when a question does not repeat the exact document terms."),
        ("h2", "3.2 Question answering and provenance"),
        ("p", "The user's question is embedded and compared with indexed passages. The selected retrieval method returns evidence and source metadata to the chat service. When configured, Gemini receives the question and excerpts and is instructed to cite the supplied sources or state when the evidence is insufficient. The interface displays the response and citations, while the session records conversation and retrieval provenance. Model availability, OCR quality, and the content of the uploaded files affect the outcome."),
    ],
    [
        ("h2", "3.3 Evidence selection"),
        ("p", "The chat interface initially selects the L6-guided Grover Adaptive Search (GAS) profile; the backend defaults to cosine similarity when no strategy is supplied. Other options include Grover-style classical simulation, analytical amplification, and a classical sampling control. For GAS, dense and BM25 scores form candidate lists, and a MiniLM-L6 cross-encoder estimates query-passage relevance. The base selector chooses eight items from a shortlist of fifteen, when enough candidates are available."),
        ("p", "A refinement retains the first five base results and considers a new three-item tail from an expanded candidate union. It accepts a change only when score constraints hold and measured embedding-based redundancy decreases. Phase marking and amplitude amplification are simulated on a classical machine. Keeping the first five fixed preserves nDCG@5 against the same base ranking, but it does not guarantee unchanged recall or better answers."),
        ("p", "The GAS profile starts from up to 64 dense candidates and forms an expanded union from several hybrid shortlists. Its base objective rewards normalized neural relevance and penalizes pairwise embedding similarity. Refinement applies score bounds derived from the original tail and retains the baseline when no admissible improvement is found. A smaller eligible pool can produce fewer than eight sources. The pinned cross-encoder must be available locally for this profile."),
        ("h2", "3.4 Evaluation and observed results"),
        ("p", "The research study evaluated public BEIR test collections using nDCG@5 for ranking quality, Recall@8 for judged retrieval coverage, and average positive embedding similarity as a redundancy proxy [8, 9]. The table reports the selected full-test configurations; the FiQA row uses the earlier base method rather than the protected refinement."),
        ("results", ""),
        ("p", "Against matched base selection, protected refinement reduced mean redundancy by 3.21% on SciFact and 2.63% on NFCorpus; their mean recall changed by -0.93% and +1.95% relative, respectively. Matched greedy and exact classical refiners reached the same aggregate quality on these two tests. A separate FiQA refinement follow-up reduced redundancy by 8.23% but recall fell by 2.60% relative, exceeding its 2% allowance and failing the frozen gate [9]."),
        ("p", "These are retrieval-study findings on parent documents and representative passages, not a measurement of generated-answer quality or an accuracy guarantee for uploaded PDFs. Results average five search seeds within each query. Additional neural scoring increased full-pipeline latency relative to matched base selection; timings on a shared host do not establish a universal speed comparison."),
    ],
    [
        ("h1", "4. Concluding Remarks"),
        ("p", "QubitChat brings document processing, semantic retrieval, cited answer generation, and session management into one prototype. Its research study shows that constrained selection can lower an embedding-based redundancy measure while preserving a chosen ranking prefix. Recall can still decrease, and comparable classical optimizers achieved the same aggregate quality in the protected tests. The results do not establish a physical quantum speedup or an improvement in generated-answer quality."),
        ("h1", "5. Future Work"),
        ("p", "Future work should evaluate citation accuracy, answer factuality, and usefulness with real users and diverse uploaded documents. Further retrieval studies should use untouched domains, stronger rerankers, and predefined recall criteria. Improved OCR, multilingual support, and production-scale performance evaluation are also valuable. Any quantum implementation should separately account for state preparation, data access, hardware noise, and end-to-end cost."),
        ("h1", "References"),
        ("ref", "[1] P. Lewis et al., \"Retrieval-augmented generation for knowledge-intensive NLP tasks,\" Advances in Neural Information Processing Systems, vol. 33, 2020, pp. 9459-9474."),
        ("ref", "[2] N. Reimers and I. Gurevych, \"Sentence-BERT: Sentence embeddings using Siamese BERT-networks,\" EMNLP-IJCNLP, 2019, pp. 3982-3992. doi:10.18653/v1/D19-1410."),
        ("ref", "[3] S. Robertson and H. Zaragoza, \"The probabilistic relevance framework: BM25 and beyond,\" Foundations and Trends in Information Retrieval, vol. 3, no. 4, 2009, pp. 333-389."),
        ("ref", "[4] R. Nogueira and K. Cho, \"Passage re-ranking with BERT,\" arXiv:1901.04085, 2019."),
        ("ref", "[5] J. Carbonell and J. Goldstein, \"The use of MMR, diversity-based reranking for reordering documents and producing summaries,\" ACM SIGIR, 1998, pp. 335-336."),
        ("ref", "[6] L. K. Grover, \"A fast quantum mechanical algorithm for database search,\" ACM STOC, 1996, pp. 212-219. doi:10.1145/237814.237866."),
        ("ref", "[7] A. Gilliam, S. Woerner, and C. Gonciulea, \"Grover Adaptive Search for constrained polynomial binary optimization,\" Quantum, vol. 5, art. 428, 2021. doi:10.22331/q-2021-04-08-428."),
        ("ref", "[8] N. Thakur et al., \"BEIR: A heterogeneous benchmark for zero-shot evaluation of information retrieval models,\" NeurIPS Datasets and Benchmarks Track, 2021."),
        ("ref", "[9] B. R. Gundapaneni, A. B. Syed, J. Borru, and N. S. Puppala, \"Qubit Chat: A Controlled Evaluation of Grover-Inspired Reranking for Document Retrieval,\" project manuscript and supporting evidence, 2026."),
    ],
]

RESULTS = [
    ("Collection (test queries)", "Configuration", "nDCG@5", "Recall@8"),
    ("SciFact (300)", "Protected refinement", "0.6878", "0.8011"),
    ("NFCorpus (323)", "Protected refinement", "0.3689", "0.1530"),
    ("FiQA (648)", "Earlier base", "0.3575", "0.4341"),
]

# Rebalance the original shared content across seven pages.  The first group
# follows the contents and acknowledgements on page 2.  Both output formats
# use these same groups, figures, captions and page references.
_INTRO, _SYSTEM, _METHOD, _CLOSING = PAGES
PAGES = [
    _INTRO[:5] + [
        ("p", "The prototype connects the reader's question to the evidence used in an answer: each selected passage retains a document and page reference. The study evaluates the retrieval stage independently, enabling the team to examine relevance, repeated evidence, and processing cost before drawing conclusions about the whole application."),
    ],
    _INTRO[5:] + [
        ("p", "Embedding retrieval can compare a question with many cached passage vectors, whereas a cross-encoder must process each question-passage pair. A two-stage pipeline therefore first narrows the search and then applies the more expensive model to a smaller set. This design can save scoring work, but an item excluded from the first-stage pool cannot be recovered by a later reranker."),
        ("p", "The quantum-search literature counts oracle queries under a specified access model. In a practical retrieval system, embedding, candidate construction, neural scoring, objective preparation, and measurement also contribute to cost. An ideal oracle-query bound should not be confused with a measured end-to-end runtime or the cost of a classical simulation [6, 7, 9]."),
        ("p", "Lexical and semantic matching can complement one another. A lexical score responds to matching words and their frequency, while a dense vector can capture similarity between differently worded passages. Hybrid candidate construction combines these signals before the cross-encoder evaluates individual query-passage pairs. The mixture can change which evidence is available to subsequent selection."),
        ("p", "A relevance-only ranking can return passages that are individually plausible but very similar to one another. Diversity-oriented methods instead consider how a new item relates to the items already chosen. This introduces a trade-off: reducing similarity may create room for different evidence, but it can also displace a relevant passage if the relevance model is mistaken [5]."),
        ("p", "Evaluation therefore needs several measures. nDCG emphasizes the position of judged-relevant results; recall measures the fraction of relevant items recovered within a fixed output budget. Embedding similarity is used here as a redundancy proxy, not as a direct measurement of factual repetition, coverage of an answer, or hallucination. These quantities address related but different questions."),
    ] + _SYSTEM[:2],
    _SYSTEM[2:] + _METHOD[:4] + [
        ("p", "Each search stage starts from an incumbent candidate set and uses bounded trials, phase calls, and a time limit. The refinement retains the original tail if it finds no admissible reduction in redundancy. Its selected evidence and timings are recorded with the response, making it possible to identify which method was requested and how the source set was produced."),
    ],
    _METHOD[4:6] + [
        ("p", "SciFact, NFCorpus, and FiQA represent scientific, biomedical, and financial retrieval tasks. Their full test sets contain 300, 323, and 648 queries, respectively. The study compares the selected GAS policy with lexical, dense, neural, greedy, and exact controls; it averages the five search seeds within each query before averaging across queries [9]."),
        _METHOD[6],
        _METHOD[7],
        ("chart_tradeoffs", "Figure 1. Recall@8 and redundancy for recorded retrieval policies [10]. Candidate pools differ; coincident points may overlap, and the figure does not establish a universal ranking of methods."),
        ("p", "Figure 1 shows the relevance-redundancy trade-off: a lower similarity score does not by itself mean that an evidence set contains more judged-relevant material. The protected SciFact and NFCorpus results preserve the first five outputs by construction; the displayed FiQA result uses the earlier base configuration."),
        ("p", "The matched greedy and exact-float refiners use the same protected prefix, candidate domain, relevance constraints, and redundancy objective as the refined GAS policy. Their matching aggregate results on SciFact and NFCorpus support the selection formulation; they do not identify an additional effectiveness gain caused by amplitude amplification."),
        ("p", "Other comparison points use different candidate pools. A dense-sixty-four cross-encoder sees more initial opportunities than a hybrid-fifteen policy, but it must also score more candidates. The chart is a descriptive view of these recorded configurations, not a controlled comparison that isolates every design choice [10]."),
    ],
    [
        ("h2", "3.5 Query outcomes and resource observations"),
        ("p", "Aggregate averages can hide individual losses. Relative to the matched base, protected refinement improved Recall@8 for 2 SciFact queries, left 293 tied, and reduced it for 5. For NFCorpus, 15 queries improved, 295 tied, and 13 declined. Redundancy fell for 158 SciFact and 135 NFCorpus queries and increased for none under the stated acceptance rule [9]."),
        ("p", "Candidate availability also limits every selector. The average judged Recall@8 ceiling for the hybrid fifteen was 0.8569 on SciFact and 0.1725 on NFCorpus; the expanded union raised those relaxed ceilings to 0.8903 and 0.1942. These are optimistic bounds under the available judgments, not performance guarantees for the constrained policy."),
        ("chart_cost", "Figure 2. Mean composed online time per seeded request, separated into retrieval, neural inference, and selection stages [10]. The FiQA bar represents its earlier base policy."),
        ("p", "Figure 2 attributes arithmetic mean time to measured stages. Original L6 inference accounts for 64.0% of the SciFact, 71.3% of the NFCorpus, and 64.8% of the FiQA primary means; additional L6 scoring contributes to the two refined pipelines. These are shared-host measurements, not controlled speed comparisons across datasets."),
        ("p", "The combined base and refinement selector represents only 0.67%, 0.88%, and 0.61% of those respective mean times. Reducing the selector alone therefore leaves the larger retrieval and neural stages. The compact simulator enumerates its encoded objective and does not demonstrate physical quantum acceleration, energy savings, or a lower monetary cost."),
        ("p", "A preserved prefix does not prevent a relevant tail item from being replaced. In one retrospectively selected SciFact case, the only judged-relevant output was lost even though top-five ranking and the candidate-pool ceiling were unchanged. This example illustrates a possible failure mode; it is not representative of every query [10]."),
        ("p", "The recorded recall-retention gate is a descriptive mean-based criterion, not a prospective statistical noninferiority test. Some confidence intervals include both gains and losses, and the prior use of test outcomes during development limits confirmatory claims. Future studies should retain these negative outcomes and specify success criteria before evaluation."),
        ("p", "The hybrid shortlist contained no positively judged parent for 40 SciFact, 91 NFCorpus, and 203 FiQA queries. Selection cannot recover a judged-relevant item that is absent from its input pool; expanding within the dense top 64 can help only when that larger pool already contains the item. These counts depend on the available judgments [10]."),
    ],
    _CLOSING[:2] + [
        ("p", "The evaluation separates guarantees from observations. Protecting the first five positions guarantees the same nDCG@5 as the corresponding base ranking, but score constraints do not guarantee the relevance of a replacement tail. The failed FiQA follow-up and the query-level recall losses demonstrate why both aggregate and individual outcomes matter."),
    ] + _CLOSING[2:4] + [
        ("p", "A prospective user study could assess whether the cited passages actually support each response and whether readers can locate the evidence efficiently. Retrieval experiments should also compare modern rerankers, measure the full latency of each policy, and report query-level failures rather than relying on a single average."),
        ("p", "For the application, further work can examine extraction quality on complex tables, poor scans, and multilingual documents, alongside recovery from processing errors. A production evaluation should measure concurrent use and document lifecycle behavior, and should review the privacy implications of sending retrieved excerpts to an external generation service."),
    ] + _CLOSING[4:] + [
        ("ref", "[10] B. R. Gundapaneni, A. B. Syed, J. Borru, and N. S. Puppala, \"Grover-Inspired Evidence Selection for Document Retrieval: Relevance Constraints, Failure Analysis, and Resource Accounting,\" journal manuscript and supporting evidence, 2026."),
    ],
]

CONTENTS = [
    ("Table of Contents", "2"),
    ("Acknowledgements", "2"),
    ("1. Introduction", "2"),
    ("2. Literature Survey", "3"),
    ("3. System Model", "3"),
    ("3.1 Document ingestion and indexing", "4"),
    ("3.2 Question answering and provenance", "4"),
    ("3.3 Evidence selection", "4"),
    ("3.4 Evaluation and observed results", "5"),
    ("3.5 Query outcomes and resource observations", "6"),
    ("4. Concluding Remarks", "7"),
    ("5. Future Work", "7"),
    ("References", "7"),
]


def tex_escape(value):
    mapping = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    return "".join(mapping.get(c, c) for c in value)


def generate_tex():
    result = [r"""\documentclass[11pt,a4paper]{article}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\renewcommand{\rmdefault}{ptm}
\usepackage{graphicx}
\usepackage[a4paper,left=21mm,right=21mm,top=21mm,bottom=21mm,footskip=10mm]{geometry}
\setlength{\parindent}{0pt}
\setlength{\parskip}{5pt}
\emergencystretch=2em
\setlength{\fboxrule}{0.6pt}
\pagestyle{plain}
\makeatletter
\newcommand{\LenToUnit}[1]{\strip@pt\dimexpr#1\relax}
\makeatother
% Draw the same border on every shipped page, including the cover.
\AddToHook{shipout/background}{%
  \setlength{\unitlength}{1pt}%
  \put(25,-\LenToUnit{\dimexpr\paperheight-25pt\relax}){%
    \framebox(\LenToUnit{\dimexpr\paperwidth-50pt\relax},\LenToUnit{\dimexpr\paperheight-50pt\relax}){}}}
\newcommand{\reportheading}[1]{\par\vspace{4pt}{\large\bfseries #1}\par\vspace{1pt}}
\newcommand{\reportsubheading}[1]{\par\vspace{2pt}{\normalsize\bfseries #1}\par}
\begin{document}
\begingroup
\fontsize{15}{18}\selectfont
\begin{center}
\vspace*{5mm}
{\fontsize{19}{23}\selectfont\bfseries """ + tex_escape(TITLE) + r"""\par}
\vfill
UROP Project submitted to the\\
{\bfseries SRM University -- AP, Andhra Pradesh}\\[2mm]
for the partial fulfillment of the requirements to award the degree of\\[1mm]
{\bfseries Bachelor of Technology in\\ Computer Science and Engineering}\\[2mm]
School of Engineering and Sciences\par
\vfill
{\bfseries Submitted by}\\[1mm]
"""]
    result.extend(tex_escape(name) + " \\textbar{} " + tex_escape(student_id) + r"\\" + "\n" for name, student_id in STUDENTS)
    result.append(r"""\vfill
\includegraphics[width=32mm]{srm_emblem.png}\\[4mm]
\vfill
{\bfseries Under the Guidance of}\\[1mm]
Dr. Naga Sravanthi Puppala\par
\vfill
{\bfseries SRM University--AP}\\
Neerukonda, Mangalagiri, Guntur\\
Andhra Pradesh -- 522 240\par
\vfill
November, 2026\par
\vspace*{2mm}
\end{center}
\endgroup
\newpage
\reportheading{Table of Contents}
""")
    for name, number in CONTENTS:
        result.append(tex_escape(name) + r"\dotfill " + number + r"\\[1pt]" + "\n")
    result.append("\\reportheading{Acknowledgements}\n")
    result.extend(tex_escape(p) + "\n\n" for p in ACK)
    for page_index, page in enumerate(PAGES):
        if page_index:
            result.append("\\newpage\n")
        if page_index == 1:
            result.append("\\begingroup\\linespread{1.13}\\selectfont\n")
        for kind, value in page:
            if kind == "h1":
                result.append("\\reportheading{" + tex_escape(value) + "}\n")
            elif kind == "h2":
                result.append("\\reportsubheading{" + tex_escape(value) + "}\n")
            elif kind == "p":
                result.append(tex_escape(value) + "\n\n")
            elif kind == "ref":
                result.append(r"{\raggedright\fontsize{10.3}{11.7}\selectfont " + tex_escape(value) + r"\par}" + "\n")
            elif kind == "diagram":
                result.append(r"""\begin{center}
\setlength{\fboxsep}{5pt}
\fbox{\parbox{0.90\linewidth}{\centering
\textbf{Upload PDF / image} $\rightarrow$ \textbf{Extract / OCR} $\rightarrow$ \textbf{Chunk, embed and index}\\[3pt]
$\downarrow$\\[3pt]
\textbf{Question} $\rightarrow$ \textbf{Retrieve and select evidence} $\rightarrow$ \textbf{Answer with citations}}}
\end{center}
""")
            elif kind == "results":
                result.append(r"\begin{center}\small\setlength{\tabcolsep}{5pt}\begin{tabular}{llrr}\hline" + "\n")
                for row_index, row in enumerate(RESULTS):
                    result.append(" & ".join((r"\textbf{" + tex_escape(cell) + "}") if row_index == 0 else tex_escape(cell) for cell in row) + r"\\" + (r"\hline" if row_index == 0 else "") + "\n")
                result.append(r"\hline\end{tabular}\end{center}" + "\n")
            elif kind in {"chart_tradeoffs", "chart_cost"}:
                image = "observed_tradeoffs.pdf" if kind == "chart_tradeoffs" else "cost_decomposition.pdf"
                result.append("\\begin{center}\\includegraphics[width=0.98\\linewidth]{" + image + "}\\par\n")
                result.append(r"{\fontsize{9.5}{11}\selectfont " + tex_escape(value) + r"\par}\end{center}" + "\n")
        if page_index == 1:
            result.append("\\par\\endgroup\n")
    result.append("\\end{document}\n")
    TEX.write_text("".join(result), encoding="utf-8")


def shade(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def set_repeat_table_header(row):
    tr_pr = row._tr.get_or_add_trPr()
    tr_pr.append(OxmlElement("w:tblHeader"))


def add_field(paragraph, instruction):
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    text = OxmlElement("w:instrText")
    text.set(qn("xml:space"), "preserve")
    text.text = f" {instruction} "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    cached = OxmlElement("w:t")
    cached.text = "1"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for element in (begin, text, separate, cached, end):
        run._r.append(element)


def add_border(section):
    sect_pr = section._sectPr
    borders = OxmlElement("w:pgBorders")
    borders.set(qn("w:offsetFrom"), "page")
    for side in ("top", "left", "bottom", "right"):
        item = OxmlElement("w:" + side)
        for attr, value in (("val", "single"), ("sz", "5"), ("space", "25"), ("color", "000000")):
            item.set(qn("w:" + attr), value)
        borders.append(item)
    sect_pr.append(borders)


def generate_docx():
    doc = Document()
    doc.core_properties.title = TITLE
    doc.core_properties.author = "; ".join(name for name, _ in STUDENTS)
    section = doc.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    section.left_margin = section.right_margin = Mm(21)
    section.top_margin = section.bottom_margin = Mm(21)
    section.footer_distance = Mm(12)
    add_border(section)

    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(11.5)
    normal.paragraph_format.space_after = Pt(5)
    normal.paragraph_format.line_spacing = 1.07
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.paragraph_format.space_after = Pt(0)
    add_field(footer, "PAGE")

    def paragraph(text="", *, size=None, bold=False, center=False, before=0, after=5, style=None):
        p = doc.add_paragraph(style=style)
        p.paragraph_format.space_before = Pt(before)
        p.paragraph_format.space_after = Pt(after)
        p.paragraph_format.widow_control = False
        if center:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(text)
        r.bold = bold
        if size:
            r.font.size = Pt(size)
        return p

    def heading(text, level=1):
        p = paragraph(text, size=13 if level == 1 else 11.5, bold=True,
                      before=5 if level == 1 else 3, after=4 if level == 1 else 2)
        p.paragraph_format.keep_with_next = True
        p.style = doc.styles[f"Heading {level}"]
        for run in p.runs:
            run.font.name = "Times New Roman"
            run.font.color.rgb = RGBColor(0, 0, 0)
            run.font.size = Pt(13 if level == 1 else 11.5)
        return p

    paragraph(TITLE, size=19, bold=True, center=True, before=10, after=32)
    paragraph("UROP Project submitted to the", size=15, center=True, after=2)
    paragraph("SRM University - AP, Andhra Pradesh", size=15, bold=True, center=True, after=5)
    paragraph("for the partial fulfillment of the requirements to award the degree of", size=15, center=True, after=4)
    paragraph("Bachelor of Technology in\nComputer Science and Engineering", size=15, bold=True, center=True, after=4)
    paragraph("School of Engineering and Sciences", size=15, center=True, after=56)
    paragraph("Submitted by", size=15, bold=True, center=True, after=4)
    for index, (name, student_id) in enumerate(STUDENTS):
        paragraph(f"{name} | {student_id}", size=15, center=True, after=24 if index == len(STUDENTS)-1 else 1)
    picture = doc.add_paragraph()
    picture.alignment = WD_ALIGN_PARAGRAPH.CENTER
    picture.paragraph_format.space_before = Pt(24)
    picture.paragraph_format.space_after = Pt(30)
    picture.add_run().add_picture(str(ROOT / "srm_emblem.png"), width=Mm(32))
    paragraph("Under the Guidance of", size=15, bold=True, center=True, after=4)
    paragraph("Dr. Naga Sravanthi Puppala", size=15, center=True, after=55)
    paragraph("SRM University-AP", size=15, bold=True, center=True, after=2)
    paragraph("Neerukonda, Mangalagiri, Guntur\nAndhra Pradesh - 522 240", size=15, center=True, after=25)
    paragraph("November, 2026", size=15, center=True, after=0)
    doc.add_page_break()
    heading("Table of Contents")
    toc = doc.add_table(rows=0, cols=2)
    toc.autofit = False
    toc.columns[0].width, toc.columns[1].width = Mm(150), Mm(15)
    for label, number in CONTENTS:
        cells = toc.add_row().cells
        cells[0].width, cells[1].width = Mm(150), Mm(15)
        cells[0].text, cells[1].text = label, number
        cells[1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
        for cell in cells:
            for p in cell.paragraphs:
                p.paragraph_format.space_after = Pt(1)
    heading("Acknowledgements")
    for text in ACK:
        paragraph(text)
    for page_index, page in enumerate(PAGES):
        if page_index:
            doc.add_page_break()
        for kind, value in page:
            if kind == "h1":
                heading(value)
            elif kind == "h2":
                heading(value, 2)
            elif kind == "p":
                paragraph(value)
            elif kind == "ref":
                paragraph(value, size=10.3, after=2)
            elif kind == "diagram":
                table = doc.add_table(rows=2, cols=1)
                table.alignment = WD_TABLE_ALIGNMENT.CENTER
                table.style = "Table Grid"
                table.cell(0, 0).text = "Upload PDF / image  →  Extract / OCR  →  Chunk, embed and index"
                table.cell(1, 0).text = "Question  →  Retrieve and select evidence  →  Answer with citations"
                for row in table.rows:
                    for cell in row.cells:
                        shade(cell, "F2F2F2")
                        for p in cell.paragraphs:
                            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                            p.paragraph_format.space_after = Pt(2)
                            for run in p.runs:
                                run.bold = True
                                run.font.size = Pt(9)
                paragraph("", after=0).paragraph_format.line_spacing = Pt(2)
            elif kind == "results":
                table = doc.add_table(rows=0, cols=4)
                table.style = "Table Grid"
                table.alignment = WD_TABLE_ALIGNMENT.CENTER
                for i, row in enumerate(RESULTS):
                    cells = table.add_row().cells
                    if i == 0:
                        set_repeat_table_header(table.rows[-1])
                    for cell, text in zip(cells, row):
                        cell.text = text
                        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                        if i == 0:
                            shade(cell, "E9E9E9")
                        for p in cell.paragraphs:
                            p.paragraph_format.space_after = Pt(0)
                            for run in p.runs:
                                run.font.size = Pt(9)
                                run.bold = i == 0
                paragraph("", after=0).paragraph_format.line_spacing = Pt(2)
            elif kind in {"chart_tradeoffs", "chart_cost"}:
                image = "observed_tradeoffs.png" if kind == "chart_tradeoffs" else "cost_decomposition.png"
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.space_after = Pt(1)
                p.add_run().add_picture(str(ROOT / image), width=Mm(162))
                paragraph(value, size=9.5, center=True, after=4)
    settings = doc.settings.element
    update_fields = OxmlElement("w:updateFields")
    update_fields.set(qn("w:val"), "true")
    settings.append(update_fields)
    doc.save(DOCX)


if __name__ == "__main__":
    generate_tex()
    generate_docx()
    print(f"Generated {TEX.name} and {DOCX.name}")
