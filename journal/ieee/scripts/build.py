"""Build and audit the isolated journal artifact; all writes remain beneath journal/."""
from __future__ import annotations
import argparse
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

JOURNAL=Path(__file__).resolve().parents[1]
ROOT=JOURNAL.parents[1]
sys.dont_write_bytecode=True


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def environment(assets=None):
    env=os.environ.copy()
    texbin=JOURNAL/'tools/.TinyTeX/bin/x86_64-linux'
    env.update(PATH=str(texbin)+os.pathsep+env.get('PATH',''),PYTHONDONTWRITEBYTECODE='1',
               XDG_CACHE_HOME=str(JOURNAL/'.cache'),MPLCONFIGDIR=str(JOURNAL/'.cache/matplotlib'),
               TMPDIR=str(JOURNAL/'.tmp'),TEXMFHOME=str(JOURNAL/'.cache/texmf-home'),
               TEXMFVAR=str(JOURNAL/'.cache/texmf-var'),TEXMFCONFIG=str(JOURNAL/'.cache/texmf-config'),
               TEXMFOUTPUT=str(JOURNAL/'build'))
    if shutil.which('curl'):
        env.setdefault('TEXLIVE_DOWNLOADER', 'curl')
    assets=assets or JOURNAL/'template/assets'
    for key in ['TEXINPUTS','TFMFONTS','T1FONTS','TEXFONTMAPS','BSTINPUTS']:
        env[key]=str(assets)+'//:'
    env['BIBINPUTS']=str(assets)+'//:'+str(JOURNAL)+':'
    return env


def prepare_workspace():
    for relative in ['build', '.tmp', '.cache', '.cache/texmf-home',
                     '.cache/texmf-var', '.cache/texmf-config']:
        (JOURNAL/relative).mkdir(parents=True,exist_ok=True)


def run(command,log,cwd=JOURNAL,env=None):
    process=subprocess.run(list(map(str,command)),cwd=cwd,env=env or environment(),text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (JOURNAL/'build'/log).write_text(process.stdout)
    if process.returncode:
        print(process.stdout[-6500:])
        raise RuntimeError(f"Command failed; see journal/ieee/build/{log}")
    return process.stdout


def ensure_packages():
    env=environment()
    packages={'cite.sty':'cite','algorithmic.sty':'algorithms','booktabs.sty':'booktabs','xurl.sty':'xurl','url.sty':'url','array.sty':'tools','etoolbox.sty':'etoolbox','pcrr8t.tfm':'courier'}
    missing=[]
    for filename,package in packages.items():
        result=subprocess.run(['kpsewhich',filename],env=env,capture_output=True,text=True)
        if result.returncode:missing.append(package)
    if missing:
        print('Installing isolated LaTeX packages:',', '.join(missing),flush=True)
        # A fixed mirror keeps metadata, checksums and signatures on one server.
        repository=['tlmgr','--repository','https://ctan.math.illinois.edu/systems/texlive/tlnet']
        try:
            run([*repository,'install',*missing],'tex_packages.log')
        except RuntimeError:
            if 'tlmgr itself needs to be updated' not in (JOURNAL/'build/tex_packages.log').read_text():raise
            run([*repository,'update','--self'],'tex_manager_update.log')
            run([*repository,'install',*missing],'tex_packages.log')


def compile_source(source,output,log_prefix,env=None):
    output.mkdir(parents=True,exist_ok=True)
    args=['pdflatex','-interaction=nonstopmode','-halt-on-error','-file-line-error','-output-directory='+str(output),source.name]
    run(args,log_prefix+'_pass1.txt',source.parent,env)
    run(['bibtex',source.stem],log_prefix+'_bibtex.txt',output,env)
    for i in [2,3]:run(args,log_prefix+f'_pass{i}.txt',source.parent,env)
    return output/(source.stem+'.pdf')


def snapshot_outside_additions():
    """Bind pre-existing additions without accepting later outside changes."""
    before=set(json.loads((JOURNAL/'evidence/original_files_metadata.json').read_text()))
    additions={}
    for base,dirs,files in os.walk(ROOT):
        dirs[:]=[d for d in dirs if d not in {'.git','.venv','node_modules','journal'}]
        for filename in files:
            path=Path(base)/filename
            name=str(path.relative_to(ROOT))
            if name not in before and path.is_file():
                additions[name]=sha(path)
    return additions


def check_originals(*, record=True, allowed_additions=None):
    originals=json.loads((JOURNAL/'evidence/original_files_sha256.json').read_text())
    changed=[name for name,digest in originals.items() if (sha(ROOT/name) if (ROOT/name).is_file() else None)!=digest]
    metadata=json.loads((JOURNAL/'evidence/original_files_metadata.json').read_text())
    before=set(metadata);after={}
    for base,dirs,files in os.walk(ROOT):
        dirs[:]=[d for d in dirs if d not in {'.git','.venv','node_modules','journal'}]
        for filename in files:
            p=Path(base)/filename
            if p.is_file():
                s=p.stat();after[str(p.relative_to(ROOT))]=[s.st_size,s.st_mtime_ns]
    altered=[name for name in before & after.keys() if metadata[name]!=after[name]]
    result={'tracked_hash_changes':changed,'outside_journal_metadata_changes':altered,
            'outside_journal_added_files':sorted(after.keys()-before),'outside_journal_removed_files':sorted(before-after.keys())}
    # Preserve separately documented concurrent edits without resetting the original
    # snapshots. Exact hashes and metadata must still match that observed state.
    observed_path=JOURNAL/'evidence/observed_external_changes.json'
    observed=json.loads(observed_path.read_text())['files'] if observed_path.exists() else {}
    recognized=[]
    for name,entry in observed.items():
        p=ROOT/name
        if (entry['initial_sha256']==originals.get(name)
                and p.is_file() and sha(p)==entry['observed_sha256']
                and after.get(name)==entry['observed_metadata']):
            recognized.append(name)
    cleanup_removed=set();cleanup_modified=set()
    cleanup_path=JOURNAL/'evidence/workspace_cleanup.json'
    if cleanup_path.exists():
        cleanup=json.loads(cleanup_path.read_text())
        if cleanup['status'] in {'applied','verified'}:
            if cleanup['schema']!='workspace-cache-cleanup-v1':
                raise ValueError('Unknown workspace cleanup record')
            inventory_path=JOURNAL/'evidence'/cleanup['inventory_file']
            if inventory_path.resolve().parent!=(JOURNAL/'evidence').resolve():
                raise ValueError('Cleanup inventory must remain in evidence/')
            if sha(inventory_path)!=cleanup['inventory_sha256']:
                raise ValueError('Workspace cleanup inventory checksum mismatch')
            with gzip.open(inventory_path,'rt') as handle:inventory=json.load(handle)
            def workspace_path(name):
                relative=Path(name)
                if relative.is_absolute() or '..' in relative.parts:
                    raise ValueError('Invalid workspace cleanup path')
                return ROOT/relative
            for entry in inventory['deleted_files']:
                path=workspace_path(entry['path'])
                if not path.exists() and not path.is_symlink():cleanup_removed.add(entry['path'])
            protected={entry['path']:entry for entry in inventory['protected_files']}
            for name,change in cleanup['approved_modified_files'].items():
                path=workspace_path(name)
                if (name in inventory['approved_modified_paths']
                        and protected[name].get('sha256')==change['before_sha256']
                        and path.is_file() and sha(path)==change['after_sha256']):
                    cleanup_modified.add(name)
    allowed_additions=allowed_additions or {}
    verified_additions=[]
    changed_additions=[]
    for name,digest in allowed_additions.items():
        path=ROOT/name
        if name in result['outside_journal_added_files'] and path.is_file() and sha(path)==digest:
            verified_additions.append(name)
        else:
            changed_additions.append(name)
    unexpected={key:[name for name in names if name not in recognized
                    and not (key=='outside_journal_removed_files' and name in cleanup_removed)
                    and not (key=='outside_journal_added_files' and name in verified_additions)
                    and not (key in {'tracked_hash_changes','outside_journal_metadata_changes'} and name in cleanup_modified)]
                for key,names in result.items()}
    unexpected['preexisting_additions_changed']=sorted(changed_additions)
    result['recognized_concurrent_edits']=recognized
    result['recognized_preexisting_additions']={name:allowed_additions[name] for name in sorted(verified_additions)}
    result['recognized_workspace_cleanup_removals']=sorted(set(result['outside_journal_removed_files']) & cleanup_removed)
    result['recognized_workspace_cleanup_modifications']=sorted(set(changed+altered) & cleanup_modified)
    result['unexpected_differences']=unexpected
    if record:
        (JOURNAL/'evidence/outside_folder_check.json').write_text(json.dumps(result,indent=2)+'\n')
    if any(unexpected.values()):raise ValueError('Unrecorded changes outside journal; inspect outside_folder_check.json')
    return result


def source_archive():
    paths=[JOURNAL/'main.tex',JOURNAL/'template_compat.tex',JOURNAL/'references.bib',JOURNAL/'SOURCE_README.md']
    for directory,pattern in [('sections','*.tex'),('includes','*.tex'),('figures','*.pdf')]:paths+=sorted((JOURNAL/directory).glob(pattern))
    with zipfile.ZipFile(JOURNAL/'latex_source.zip','w',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in paths:archive.write(path,str(path.relative_to(JOURNAL)))
        for path in sorted((JOURNAL/'template/assets').iterdir()):
            if path.is_file():archive.write(path,path.name)


def check_numbers():
    exported=json.loads((JOURNAL/'evidence/export_verification.json').read_text())
    if 'exporter_sha256' in exported:
        assert sha(JOURNAL/'scripts/export_evidence.py')==exported['exporter_sha256'],'Exporter changed; regenerate evidence'
    for relative,digest in exported['generated_sha256'].items():
        assert sha(JOURNAL/relative)==digest,f'Generated evidence changed: {relative}'
    analysis=json.loads((JOURNAL/'evidence/secondary_analysis.json').read_text())
    runs=json.loads((JOURNAL/'evidence/verified_runs.json').read_text())
    for name,a in analysis.items():
        coverage=a['coverage'];mean=runs[name]['evaluation']['means'][runs[name]['method']]
        assert coverage['dense64']['size']==64 and coverage['shortlist15']['size']==15
        assert coverage['dense64']['ceiling8']+1e-12>=coverage['shortlist15']['ceiling8']
        pool='union' if 'union' in coverage else 'shortlist15'
        assert coverage[pool]['ceiling8']+1e-12>=mean['Recall@8']
        assert a['recall_wins']+a['recall_ties']+a['recall_losses']==a['queries']
        if 'union' in coverage:
            assert coverage['shortlist15']['ceiling8']<=coverage['union']['ceiling8']<=coverage['dense64']['ceiling8']
            assert a['redundancy_increased_queries']==0
    with (JOURNAL/'evidence/per_query_diagnostics.csv').open() as f:rows=list(csv.DictReader(f))
    case1=next(r for r in rows if r['dataset']=='scifact' and r['qid']=='384')
    case2=next(r for r in rows if r['dataset']=='nfcorpus' and r['qid']=='PLAIN-2570')
    assert float(case1['reference_recall'])==1 and float(case1['Recall@8'])==0
    assert int(case2['judged_relevant'])==40 and abs(float(case2['reference_recall'])-.075)<1e-12 and abs(float(case2['Recall@8'])-.025)<1e-12
    assert abs(float(case1['redundancy_delta'])+.04373)<.000005
    assert abs(float(case2['redundancy_delta'])+.09454)<.000005
    # The existing independent mathematical verification has no file-writing path.
    sys.path.insert(0,str(ROOT))
    from manuscript_support.build_manuscript import mathematical_checks
    result=mathematical_checks()
    result.update(candidate_coverage_bounds=True,query_count_partitions=True,reported_cases_crosschecked=True)
    return result


def audit(pdf,proofs):
    log=(JOURNAL/'build/main.log').read_text(errors='replace')
    aux=(JOURNAL/'build/main.aux').read_text(errors='replace')
    text=run(['pdftotext','-layout',pdf,'-'],'pdf_text.txt')
    metadata=run(['pdfinfo',pdf],'pdf_metadata.txt')
    fonts=run(['pdffonts',pdf],'pdf_fonts.txt')
    pages=int(re.search(r'^Pages:\s+(\d+)',metadata,re.M).group(1))
    source=(JOURNAL/'main.tex').read_text()
    abstract=source.split(r'\begin{abstract}',1)[1].split(r'\end{abstract}',1)[0]
    abstract=re.sub(r'\\[A-Za-z]+\{\}', 'VALUE',abstract)
    abstract_words=len(re.findall(r"\b[\w]+(?:[-–][\w]+)*\b",abstract))
    warnings=[line for line in log.splitlines() if re.search(r'Warning:|Overfull|Underfull|Missing character|Font shape .* undefined',line)]
    issues=[]
    if not 150<=abstract_words<=250:issues.append('Abstract outside 150–250 words')
    if re.search(r'undefined|multiply defined', '\n'.join(warnings),re.I):issues.append('Unresolved citation/reference or font')
    if re.search(r'Overfull|Underfull', '\n'.join(warnings)):issues.append('Box diagnostics remain')
    if '??' in text:issues.append('Unresolved PDF reference marker')
    if 'Type 3' in fonts:issues.append('Type 3 fonts')
    if pages>20:issues.append('More than 20 pages')
    all_tex='\n'.join(p.read_text() for p in [JOURNAL/'main.tex',*sorted((JOURNAL/'sections').glob('*.tex'))])
    figures=re.findall(r'\\label\{((?:fig|tab):[^}]+)\}',all_tex)
    assert all(r'\ref{'+label+'}' in all_tex for label in figures)
    cited=set(k.strip() for group in re.findall(r'\\cite\{([^}]+)\}',all_tex) for k in group.split(','))
    bibliokeys=set(re.findall(r'@\w+\{([^,]+),',(JOURNAL/'references.bib').read_text()))
    assert not cited-bibliokeys,cited-bibliokeys
    assert not bibliokeys-cited, f'Uncited bibliography entries: {bibliokeys-cited}'
    requested=json.loads((ROOT/'manuscript_support/records/requested_references.json').read_text())
    assert set(requested['required_keys'])<=cited,'A requested reference is missing'
    results={'pages':pages,'abstract_words':abstract_words,'cited_references':len(cited),'bibliography_entries':len(bibliokeys),
             'figure_table_labels':figures,'warnings':warnings,'issues':issues,'math_and_analysis_checks':proofs,
             'pdf_sha256':sha(pdf),'source_sha256':sha(JOURNAL/'main.tex'),'class_sha256':sha(JOURNAL/'template/assets/ieeeaccess.cls'),
             'new_benchmark_rankings':False,'model_inference':False}
    results['requested_references_present']=len(requested['required_keys'])
    (JOURNAL/'evidence/publication_checks.json').write_text(json.dumps(results,indent=2)+'\n')
    print(f'Built {pages} pages; abstract {abstract_words} words; {len(cited)} cited references; {len(warnings)} diagnostics',flush=True)
    for issue in issues:print('To resolve:',issue)
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-evidence',action='store_true',help='Reverify saved runs and regenerate analyses; never collect benchmarks')
    parser.add_argument('--standalone',action='store_true',help='Also compile the source ZIP in an isolated subdirectory')
    parser.add_argument('--preserve-existing-additions',action='store_true',help='Snapshot existing outside files added since the original audit and verify they stay unchanged')
    args=parser.parse_args()
    additions=snapshot_outside_additions() if args.preserve_existing_additions else {}
    check_originals(record=False,allowed_additions=additions)
    prepare_workspace()
    if not (JOURNAL/'tools/.TinyTeX/bin/x86_64-linux/pdflatex').exists():run([sys.executable,JOURNAL/'scripts/bootstrap_tex.py'],'tex_bootstrap.log')
    if args.refresh_evidence:run([sys.executable,'-B',JOURNAL/'scripts/export_evidence.py'],'export.log')
    ensure_packages()
    proofs=check_numbers()
    pdf=compile_source(JOURNAL/'main.tex',JOURNAL/'build','main')
    shutil.copyfile(pdf,JOURNAL/'main.pdf')
    checks=audit(pdf,proofs)
    source_archive()
    if args.standalone:
        directory=JOURNAL/'build/standalone';directory.mkdir(exist_ok=True)
        with zipfile.ZipFile(JOURNAL/'latex_source.zip') as archive:archive.extractall(directory)
        env=environment(directory);env['BIBINPUTS']=str(directory)+'//:'
        standalone=compile_source(directory/'main.tex',directory/'output','standalone',env)
        original_text=(JOURNAL/'build/pdf_text.txt').read_text()
        standalone_text=run(['pdftotext','-layout',standalone,'-'],'standalone_pdf_text.txt')
        assert original_text==standalone_text,'Standalone PDF text differs'
        (JOURNAL/'evidence/standalone_check.json').write_text(json.dumps({'compiled':True,'extracted_text_matches':True,'source_archive_sha256':sha(JOURNAL/'latex_source.zip')},indent=2)+'\n')
    check_originals(allowed_additions=additions)
    if checks['issues']:raise SystemExit(2)


if __name__=='__main__':main()
