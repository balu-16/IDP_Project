import assert from 'node:assert/strict';
import test from 'node:test';
import { chatResponseSchema } from '../src/lib/contracts.ts';
import { DEFAULT_RETRIEVAL, retrievalSettings, chatRequest } from '../src/lib/retrieval.ts';

test('new messages default to eight-passage GAS; legacy settings stay explicit', () => {
  assert.equal(DEFAULT_RETRIEVAL, 'l6_gas');
  assert.deepEqual(retrievalSettings(DEFAULT_RETRIEVAL), {
    strategy: 'l6_gas', top_k: 8, candidate_limit: 64, seed: 0,
  });
  for (const strategy of ['cosine', 'grover', 'closed_form', 'classical_sampling'] as const) {
    assert.equal(retrievalSettings(strategy).top_k, 5);
    assert.equal(retrievalSettings(strategy).strategy, strategy);
  }
});

test('retry keeps submitted settings instead of reading a changed dropdown', () => {
  let selected = DEFAULT_RETRIEVAL;
  const variables = { id: '1', text: 'Question', runId: 'a-request', retrieval: retrievalSettings(selected) };
  const original = chatRequest(variables);
  selected = 'cosine';
  const anotherMessage = chatRequest({ ...variables, retrieval: retrievalSettings(selected) });
  assert.equal(anotherMessage.retrieval.strategy, 'cosine');
  assert.deepEqual(chatRequest(variables), original);
  assert.equal(chatRequest(variables).retrieval.strategy, 'l6_gas');
});

test('old provenance and new negative L6 logits both satisfy the response contract', () => {
  const oldSource = { id: 'p1', document: 'A source passage.', metadata: { page_start: 1 },
    cosine_score: 0.6, rank_score: 0.6, sampling_probability: null, search_method: 'cosine' };
  const oldResponse = { success: true, response: 'Answer [S1]', session_id: '1',
    run_id: '00000000-0000-4000-8000-000000000001', context_used: true,
    context_sources: [oldSource], retrieval_time_ms: 12, processing_time_ms: 20,
    metadata: { retrieval_method: 'cosine', fallback_reason: null } };
  assert.equal(chatResponseSchema.parse(oldResponse).context_sources.length, 1);
  const modern = { ...oldResponse, context_sources: [{ ...oldSource, search_method: 'l6_gas',
    rank_score: -2, l6_logit: -2, normalized_relevance: 0.25 }],
    metadata: { retrieval_method: 'l6_gas', fallback_reason: null, quantum: { refinement: {} } } };
  assert.equal(chatResponseSchema.parse(modern).context_sources[0].l6_logit, -2);
  assert.equal(chatResponseSchema.safeParse({ ...modern,
    context_sources: [{ ...modern.context_sources[0], l6_logit: Infinity }] }).success, false);
});
