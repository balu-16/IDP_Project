"""Build BibTeX from publisher-deposited metadata and explicit primary records."""
from concurrent.futures import ThreadPoolExecutor
import html
import json
from pathlib import Path
import urllib.parse
import urllib.request
import urllib.error
import time

JOURNAL = Path(__file__).resolve().parents[1]
ROOT = JOURNAL.parents[1]
DOIS = {
    "grover1996search":"10.1145/237814.237866", "brassard2002amplitude":"10.1090/conm/305/05215",
    "gilliam2021gas":"10.22331/q-2021-04-08-428", "bartschi2019dicke":"10.1007/978-3-030-25027-0_9",
    "montanaro2016quantum":"10.1038/npjqi.2015.23", "carbonell1998mmr":"10.1145/290941.291025",
    "cormack2009rrf":"10.1145/1571941.1572114", "robertson2009bm25":"10.1561/1500000019",
    "reimers2019sentencebert":"10.18653/v1/D19-1410", "devlin2019bert":"10.18653/v1/N19-1423",
    "karpukhin2020dpr":"10.18653/v1/2020.emnlp-main.550", "khattab2020colbert":"10.1145/3397271.3401075",
    "nogueira2020seq2seq":"10.18653/v1/2020.findings-emnlp.63", "wadden2020scifact":"10.18653/v1/2020.emnlp-main.609",
    "boteva2016nfcorpus":"10.1007/978-3-319-30671-1_58", "maia2018fiqa":"10.1145/3184558.3192301",
    "jarvelin2002gain":"10.1145/582415.582418", "smucker2007tests":"10.1145/1321440.1321528",
    "dror2018harnessing":"10.18653/v1/P18-1128", "vidal2003simulation":"10.1103/PhysRevLett.91.147902",
    "norimoto2024gas":"10.1109/ACCESS.2024.3413084", "ominato2024gas":"10.1109/ACCESS.2024.3403200",
    "elkiran2026evaluation":"10.1109/ACCESS.2026.3664852", "sun2023rankgpt":"10.18653/v1/2023.emnlp-main.923",
    "abdallah2025rerankers":"10.18653/v1/2025.findings-emnlp.305", "kulesza2012dpp":"10.1561/2200000044",
}


def tex(value):
    return html.unescape(str(value)).replace('®','').replace("&", r"\&").replace("%", r"\%").replace("_", r"\_").replace("–", "--").replace("—", "---")


def entry(key, kind, fields):
    return "@"+kind+"{"+key+",\n"+",\n".join("  "+k+" = {"+str(v)+"}" for k,v in fields.items() if v not in [None,""])+"\n}\n"


def fetch(item):
    key,doi=item
    url="https://api.crossref.org/works/"+urllib.parse.quote(doi,safe="")
    request=urllib.request.Request(url,headers={"User-Agent":"QubitChat journal bibliography verification"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request,timeout=25) as response: record=json.load(response)["message"]
            break
        except urllib.error.HTTPError as error:
            if error.code not in {429, 502, 503, 504} or attempt == 4:
                raise
            time.sleep(min(10, 2 * (attempt+1)))
    return key,(url,record)


def main():
    target=JOURNAL/'evidence/bibliography_metadata.json'
    records=json.loads(target.read_text()) if target.exists() else {}
    verified=json.loads((ROOT/'manuscript_support/records/bibliography_sources.json').read_text())
    for key,value in verified['new_sources'].items():
        source=value.get('publisher_registered_metadata')
        if key in DOIS and key not in records and source:
            records[key]={'primary_metadata_url':source['source_url'],'metadata':{
                'author':source['authors'],'title':source['title'],'container-title':source['container'],
                'volume':source.get('volume'),'issue':source.get('issue'),'page':source.get('page'),
                'article-number':source.get('article-number'),'published':source['published'],
                'type':'journal-article' if key in {'jarvelin2002gain','vidal2003simulation'} else 'proceedings-article'}}
    target.write_text(json.dumps(records,indent=2)+'\n')
    todo=[item for item in DOIS.items() if item[0] not in records]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for key,(url,record) in pool.map(fetch,todo):
            records[key]={"primary_metadata_url":url,"metadata":record}
            target.write_text(json.dumps(records,indent=2)+'\n')
    entries=[]
    for key,doi in DOIS.items():
        r=records[key]['metadata']
        authors=' and '.join(tex(a.get('family',a.get('name','')))+(', '+tex(a['given']) if a.get('given') else '') for a in r.get('author',[]))
        title=r['title'][0]
        if r.get('subtitle'):title+=': '+r['subtitle'][0]
        date=r.get('published',r.get('published-print',r.get('published-online')))['date-parts'][0]
        fields=dict(author=authors,title='{'+tex(title)+'}',year=date[0])
        kind='article' if r['type']=='journal-article' else 'inproceedings'
        fields['journal' if kind=='article' else 'booktitle']=tex(r['container-title'][0 if kind=='article' else -1])
        if r.get('volume'):fields['volume']=tex(r['volume'])
        if kind=='article' and r.get('issue'):fields['number']=tex(r['issue'])
        if r.get('page'):fields['pages']=r['page'].replace('–','--').replace('-','--')
        elif r.get('article-number'):fields['pages']=r['article-number']
        fields['doi']=doi
        fields['note']='doi: '+r'\nolinkurl{'+doi+'}'
        # Primary-paper/author records take precedence over erroneous DOI deposits.
        if key=='robertson2009bm25':
            fields.update(volume='3',number='4',pages='333--389')
        if key=='reimers2019sentencebert':fields['pages']='3982--3992'
        if key=='brassard2002amplitude':fields.update(booktitle='Quantum Computation and Information',series='Contemporary Mathematics',volume='305')
        entries.append(entry(key,kind,fields))
    explicit={
      'conference2026':('unpublished',dict(author='Bala Rakesh Gundapaneni and Abdul Basith Syed and Jagadeeshbabu Borru and Naga Sravanthi Puppala',title='{Qubit Chat: A Controlled Evaluation of Grover-Inspired Reranking for Document Retrieval}',year='2026',note='Accepted for the 6th International Conference on Evolutionary Computing and Mobile Sustainable Networks (ICECMSN); conference manuscript, awaiting publication')),
      'lewis2020retrieval':('inproceedings',dict(author='Patrick Lewis and Ethan Perez and Aleksandra Piktus and Fabio Petroni and Vladimir Karpukhin and Naman Goyal and Heinrich K{\\"u}ttler and Mike Lewis and Wen-tau Yih and Tim Rockt{\\"a}schel and Sebastian Riedel and Douwe Kiela',title='{Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks}',booktitle='Advances in Neural Information Processing Systems',volume='33',pages='9459--9474',year='2020',url='https://proceedings.neurips.cc/paper/2020/hash/6b493230205f780e1bc26945df7481e5-Abstract.html')),
      'wang2020minilm':('inproceedings',dict(author='Wenhui Wang and Furu Wei and Li Dong and Hangbo Bao and Nan Yang and Ming Zhou',title='{MiniLM: Deep Self-Attention Distillation for Task-Agnostic Compression of Pre-Trained Transformers}',booktitle='Advances in Neural Information Processing Systems',volume='33',pages='5776--5788',year='2020',url='https://arxiv.org/abs/2002.10957')),
      'thakur2021beir':('inproceedings',dict(author='Nandan Thakur and Nils Reimers and Andreas R{\\"u}ckl{\\\'e} and Abhishek Srivastava and Iryna Gurevych',title='{BEIR: A Heterogeneous Benchmark for Zero-shot Evaluation of Information Retrieval Models}',booktitle='Proceedings of the Neural Information Processing Systems Datasets and Benchmarks Track',year='2021',url='https://arxiv.org/abs/2104.08663')),
      'boyer1998tight':('article',dict(author='Michel Boyer and Gilles Brassard and Peter H{\\o}yer and Alain Tapp',title='{Tight Bounds on Quantum Searching}',journal='Fortschritte der Physik',volume='46',number='4--5',pages='493--505',year='1998',url='https://arxiv.org/abs/quant-ph/9605034')),
      'durr1996minimum':('misc',dict(author='Christoph D{\\"u}rr and Peter H{\\o}yer',title='{A Quantum Algorithm for Finding the Minimum}',year='1996',howpublished='arXiv:quant-ph/9607014',url='https://arxiv.org/abs/quant-ph/9607014')),
      'nogueira2019bert':('misc',dict(author='Rodrigo Nogueira and Kyunghyun Cho',title='{Passage Re-ranking with BERT}',year='2019',howpublished='arXiv:1901.04085',url='https://arxiv.org/abs/1901.04085')),
      'bajaj2016msmarco':('misc',dict(author='Palash Bajaj and others',title='{MS MARCO: A Human Generated MAchine Reading COmprehension Dataset}',year='2016',howpublished='arXiv:1611.09268',url='https://arxiv.org/abs/1611.09268')),
      'javadi2024qiskit':('misc',dict(author='Ali Javadi-Abhari and others',title='{Quantum Computing with Qiskit}',year='2024',howpublished='arXiv:2405.08810',url='https://arxiv.org/abs/2405.08810')),
      'holm1979multiple':('article',dict(author='Sture Holm',title='{A Simple Sequentially Rejective Multiple Test Procedure}',journal='Scandinavian Journal of Statistics',volume='6',number='2',pages='65--70',year='1979',url='https://www.jstor.org/stable/4615733')),
      'minilm_model':('misc',dict(author='{Sentence Transformers}',title='{all-MiniLM-L6-v2 Model Card}',howpublished='Hugging Face',url='https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2',note='Accessed: Oct. 24, 2026')),
      'crossencoder_models':('misc',dict(author='{Sentence Transformers}',title='{MS MARCO MiniLM Cross-Encoder Model Cards}',howpublished='Hugging Face',url='https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2',note='L2 control: https://huggingface.co/cross-encoder/ms-marco-MiniLM-L2-v2. Accessed: Oct. 24, 2026')),
      'trec_eval':('misc',dict(author='{National Institute of Standards and Technology}',title='{trec\\_eval}',url='https://github.com/usnistgov/trec_eval',note='Accessed: Oct. 24, 2026')),
    }
    requested_path = ROOT / 'manuscript_support/records/requested_references.json'
    requested = json.loads(requested_path.read_text())
    for key, source in requested['sources'].items():
        explicit[key] = (source['bibtex_type'], source['bibtex_fields'])
    entries.extend(entry(key,*value) for key,value in explicit.items())
    (JOURNAL/'references.bib').write_text('% Publisher-deposited metadata and primary records; see evidence/bibliography_metadata.json.\n\n'+'\n'.join(entries))
    (JOURNAL/'evidence/bibliography_primary_records.json').write_text(json.dumps({key:fields for key,(_,fields) in explicit.items()},indent=2)+'\n')
    (JOURNAL/'evidence/bibliography_corrections.json').write_text(json.dumps({
        'robertson2009bm25':{'corrected':{'volume':'3','number':'4','pages':'333--389'},'primary_source':'https://www.staff.city.ac.uk/~sbrp622/pubs.html','paper_pdf':'https://www.ccs.neu.edu/home/vip/teach/IRcourse/IR_surveys/robertson_foundations.pdf','reason':'DOI deposit incorrectly supplies volume 4, numbers 1–2, pages 1–174'},
        'reimers2019sentencebert':{'corrected':{'pages':'3982--3992'},'primary_source':'https://aclanthology.org/D19-1410/','reason':'DOI deposit incorrectly supplies pages 3980–3990'},
        'venue_formatting':'Use actual book title rather than series title for proceedings; decode HTML entities; omit journal trademark glyphs; retain DOI metadata and display DOI through the standard note field supported by IEEEtran.bst.'},indent=2)+'\n')
    print('Wrote',len(entries),'verified/reference-record bibliography entries')


if __name__=='__main__':main()
