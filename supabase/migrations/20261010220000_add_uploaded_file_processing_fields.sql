-- Align uploaded_files with the owner-scoped document processing pipeline.
-- Existing rows are retained and labeled legacy; new uploads set their own
-- processing status and document metadata.
ALTER TABLE public.uploaded_files
    ADD COLUMN IF NOT EXISTS document_id text,
    ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'legacy',
    ADD COLUMN IF NOT EXISTS chunks_count integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS processing_version text;

CREATE UNIQUE INDEX IF NOT EXISTS uploaded_files_owner_session_document_uidx
    ON public.uploaded_files (user_id, chat_session_id, document_id)
    WHERE document_id IS NOT NULL;
