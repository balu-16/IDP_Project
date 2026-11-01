"""Publication figures from verified saved-run exports; no model or selector calls."""
from __future__ import annotations
import csv
import json
import os
from pathlib import Path
import sys

JOURNAL=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
os.environ['MPLCONFIGDIR']=str(JOURNAL/'.cache/matplotlib')
os.environ['XDG_CACHE_HOME']=str(JOURNAL/'.cache')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np

plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'axes.titlesize':10,'axes.labelsize':9,
                     'legend.fontsize':8,'xtick.labelsize':8,'ytick.labelsize':8,'pdf.fonttype':42,
                     'ps.fonttype':42,'axes.spines.top':False,'axes.spines.right':False,
                     'savefig.facecolor':'white'})
COLORS=['#176B91','#D06629','#33846D','#8759A4','#BE4771','#70808C']
ORDER=['scifact','nfcorpus','fiqa']
NAMES={'scifact':'SciFact','nfcorpus':'NFCorpus','fiqa':'FiQA'}


def save(fig,name):
    fig.savefig(JOURNAL/'figures'/f'{name}.pdf',bbox_inches='tight',pad_inches=.08)
    plt.close(fig)


def architecture():
    fig=plt.figure(figsize=(7.1,3.9))
    ax=fig.add_axes([0,0,1,1])
    ax.set_xlim(0,7.1);ax.set_ylim(0,3.9);ax.axis('off')
    def box(x,y,w,h,title,body,color):
        ax.add_patch(FancyBboxPatch((x,y),w,h,boxstyle='round,pad=0.035',facecolor=color,edgecolor='#40505E',linewidth=.8))
        ax.text(x+w/2,y+h-.16,title,ha='center',va='top',fontsize=9.2,fontweight='bold')
        ax.text(x+w/2,y+.15,body,ha='center',va='bottom',fontsize=8.2,linespacing=1.4)
    def arrow(a,b):
        ax.add_patch(FancyArrowPatch(a,b,arrowstyle='-|>',mutation_scale=11,linewidth=1,color='#40505E'))
    box(.10,2.72,2.02,1.03,'Candidate retrieval','MiniLM dense top 64\nBM25 / frozen hybrid top 15','#EBF3F7')
    box(2.54,2.72,2.02,1.03,'Neural scoring','Original L6 logits\nPairwise embedding similarities','#EBF3F7')
    box(4.98,2.72,2.02,1.03,'Base selection','Choose 8 of 15\nOrder by raw L6 logit','#E8F2EC')
    arrow((2.19,3.23),(2.47,3.23));arrow((4.63,3.23),(4.91,3.23))
    box(.10,1.20,2.02,1.13,'Protected prefix','Retain first 5 IDs\nRetain their exact order\nKeep original tail feasible','#FFF3E8')
    box(2.54,1.20,2.02,1.13,'Expanded tail pool','Union of 3 hybrid lists\nScore new candidates\nConstrain sorted tail logits','#FFF3E8')
    box(4.98,1.20,2.02,1.13,'Tail refinement','Choose 3 tail documents\nRequire lower redundancy\nCompare classical controls','#E8F2EC')
    ax.plot([5.99,5.99,1.11],[2.67,2.51,2.51],color='#40505E',linewidth=1)
    arrow((1.11,2.51),(1.11,2.38))
    arrow((2.19,1.76),(2.47,1.76));arrow((4.63,1.76),(4.91,1.76))
    ax.text(3.55,.76,'Base and refinement: ideal amplitude amplification simulated on a CPU.',ha='center',fontsize=8.7)
    ax.text(3.55,.44,'Separate native study: reversible constraints, synthesis, and bounded noiseless validation.',ha='center',fontsize=8.1,color='#40505E')
    ax.text(3.55,.12,'Reported policies: SciFact and NFCorpus use both stages; FiQA uses the base stage.',ha='center',fontsize=8.1,fontweight='bold')
    save(fig,'architecture')


def main():
    analysis=json.loads((JOURNAL/'evidence/secondary_analysis.json').read_text())
    runs=json.loads((JOURNAL/'evidence/verified_runs.json').read_text())
    resource=json.loads((JOURNAL/'evidence/resource_study.json').read_text())['summary']
    with (JOURNAL/'evidence/per_query_diagnostics.csv').open() as f:queries=list(csv.DictReader(f))
    architecture()
    fig,axes=plt.subplots(1,3,figsize=(7.1,2.8),sharey=False,layout='constrained')
    for ax,name in zip(axes,ORDER):
        c=analysis[name]['coverage'];keys=list(c);labels={'dense64':'Dense 64','shortlist15':'Hybrid 15','union':'Union'}
        x=np.arange(len(keys));vals=[c[k]['ceiling8'] for k in keys]
        ax.bar(x,vals,color=COLORS[0],width=.65,label='Judgment-based ceiling')
        observed=runs[name]['evaluation']['means'][runs[name]['method']]['Recall@8']
        ax.axhline(observed,color=COLORS[1],linestyle='--',linewidth=1.3,label='Observed reported policy')
        ax.set_xticks(x,[labels[k] for k in keys],rotation=22);ax.set_title(NAMES[name]);ax.set_ylim(0,min(1.05,max(vals)*1.22))
        ax.grid(axis='y',alpha=.18);ax.set_axisbelow(True)
    axes[0].set_ylabel('Mean attainable Recall@8')
    handles,labels=axes[0].get_legend_handles_labels();fig.legend(handles,labels,loc='outside lower center',ncol=2,frameon=False)
    save(fig,'candidate_coverage')
    fig,axes=plt.subplots(1,2,figsize=(7.1,2.6),layout='constrained')
    for name,color in zip(ORDER[:2],COLORS):
        rows=[r for r in queries if r['dataset']==name]
        for ax,key,label in zip(axes,['recall_delta','redundancy_delta'],['Change in Recall@8','Change in redundancy']):
            values=np.sort([float(r[key]) for r in rows]);ax.step(values,np.arange(1,len(values)+1)/len(values),where='post',color=color,label=NAMES[name])
            ax.set_xlabel(label);ax.set_ylabel('Fraction of queries');ax.axvline(0,color='#777777',linewidth=.7,linestyle='--');ax.grid(alpha=.16)
    axes[1].legend(frameon=False,loc='upper left');save(fig,'paired_distributions')
    fig,axes=plt.subplots(1,3,figsize=(7.1,2.9),layout='constrained')
    groups=[('cosine','Dense cosine','o'),('fusion','RRF','s'),('l6_only','L6 only','D'),('gas_l6','Base GAS','v'),('neural_l6_top64','L6 dense 64','P'),('primary','Reported GAS','*'),('greedy','Matched greedy','X')]
    for ax,name in zip(axes,ORDER):
        r=runs[name];e=r['evaluation']['means']
        for i,(alias,label,marker) in enumerate(groups):
            m=r['method'] if alias=='primary' else ('greedy_v3' if r['refined'] else 'greedy_l6') if alias=='greedy' else alias
            ax.scatter(e[m]['redundancy'],e[m]['Recall@8'],s=62 if alias=='primary' else 29,marker=marker,color=COLORS[i%6],label=label,alpha=.8,linewidths=.6)
        ax.set_title(NAMES[name]);ax.set_xlabel('Redundancy (lower is better)');ax.grid(alpha=.16)
    axes[0].set_ylabel('Recall@8 (higher is better)')
    handles,labels=axes[-1].get_legend_handles_labels();fig.legend(handles,labels,loc='outside lower center',ncol=4,frameon=False)
    save(fig,'observed_tradeoffs')
    fig,ax=plt.subplots(figsize=(7.1,2.9),layout='constrained');left=np.zeros(3)
    components=[('retrieval_lexical_ms','Retrieval + lexical'),('original_l6_ms','Original L6'),('additional_l6_ms','Additional L6'),('base_selector_ms','Base selection'),('refine_selector_ms','Refinement')]
    for i,(key,label) in enumerate(components):
        vals=np.array([analysis[n]['mean_timing_components_ms'][key] for n in ORDER]);ax.barh([NAMES[n] for n in ORDER],vals,left=left,color=COLORS[i],height=.6,label=label);left+=vals
    ax.set_xlabel('Arithmetic mean composed online time (ms / seeded request)');ax.invert_yaxis();ax.grid(axis='x',alpha=.16);ax.set_axisbelow(True)
    fig.legend(loc='outside lower center',ncol=3,frameon=False);save(fig,'cost_decomposition')
    fig,axes=plt.subplots(1,2,figsize=(7.1,2.8),layout='constrained')
    for bits,color in zip([4,8,12,16],COLORS):
        real=[(int(m),cells[str(bits)]) for m,cells in resource['native'].items() if cells[str(bits)]['datasets']!=['synthetic']]
        stress=[(int(m),cells[str(bits)]) for m,cells in resource['native'].items() if cells[str(bits)]['datasets']==['synthetic']]
        real.sort();stress.sort()
        for ax,key,label in zip(axes,['qubits_max','oracle_cx_max'],['Maximum logical qubits','Maximum oracle CX gates']):
            ax.plot([m for m,c in real],[c[key] for m,c in real],marker='o',markersize=4,color=color,label=f'{bits} bits')
            ax.plot([m for m,c in stress],[c[key] for m,c in stress],marker='^',markersize=5,color=color,linestyle='--',markerfacecolor='white')
            ax.set_xlabel('Tail-pool size M');ax.set_ylabel(label);ax.set_xticks([3,5,8,12,16,20]);ax.grid(alpha=.16)
    axes[1].legend(frameon=False,title='Pair precision',ncol=2);fig.supxlabel('Circles: saved real instances. Hollow triangles: artificial stress instances.',fontsize=8)
    save(fig,'native_resources')
    fig,axes=plt.subplots(1,2,figsize=(7.1,2.7),layout='constrained')
    for name,color in zip(ORDER,COLORS):
        for pool,style in [(5,'-'),(8,'--')]:
            cells=resource['compact'][name];x=[b for b in [4,8,12,16] if f'{pool}:{b}' in cells]
            y=[cells[f'{pool}:{b}']['float_gap_mean'] for b in x]
            axes[0].plot(x,y,color=color,linestyle=style,marker='o',markersize=3,label=NAMES[name]+f', M={pool}')
    axes[0].set_xlabel('Pair coefficient bits');axes[0].set_ylabel('Mean GAS float-redundancy gap');axes[0].set_xticks([4,8,12,16]);axes[0].grid(alpha=.16)
    axes[1].axis('off');handles,labels=axes[0].get_legend_handles_labels();axes[1].legend(handles,labels,loc='center',frameon=False)
    axes[1].text(.05,.02,'Gap is measured against the exact float optimum.\nAvailable real instances only; this is not a new\nretrieval-effectiveness experiment.',fontsize=8,transform=axes[1].transAxes)
    save(fig,'precision_gaps')
    print('Generated seven vector PDF figures')


if __name__=='__main__':main()
