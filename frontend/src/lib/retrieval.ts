import type { RetrievalStrategy } from './contracts';

export const DEFAULT_RETRIEVAL: RetrievalStrategy = 'l6_gas';

export function retrievalSettings(strategy: RetrievalStrategy) {
  if (strategy === 'l6_gas') {
    return { strategy, top_k: 8, candidate_limit: 64, seed: 0 };
  }
  return { strategy, top_k: 5, candidate_limit: 64, threshold: 0.5, shots: 1024, seed: 0 };
}

export interface SubmittedMessage {
  id: string;
  text: string;
  runId: string;
  retrieval: ReturnType<typeof retrievalSettings>;
}

export function chatRequest(message: SubmittedMessage) {
  return { session_id: message.id, message: message.text, run_id: message.runId,
    temperature: 0, retrieval: message.retrieval };
}
