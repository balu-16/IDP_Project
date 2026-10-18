"""Passage adaptation of the pinned L6-guided, protected-prefix GAS pipeline."""
from dataclasses import asdict
import time

import numpy as np

from .gas_profile import APPLICATION_GAS, L6_MODEL, L6_REVISION
from .gas_selector import baseline, refinement
from .gas_selector.lexical import BM25
from .gas_selector.primitives import CandidateFeatures
from .l6_scorer import get_l6_scorer
from .quantum_search import normalized_matrix
from config import settings


def rank_passages(query, query_embedding, rows, *, seed=0, profile=APPLICATION_GAS, scorer=None):
    """Run in the bounded executor; judgments and benchmark runners are absent."""
    start = time.perf_counter()
    if not query or not query.strip():
        raise ValueError('L6-guided GAS requires the original question text')
    if not rows:
        return {'results': [], 'search_method': 'l6_gas', 'requested_search_method': 'l6_gas',
            'fallback_reason': 'no_candidates', 'quantum': {'representation': 'compact classical simulation'},
            'candidate_count': 0, 'ranking_time_ms': 0.0, 'timings_ms': {}}
    rows = sorted(rows, key=lambda row: row['id'])
    ids = tuple(row['id'] for row in rows)
    if len(ids) != len(set(ids)):
        raise ValueError('Eligible passage IDs must be unique')
    clock = time.perf_counter()
    vectors = normalized_matrix([row['embedding'] for row in rows], settings.EMBEDDING_DIMENSION)
    vector = normalized_matrix([query_embedding], settings.EMBEDDING_DIMENSION)[0]
    cosine = np.clip(vectors @ vector, -1, 1)
    indices = sorted(range(len(ids)), key=lambda i: (-cosine[i], ids[i]))[:profile.dense_count]
    dense_ms = (time.perf_counter() - clock) * 1000
    clock = time.perf_counter()
    lexical = BM25({row['id']: row['document'] for row in rows}).scores(query)
    lexical_ms = (time.perf_counter() - clock) * 1000
    features = CandidateFeatures(tuple(ids[i] for i in indices), cosine[indices], vectors[indices],
        tuple(rows[i]['document'] for i in indices))
    lexical_scores = [lexical[did] for did in features.ids]
    clock = time.perf_counter()
    original_indices = baseline.shortlist(features.ids, features.cosine_scores,
        lexical_scores, profile.lexical_weight, profile.shortlist_count)
    original = baseline.take(features, original_indices)
    prefilter_ms = (time.perf_counter() - clock) * 1000
    scorer = scorer or get_l6_scorer()
    original_scores, original_timing = scorer.score(query, list(original.passages))
    scored = baseline.ScoredFeatures(original, original_scores)
    base = baseline.select(scored, config=profile.baseline(), seed=seed)
    clock = time.perf_counter()
    union = set()
    for beta in (0.0, 0.25, 0.5):
        union.update(baseline.shortlist(features.ids, features.cosine_scores,
            lexical_scores, beta, profile.shortlist_count))
    union_indices = sorted(union, key=lambda i: features.ids[i])
    expanded = baseline.take(features, union_indices)
    known = dict(zip(original.ids, map(float, scored.l6_logits)))
    missing = [i for i in union_indices if features.ids[i] not in known]
    union_ms = (time.perf_counter() - clock) * 1000
    extra_scores, extra_timing = scorer.score(query, [features.passages[i] for i in missing])
    if len(extra_scores) != len(missing) or not np.isfinite(extra_scores).all():
        raise ValueError('Additional L6 scores must align with the new candidates')
    known.update(zip((features.ids[i] for i in missing), map(float, extra_scores)))
    union_features = baseline.ScoredFeatures(expanded, [known[did] for did in expanded.ids])
    selected = refinement.select(union_features, base.ranked_ids,
        config=profile.refinement(), seed=seed)
    lookup = {row['id']: row for row in rows}
    relevance = dict(zip(expanded.ids, map(float, baseline.normalize_relevance(union_features.l6_logits))))
    raw_cosine = dict(zip(features.ids, map(float, features.cosine_scores)))
    results = [{'id': did, 'document': lookup[did]['document'], 'metadata': lookup[did]['metadata'],
                'cosine_score': raw_cosine[did], 'similarity_score': raw_cosine[did],
                'rank_score': known[did], 'l6_logit': known[did],
                'normalized_relevance': relevance[did], 'sampling_probability': None,
                'search_method': 'l6_gas'} for did in selected.ranked_ids]
    timing = {'dense_retrieval': dense_ms, 'lexical_scoring': lexical_ms,
        'hybrid_prefilter': prefilter_ms, 'original_l6_inference': original_timing['inference_ms'],
        'baseline_selection': base.timings_ms['total_ms'], 'union_prefilter': union_ms,
        'additional_l6_inference': extra_timing['inference_ms'],
        'refinement_selection': selected.timings_ms['total_ms']}
    for key in ('model_loading_ms', 'model_warmup_ms', 'l6_queue_ms'):
        timing[key] = original_timing[key] + extra_timing[key]
    return {'results': results, 'search_method': 'l6_gas', 'requested_search_method': 'l6_gas',
        'candidate_count': len(features.ids), 'fallback_reason':
            selected.status if 'fallback' in selected.status else None,
        'ranking_time_ms': (time.perf_counter() - start) * 1000, 'timings_ms': timing,
        'quantum': {'representation': 'compact noiseless classical simulation; no physical QPU execution',
            'model': L6_MODEL, 'model_revision': L6_REVISION,
            'application_profile': asdict(profile), 'passage_adaptation': True,
            'eligible_passages': len(rows), 'dense_candidates': len(features.ids),
            'union_candidates': len(expanded.ids), 'additional_l6_pairs': len(missing),
            'ordering_policy': 'baseline first five fixed; raw-L6 ordered tail',
            'baseline': base.to_dict(), 'refinement': selected.to_dict()}}
