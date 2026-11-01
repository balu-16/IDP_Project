"""Verify saved research and derive journal analyses; never run a retrieval experiment."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
import sys

JOURNAL = Path(__file__).resolve().parents[1]
ROOT = JOURNAL.parents[1]
sys.dont_write_bytecode = True
for key, relative in {"XDG_CACHE_HOME": ".cache", "MPLCONFIGDIR": ".cache/matplotlib", "TMPDIR": ".tmp"}.items():
    os.environ[key] = str(JOURNAL / relative)
sys.path.insert(0, str(ROOT))

import numpy as np
from manuscript_support.export_verified_results import load_runs, independent_scores
from manuscript_support.resource_integration import load_resource
from research import datasets
from research.accuracy_v2.storage import Store

ORDER = ("scifact", "nfcorpus", "fiqa")
NAMES = dict(scifact="SciFact", nfcorpus="NFCorpus", fiqa="FiQA")
METRICS = ("nDCG@5", "nDCG@8", "Recall@8", "redundancy")


def write_json(name: str, value: object) -> None:
    (JOURNAL / "evidence" / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def write_csv(name: str, rows: list[dict]) -> None:
    if not rows:
        return
    with (JOURNAL / "evidence" / name).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def escape(value: object) -> str:
    return str(value).replace("&", r"\&").replace("%", r"\%").replace("_", r"\_").replace("#", r"\#")


def table(name: str, columns: str, header: str, rows: list[list]) -> None:
    value = [r"\begin{tabular}{" + columns + "}", r"\toprule", header + r"\\", r"\midrule"]
    value += [" & ".join(map(str, row)) + r"\\" for row in rows]
    value += [r"\bottomrule", r"\end{tabular}", ""]
    (JOURNAL / "includes" / (name + ".tex")).write_text("\n".join(value))


def fmt(value: float, digits: int = 4) -> str:
    return f"{value:.{digits}f}"


def seed_rows(payload: dict) -> dict:
    return payload.get("per_seed_results", {"0": payload.get("result")})


def derive(runs: dict) -> dict:
    analysis, query_rows, seed_export, methods_export, timing_export = {}, [], [], [], []
    for name in ORDER:
        run = runs[name]
        store = Store(ROOT / run["path"], run["identity"], resume=True)
        rels = datasets._load_qrels(datasets.DATA_ROOT / name, "test")
        texts = datasets._load_queries(datasets.DATA_ROOT / name, "test")
        evaluation = run["evaluation"]
        primary = run["method"]
        reference = "gas_l6" if run["refined"] else "l6_only"
        rows, timings = [], []
        run['primary_requests'] = []
        for qid in sorted(rels):
            record = store.get("queries", qid)
            bundle = store.get("features", qid)
            vectors = dict(zip(bundle["full"]["ids"], np.asarray(bundle["full"]["embeddings"], dtype=float)))
            relevant = rels[qid]
            # Historical wire names: shortlist_ids is dense 64; candidate_ids is hybrid 15.
            # dense_candidate_ids identifies the separate dense-15 neural control.
            pools = {"dense64": record["shortlist_ids"], "shortlist15": record["candidate_ids"]}
            assert len(pools['dense64']) == 64 and len(pools['shortlist15']) == 15
            assert set(pools['shortlist15']) <= set(pools['dense64'])
            if "union_ids" in record:
                pools["union"] = record["union_ids"]
                assert set(pools['shortlist15']) <= set(pools['union']) <= set(pools['dense64'])
            coverage = {}
            for pool, ids in pools.items():
                n_relevant = len(set(ids) & relevant.keys())
                coverage.update({pool + "_relevant": n_relevant,
                                 pool + "_coverage": n_relevant / len(relevant),
                                 pool + "_ceiling8": min(8, n_relevant) / len(relevant),
                                 pool + "_size": len(ids)})
            primary_rows = seed_rows(record["methods"][primary])
            reference_rows = seed_rows(record["methods"][reference])
            scores, distinct = [], set()
            prefix_preserved = True
            same_membership = 0
            per_query_timing = []
            for seed, result in primary_rows.items():
                run['primary_requests'].append(result)
                reference_result = reference_rows.get(seed, reference_rows["0"])
                score = independent_scores(result["ranked_ids"], relevant, vectors)
                scores.append(score)
                distinct.add(tuple(result["ranked_ids"]))
                prefix_preserved &= result["ranked_ids"][:5] == reference_result["ranked_ids"][:5]
                same_membership += set(result["ranked_ids"]) == set(reference_result["ranked_ids"])
                t = result["timings_ms"]
                upstream = sum(t.get(k, 0) for k in ["query_encoding_ms", "dense_retrieval_ms", "representative_features_ms", "lexical_scoring_ms", "hybrid_prefilter_ms", "union_prefilter_ms"])
                components = {"retrieval_lexical_ms": upstream, "original_l6_ms": t.get("l6_inference_ms", 0),
                              "additional_l6_ms": t.get("additional_l6_inference_ms", 0),
                              "base_selector_ms": t.get("baseline_selection_ms", 0) if run["refined"] else t["total_ms"],
                              "refine_selector_ms": t["total_ms"] if run["refined"] else 0}
                assert abs(sum(components.values()) - t["online_total_ms"]) < 1e-6, (name, qid, "timing composition")
                components.update(online_total_ms=t["online_total_ms"],
                                  combined_selector_ms=t["total_ms"] + t.get("baseline_selection_ms", 0))
                timing_export.append(dict(dataset=name, qid=qid, seed=int(seed), **components))
                per_query_timing.append(components)
                seed_export.append(dict(dataset=name, qid=qid, seed=int(seed), **score,
                                        phase_calls=result["counts"]["phase_oracle_calls"],
                                        baseline_phase_calls=result["counts"].get("baseline_phase_oracle_calls", 0),
                                        status=result["status"], distinct_membership_from_reference=int(set(result["ranked_ids"]) != set(reference_result["ranked_ids"]))))
            if run["refined"]:
                assert prefix_preserved, (name, qid, "protected prefix changed")
            means = {k: float(np.mean([s[k] for s in scores])) for k in METRICS}
            base = evaluation["per_query"][reference][qid]
            def delta(key):
                value=means[key]-base[key]
                return 0.0 if abs(value)<=1e-12 else value
            row = dict(dataset=name, qid=qid, query=texts[qid], judged_relevant=len(relevant), **coverage,
                       **means, recall_delta=delta('Recall@8'),
                       redundancy_delta=delta('redundancy'), ndcg5_delta=delta('nDCG@5'),
                       reference_recall=base["Recall@8"], reference_redundancy=base["redundancy"],
                       distinct_seed_rankings=len(distinct), prefix_preserved=int(prefix_preserved),
                       same_membership_requests=same_membership,
                       recall_seed_range=max(s["Recall@8"] for s in scores)-min(s["Recall@8"] for s in scores),
                       redundancy_seed_range=max(s["redundancy"] for s in scores)-min(s["redundancy"] for s in scores))
            rows.append(row)
            timings.extend(per_query_timing)
        query_rows.extend(rows)
        changed = lambda key, sign: sum(sign * r[key] > 1e-12 for r in rows)
        pool_names = list(pools)
        a = {"method": primary, "reference": reference, "queries": len(rows),
             "coverage": {pool: {k: float(np.mean([r[pool + "_" + k] for r in rows])) for k in ["coverage", "ceiling8", "size", "relevant"]} for pool in pool_names},
             "no_relevant_in_shortlist": sum(r["shortlist15_relevant"] == 0 for r in rows),
             "recall_wins": changed("recall_delta", 1), "recall_losses": changed("recall_delta", -1),
             "redundancy_reduced_queries": changed("redundancy_delta", -1),
             "redundancy_increased_queries": changed("redundancy_delta", 1),
             "seed_variable_queries": sum(r["distinct_seed_rankings"] > 1 for r in rows),
             "seed_recall_variable_queries": sum(r["recall_seed_range"] > 1e-12 for r in rows),
             "mean_recall_seed_range": float(np.mean([r["recall_seed_range"] for r in rows])),
             "max_recall_seed_range": max(r["recall_seed_range"] for r in rows),
             "mean_redundancy_seed_range": float(np.mean([r["redundancy_seed_range"] for r in rows])),
             "same_membership_requests": sum(r["same_membership_requests"] for r in rows),
             "mean_timing_components_ms": {key: float(np.mean([t[key] for t in timings])) for key in timings[0]},
             "mean_recall_delta": float(np.mean([r["recall_delta"] for r in rows])),
             "mean_redundancy_delta": float(np.mean([r["redundancy_delta"] for r in rows])),
             "mean_recall_lost_per_query": float(np.mean([max(0, -r["recall_delta"]) for r in rows])),
             "mean_recall_gained_per_query": float(np.mean([max(0, r["recall_delta"]) for r in rows])),
             "worst_recall_delta": min(r["recall_delta"] for r in rows),
             "best_recall_delta": max(r["recall_delta"] for r in rows)}
        a["recall_ties"] = len(rows) - a["recall_wins"] - a["recall_losses"]
        analysis[name] = a
        for method, values in evaluation["means"].items():
            execution = evaluation["execution"][method]
            methods_export.append(dict(dataset=name, method=method, primary=int(method == primary), **values,
                                       online_median_ms=execution["online_total_ms"]["median"], online_p95_ms=execution["online_total_ms"]["p95"]))
        print(f"Derived {NAMES[name]}: coverage, paired outcomes, seed stability, and cost decomposition", flush=True)
    # CSV field union handles metrics available in only one policy family.
    keys = list(dict.fromkeys(k for row in methods_export for k in row))
    write_csv("all_methods.csv", [{k: row.get(k, "") for k in keys} for row in methods_export])
    keys = list(dict.fromkeys(k for row in query_rows for k in row))
    write_csv("per_query_diagnostics.csv", [{k: row.get(k, "") for k in keys} for row in query_rows])
    write_csv("primary_seed_metrics.csv", seed_export)
    write_csv("primary_request_timings.csv", timing_export)
    write_json("secondary_analysis.json", analysis)
    return analysis


def make_tables(runs: dict, analysis: dict, resource: dict) -> None:
    rows = []
    for name in ORDER:
        r = runs[name]; config = r["base"]["config"]
        setup = r["setup"][0]["provenance"]
        rows.append([NAMES[name], f"{setup['n_parents']:,}", r["development_count"], r["evaluation"]["query_count"],
                     fmt(config["lexical_weight"], 2), fmt(config["diversity_weight"], 3), "Base + refinement" if r["refined"] else "Base"])
    table("datasets", "lrrrrrl", r"Dataset & Documents & Dev. & Test & $\beta$ & $\lambda$ & Reported policy", rows)
    rows = []
    for name in ORDER:
        r = runs[name];m = r["evaluation"]["means"][r["method"]]
        rows.append([NAMES[name], *[fmt(m[k],6) for k in METRICS]])
    table("headline", "lrrrr", r"Dataset & nDCG@5 & nDCG@8 & Recall@8 & Redundancy $\downarrow$", rows)
    labels = [("cosine","Dense cosine"),("fusion","Dense/BM25 RRF"),("legacy_grover","Legacy threshold Grover"),("gas","Cosine-guided GAS"),
              ("l6_only","L6 relevance only"),("mmr_l6","L6 MMR"),("gas_l6","Base L6-guided GAS"),
              ("greedy","Matched greedy"),("exact_float","Matched exact float"),("exact_quantized","Matched exact integer"),("random","Matched random"),
              ("neural_l2_matched","L2, dense 15"),("neural_l6_matched","L6, dense 15"),("neural_l2_top64","L2, dense 64"),("neural_l6_top64","L6, dense 64"),("primary","Reported GAS policy")]
    rows, latencies = [], []
    for alias,label in labels:
        row,timing=[label],[label]
        for name in ORDER:
            r=runs[name]
            method=r["method"] if alias=="primary" else alias + ("_v3" if r["refined"] else "_l6") if alias in {"greedy","exact_float","exact_quantized","random"} else alias
            e=r["evaluation"]
            row.extend(fmt(e["means"][method][k]) for k in ["nDCG@5","Recall@8","redundancy"])
            timing.extend(fmt(e["execution"][method]["online_total_ms"][k],1) for k in ["median","p95"])
        rows.append(row);latencies.append(timing)
    table("comparators","lrrrrrrrrr",r"& \multicolumn{3}{c}{SciFact} & \multicolumn{3}{c}{NFCorpus} & \multicolumn{3}{c}{FiQA}\\"+'\n'+r"Policy & n@5 & R@8 & Red. & n@5 & R@8 & Red. & n@5 & R@8 & Red.",rows)
    table("latency","lrrrrrr",r"& \multicolumn{2}{c}{SciFact} & \multicolumn{2}{c}{NFCorpus} & \multicolumn{2}{c}{FiQA}\\"+'\n'+r"Policy & P50 & P95 & P50 & P95 & P50 & P95",latencies)
    rows=[]
    for name in ORDER[:2]:
        e=runs[name]["evaluation"]
        for k in METRICS:
            s=e["comparisons"]["gas_l6"][k];h=e["holm"][f"gas_l6:{k}"]
            rows.append([NAMES[name],k.replace("redundancy","Redundancy"),f"{s['mean_diff']:+.5f}",f"[{s['ci_low']:+.5f}, {s['ci_high']:+.5f}]",f"{s['p_value']:.5f}","Yes" if h["significant"] else "No"])
    s=runs['fiqa']['statistics_audit']['comparisons']['l6_only']
    rows.append(['FiQA',r'nDCG@5$^\dagger$',fmt(s['mean_diff'],5),f"[{s['ci_low']:.5f}, {s['ci_high']:.5f}]",fmt(s['p_value'],5),'No'])
    table('statistics','llrrrc',r'Dataset & Metric & Mean difference & Paired 95\% CI & Raw $p$ & Holm reject',rows)
    rows=[]
    for name in ORDER:
        a=analysis[name]
        for pool,label in [('dense64','Dense 64'),('shortlist15','Hybrid 15'),('union','Expanded union')]:
            if pool in a['coverage']:
                c=a['coverage'][pool];rows.append([NAMES[name],label,fmt(c['size'],2),fmt(c['coverage']),fmt(c['ceiling8'])])
    table('coverage','llrrr',r'Dataset & Pool & Mean size & Judged coverage & Recall@8 ceiling',rows)
    rows=[]
    for name in ORDER:
        a=analysis[name];rows.append([NAMES[name],a['recall_wins'],a['recall_ties'],a['recall_losses'],a['redundancy_reduced_queries'],a['seed_variable_queries'],a['seed_recall_variable_queries']])
    table('query_outcomes','lrrrrrr',r'Dataset & Recall wins & Ties & Losses & Lower redundancy & Seed-varying ranks & Seed-varying recall',rows)
    rows=[]
    for name in ORDER:
        r=runs[name];requests=r['primary_requests'];ex=r['evaluation']['execution'][r['method']]
        hit=r['evaluation']['means'][r['method']].get('float_redundancy_optimum_hit',r['evaluation']['means'][r['method']].get('quantized_optimum_hit'))
        rows.append([NAMES[name],len(requests),fmt(np.mean([v['counts'].get('baseline_phase_oracle_calls',0) for v in requests]),2),fmt(np.mean([v['counts']['phase_oracle_calls'] for v in requests]),2),fmt(hit,3),fmt(r['combined_selector_ms']['median'],2),fmt(r['combined_selector_ms']['p95'],2)])
    table('search','lrrrrrr',r'Dataset & Requests & Base phases & Refine/base phases & Optimum-hit rate & Selector P50 & Selector P95',rows)
    rows=[]
    for name in ORDER:
        for q in runs[name]['thresholds']:rows.append([NAMES[name],fmt(q['threshold'],1),fmt(q['development_ndcg5']),fmt(q['no_marked_query_percent'],1)])
    table('thresholds','lrrr',r'Dataset & Threshold & Dev. nDCG@5 & No-marked queries (\%)',rows)
    (JOURNAL/'includes/native_resources.tex').write_text(resource['resource_table'])
    rows=[]
    for alias,label in [('l6_union','Union L6, global order'),('l6_union_tail','Union L6, protected prefix'),('gas_v3','Constrained GAS'),('greedy_v3','Constrained greedy'),('exact_float_v3','Constrained exact float'),('exact_quantized_v3','Constrained exact integer'),('random_v3','Constrained random')]:
        row=[label]
        for name in ORDER[:2]:row.extend(fmt(runs[name]['evaluation']['means'][alias][k]) for k in METRICS)
        rows.append(row)
    table('expanded_controls','lrrrrrrrr',r'& \multicolumn{4}{c}{SciFact} & \multicolumn{4}{c}{NFCorpus}\\'+'\n'+r'Policy & n@5 & n@8 & R@8 & Red. & n@5 & n@8 & R@8 & Red.',rows)
    # All scalar macros are generated from verified values, never hand-entered headline numbers.
    macros=[]
    for name in ORDER:
        a=analysis[name];e=runs[name]['evaluation'];p=e['means'][runs[name]['method']];b=e['means'][a['reference']]
        values={'Ndcg':fmt(p['nDCG@5'],4),'Recall':fmt(p['Recall@8'],4),'Redundancy':fmt(p['redundancy'],4),
                'RecallChange':fmt(100*(p['Recall@8']/b['Recall@8']-1),2),
                'RedReduction':fmt(100*(b['redundancy']-p['redundancy'])/b['redundancy'],2),
                'NoRelevant':str(a['no_relevant_in_shortlist']),'Wins':str(a['recall_wins']),'Losses':str(a['recall_losses']),
                'Ties':str(a['recall_ties']),'LowerRed':str(a['redundancy_reduced_queries']),'SeedVary':str(a['seed_variable_queries']),
                'SeedRecall':str(a['seed_recall_variable_queries']),
                'DenseCeiling':fmt(a['coverage']['dense64']['ceiling8'],4),'ShortCeiling':fmt(a['coverage']['shortlist15']['ceiling8'],4),
                'OriginalLsixShare':fmt(100*a['mean_timing_components_ms']['original_l6_ms']/a['mean_timing_components_ms']['online_total_ms'],1),
                'SelectorShare':fmt(100*a['mean_timing_components_ms']['combined_selector_ms']/a['mean_timing_components_ms']['online_total_ms'],2)}
        if 'union' in a['coverage']:values['UnionCeiling']=fmt(a['coverage']['union']['ceiling8'],4)
        for key,value in values.items():macros.append('\\newcommand{\\'+name+key+'}{'+value+'}')
    g=resource['protocol']['prerequisites']['fiqa_gate']
    macros.extend([r'\newcommand{\fiqaFollowupRecallLoss}{'+fmt(-g['recall_relative_change_percent'],2)+'}',r'\newcommand{\fiqaFollowupRedReduction}{'+fmt(g['redundancy_relative_reduction_percent'],2)+'}'])
    (JOURNAL/'includes/numbers.tex').write_text('\n'.join(macros)+'\n')


def main() -> None:
    mapping=json.loads((ROOT/'manuscript_support/paper_sources.json').read_text())
    write_json('paper_sources.json',mapping)
    if '--refresh-analysis' in sys.argv:
        runs=json.loads((JOURNAL/'evidence/verified_runs.json').read_text())
        previous=json.loads((ROOT/'manuscript_support/records/evidence.json').read_text())['runs']
        for name,run in runs.items():
            run['independent_recomputed_metric_values']=previous[name]['independent_recomputed_metric_values']
            run['thresholds']=previous[name]['thresholds']
            for filename,key in [('manifest.json','manifest_sha256'),('evaluation.json','evaluation_sha256')]:
                assert hashlib.sha256((ROOT/run['path']/filename).read_bytes()).hexdigest()==run[key]
    else:
        runs,_=load_runs(mapping,False)
    resource=load_resource(mapping)
    # load_resource verifies the source CSV against the sealed report manifest.
    # Preserve its full validation/status columns in the journal artifact.
    native_csv=ROOT/resource['directory']/'native_resources.csv'
    (JOURNAL/'evidence/native_resources.csv').write_bytes(native_csv.read_bytes())
    analysis=derive(runs)
    make_tables(runs,analysis,resource)
    serial={name:{'path':r['path'],'method':r['method'],'refined':r['refined'],'manifest_sha256':r['manifest_sha256'],
                  'evaluation_sha256':r['evaluation_sha256'],'identity':r['identity'],'base':r['base'],
                  'setup':r['setup'],'evaluation':r['evaluation'],'development_count':r['development_count'],
                  'independent_recomputed_metric_values':r['independent_recomputed_metric_values'],
                  'thresholds':r['thresholds'],
                  'statistics_audit':r['statistics_audit'],'combined_selector_ms':r['combined_selector_ms']} for name,r in runs.items()}
    write_json('verified_runs.json',serial)
    write_json('resource_study.json',resource)
    numeric_names={'verified_runs.json','resource_study.json','secondary_analysis.json','paper_sources.json',
                   'all_methods.csv','per_query_diagnostics.csv','primary_seed_metrics.csv','primary_request_timings.csv',
                   'native_resources.csv'}
    generated={str(p.relative_to(JOURNAL)):hashlib.sha256(p.read_bytes()).hexdigest() for d in ['includes','evidence'] for p in (JOURNAL/d).iterdir() if p.is_file() and (d=='includes' or p.name in numeric_names)}
    write_json('export_verification.json',{'query_counts':{n:r['evaluation']['query_count'] for n,r in runs.items()},
                'independently_checked_query_method_metric_values':sum(r['independent_recomputed_metric_values'] for r in runs.values()),
                'exporter_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'new_rankings':False,'model_inference':False,'scidocs_included':False,'generated_sha256':generated})
    print('Journal evidence exported; existing experiments and conference files were not written',flush=True)


if __name__=='__main__':
    main()
