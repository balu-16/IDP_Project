-- Keep the live chat_history table aligned with the app's idempotent chat API
-- and the provenance returned to clients for citations and retrieval details.
ALTER TABLE public.chat_history
    ADD COLUMN IF NOT EXISTS run_id uuid,
    ADD COLUMN IF NOT EXISTS provenance jsonb;

CREATE UNIQUE INDEX IF NOT EXISTS chat_history_run_id_uidx
    ON public.chat_history (user_id, chat_id, run_id)
    WHERE run_id IS NOT NULL;
