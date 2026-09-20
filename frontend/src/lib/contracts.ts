import { z } from 'zod';

export const profileSchema = z.object({
  id: z.number().int().positive(),
  auth_user_id: z.string().uuid(),
  full_name: z.string(),
  email: z.string().email(),
  phone_number: z.string().nullable(),
  created_at: z.string().nullable(),
});
export type Profile = z.infer<typeof profileSchema>;
export const sourceSchema = z.object({
  id: z.string(),
  document: z.string(),
  metadata: z.record(z.union([z.string(), z.number(), z.boolean(), z.null()])),
  cosine_score: z.number(),
  rank_score: z.number(),
  sampling_probability: z.number().nullable(),
  search_method: z.string(),
});
export type Source = z.infer<typeof sourceSchema>;
export const chatResponseSchema = z.object({
  success: z.literal(true), response: z.string(), session_id: z.string(),
  run_id: z.string().uuid(), context_used: z.boolean(),
  context_sources: z.array(sourceSchema), retrieval_time_ms: z.number(),
  processing_time_ms: z.number(),
  metadata: z.object({ retrieval_method: z.string(), fallback_reason: z.string().nullable() }).passthrough(),
});
export type ChatResponse = z.infer<typeof chatResponseSchema>;
export type RetrievalStrategy = 'cosine' | 'grover' | 'closed_form' | 'classical_sampling';
