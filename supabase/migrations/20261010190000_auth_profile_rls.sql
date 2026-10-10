-- Link Supabase Auth identities to QubitChat profiles and close anonymous table
-- access. Apply using the Supabase SQL Editor or another database-owner role.

ALTER TABLE public.signup_users
    ADD COLUMN IF NOT EXISTS auth_user_id uuid;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.signup_users'::regclass
          AND conname = 'signup_users_auth_user_id_fkey'
    ) THEN
        ALTER TABLE public.signup_users
            ADD CONSTRAINT signup_users_auth_user_id_fkey
            FOREIGN KEY (auth_user_id) REFERENCES auth.users(id)
            ON DELETE SET NULL;
    END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS signup_users_auth_user_id_uidx
    ON public.signup_users (auth_user_id)
    WHERE auth_user_id IS NOT NULL;

-- Link only confirmed auth accounts where both sides have exactly one
-- normalized-email match. Existing profile IDs (and their chat rows) remain.
WITH candidates AS (
    SELECT su.id AS profile_id,
           au.id AS auth_id,
           count(*) OVER (PARTITION BY su.id) AS profile_match_count,
           count(*) OVER (PARTITION BY au.id) AS auth_match_count
    FROM public.signup_users AS su
    JOIN auth.users AS au
      ON lower(btrim(su.email)) = lower(btrim(au.email))
    WHERE su.auth_user_id IS NULL
      AND au.email_confirmed_at IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM public.signup_users AS linked
          WHERE linked.auth_user_id = au.id
      )
), safe_matches AS (
    SELECT profile_id, auth_id
    FROM candidates
    WHERE profile_match_count = 1 AND auth_match_count = 1
)
UPDATE public.signup_users AS su
SET auth_user_id = matches.auth_id
FROM safe_matches AS matches
WHERE su.id = matches.profile_id
  AND su.auth_user_id IS NULL;

-- Create or link a profile only after the auth email is confirmed. Linking by
-- normalized email preserves existing profile IDs and their associated chats.
CREATE OR REPLACE FUNCTION public.sync_confirmed_auth_profile()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    matched_profile_id bigint;
    matching_profile_count integer;
BEGIN
    IF NEW.email_confirmed_at IS NULL OR NEW.email IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT su.id
      INTO matched_profile_id
      FROM public.signup_users AS su
     WHERE su.auth_user_id = NEW.id
     LIMIT 1;

    IF FOUND THEN
        UPDATE public.signup_users
           SET email = NEW.email
         WHERE id = matched_profile_id
           AND email IS DISTINCT FROM NEW.email;
        RETURN NEW;
    END IF;

    SELECT count(*)
      INTO matching_profile_count
      FROM public.signup_users AS su
     WHERE lower(btrim(su.email)) = lower(btrim(NEW.email));

    IF matching_profile_count = 1 THEN
        UPDATE public.signup_users AS su
           SET auth_user_id = NEW.id,
               full_name = COALESCE(
                   NULLIF(btrim(su.full_name), ''),
                   NULLIF(btrim(NEW.raw_user_meta_data ->> 'full_name'), ''),
                   'QubitChat User'
               ),
               phone_number = COALESCE(
                   NULLIF(btrim(su.phone_number), ''),
                   NULLIF(btrim(NEW.raw_user_meta_data ->> 'phone_number'), '')
               )
         WHERE lower(btrim(su.email)) = lower(btrim(NEW.email))
           AND (su.auth_user_id IS NULL OR su.auth_user_id = NEW.id);

        IF FOUND THEN
            RETURN NEW;
        END IF;

        RAISE WARNING 'Confirmed auth profile has a conflicting existing link; manual review is required';
        RETURN NEW;
    ELSIF matching_profile_count > 1 THEN
        RAISE WARNING 'Confirmed auth profile has ambiguous normalized-email matches; manual review is required';
        RETURN NEW;
    END IF;

    INSERT INTO public.signup_users (auth_user_id, full_name, email, phone_number)
    VALUES (
        NEW.id,
        COALESCE(NULLIF(btrim(NEW.raw_user_meta_data ->> 'full_name'), ''), 'QubitChat User'),
        NEW.email,
        NULLIF(btrim(NEW.raw_user_meta_data ->> 'phone_number'), '')
    )
    ON CONFLICT (auth_user_id) WHERE auth_user_id IS NOT NULL DO NOTHING;

    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION public.sync_confirmed_auth_profile() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS qubitchat_auth_profile_insert ON auth.users;
CREATE TRIGGER qubitchat_auth_profile_insert
AFTER INSERT ON auth.users
FOR EACH ROW EXECUTE FUNCTION public.sync_confirmed_auth_profile();

DROP TRIGGER IF EXISTS qubitchat_auth_profile_confirmation ON auth.users;
CREATE TRIGGER qubitchat_auth_profile_confirmation
AFTER UPDATE OF email, email_confirmed_at ON auth.users
FOR EACH ROW EXECUTE FUNCTION public.sync_confirmed_auth_profile();

-- This narrowly scoped SECURITY DEFINER lookup avoids recursive profile RLS
-- checks in policies on the three tables that store the numeric profile ID.
CREATE OR REPLACE FUNCTION public.current_signup_user_id()
RETURNS bigint
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
    SELECT su.id::bigint
    FROM public.signup_users AS su
    WHERE su.auth_user_id = auth.uid()
    LIMIT 1
$$;

REVOKE ALL ON FUNCTION public.current_signup_user_id() FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.current_signup_user_id() TO authenticated;

-- Replace any previous broad policies on these private tables with explicit
-- owner-only policies. The browser and backend continue using user JWTs.
DO $$
DECLARE
    existing_policy record;
BEGIN
    FOR existing_policy IN
        SELECT schemaname, tablename, policyname
        FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = ANY (ARRAY['signup_users', 'chats', 'chat_history', 'uploaded_files'])
    LOOP
        EXECUTE format('DROP POLICY %I ON %I.%I',
                       existing_policy.policyname,
                       existing_policy.schemaname,
                       existing_policy.tablename);
    END LOOP;
END
$$;

ALTER TABLE public.signup_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chats ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.uploaded_files ENABLE ROW LEVEL SECURITY;

REVOKE ALL PRIVILEGES ON TABLE
    public.signup_users, public.chats, public.chat_history, public.uploaded_files
FROM PUBLIC, anon, authenticated;

-- Column-level grants survive a table-level REVOKE, so clear them as well.
DO $$
DECLARE
    target_table text;
    target_column text;
    target_role text;
    role_sql text;
BEGIN
    FOREACH target_table IN ARRAY ARRAY['signup_users', 'chats', 'chat_history', 'uploaded_files'] LOOP
        FOR target_column IN
            SELECT c.column_name
            FROM information_schema.columns AS c
            WHERE c.table_schema = 'public' AND c.table_name = target_table
        LOOP
            FOREACH target_role IN ARRAY ARRAY['PUBLIC', 'anon', 'authenticated'] LOOP
                role_sql := CASE WHEN target_role = 'PUBLIC' THEN 'PUBLIC' ELSE quote_ident(target_role) END;
                EXECUTE format('REVOKE ALL PRIVILEGES (%I) ON TABLE public.%I FROM %s',
                               target_column, target_table, role_sql);
            END LOOP;
        END LOOP;
    END LOOP;
END
$$;

GRANT SELECT ON TABLE public.signup_users TO authenticated;
GRANT UPDATE (full_name, phone_number) ON TABLE public.signup_users TO authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.chats TO authenticated;
GRANT SELECT, INSERT, DELETE ON TABLE public.chat_history TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.uploaded_files TO authenticated;

DO $$
DECLARE
    table_name text;
    sequence_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['chats', 'chat_history', 'uploaded_files'] LOOP
        sequence_name := pg_get_serial_sequence(format('public.%I', table_name), 'id');
        IF sequence_name IS NOT NULL THEN
            EXECUTE format('REVOKE ALL ON SEQUENCE %s FROM PUBLIC, anon, authenticated', sequence_name);
            EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO authenticated', sequence_name);
        END IF;
    END LOOP;
END
$$;

CREATE POLICY signup_users_select_own
    ON public.signup_users FOR SELECT TO authenticated
    USING (auth_user_id = (SELECT auth.uid()));

CREATE POLICY signup_users_update_own
    ON public.signup_users FOR UPDATE TO authenticated
    USING (auth_user_id = (SELECT auth.uid()))
    WITH CHECK (auth_user_id = (SELECT auth.uid()));

CREATE POLICY chats_select_own
    ON public.chats FOR SELECT TO authenticated
    USING (user_id = (SELECT public.current_signup_user_id()));

CREATE POLICY chats_insert_own
    ON public.chats FOR INSERT TO authenticated
    WITH CHECK (user_id = (SELECT public.current_signup_user_id()));

CREATE POLICY chats_update_own
    ON public.chats FOR UPDATE TO authenticated
    USING (user_id = (SELECT public.current_signup_user_id()))
    WITH CHECK (user_id = (SELECT public.current_signup_user_id()));

CREATE POLICY chats_delete_own
    ON public.chats FOR DELETE TO authenticated
    USING (user_id = (SELECT public.current_signup_user_id()));

CREATE POLICY chat_history_select_own
    ON public.chat_history FOR SELECT TO authenticated
    USING (
        user_id = (SELECT public.current_signup_user_id())
        AND EXISTS (
            SELECT 1 FROM public.chats AS c
            WHERE c.id = chat_history.chat_id
              AND c.user_id = (SELECT public.current_signup_user_id())
        )
    );

CREATE POLICY chat_history_insert_own
    ON public.chat_history FOR INSERT TO authenticated
    WITH CHECK (
        user_id = (SELECT public.current_signup_user_id())
        AND EXISTS (
            SELECT 1 FROM public.chats AS c
            WHERE c.id = chat_history.chat_id
              AND c.user_id = (SELECT public.current_signup_user_id())
        )
    );

CREATE POLICY chat_history_delete_own
    ON public.chat_history FOR DELETE TO authenticated
    USING (
        user_id = (SELECT public.current_signup_user_id())
        AND EXISTS (
            SELECT 1 FROM public.chats AS c
            WHERE c.id = chat_history.chat_id
              AND c.user_id = (SELECT public.current_signup_user_id())
        )
    );

CREATE POLICY uploaded_files_select_own
    ON public.uploaded_files FOR SELECT TO authenticated
    USING (
        user_id = (SELECT public.current_signup_user_id())
        AND EXISTS (
            SELECT 1 FROM public.chats AS c
            WHERE c.id = uploaded_files.chat_session_id
              AND c.user_id = (SELECT public.current_signup_user_id())
        )
    );

CREATE POLICY uploaded_files_insert_own
    ON public.uploaded_files FOR INSERT TO authenticated
    WITH CHECK (
        user_id = (SELECT public.current_signup_user_id())
        AND EXISTS (
            SELECT 1 FROM public.chats AS c
            WHERE c.id = uploaded_files.chat_session_id
              AND c.user_id = (SELECT public.current_signup_user_id())
        )
    );

CREATE POLICY uploaded_files_update_own
    ON public.uploaded_files FOR UPDATE TO authenticated
    USING (
        user_id = (SELECT public.current_signup_user_id())
        AND EXISTS (
            SELECT 1 FROM public.chats AS c
            WHERE c.id = uploaded_files.chat_session_id
              AND c.user_id = (SELECT public.current_signup_user_id())
        )
    )
    WITH CHECK (
        user_id = (SELECT public.current_signup_user_id())
        AND EXISTS (
            SELECT 1 FROM public.chats AS c
            WHERE c.id = uploaded_files.chat_session_id
              AND c.user_id = (SELECT public.current_signup_user_id())
        )
    );

CREATE POLICY uploaded_files_delete_own
    ON public.uploaded_files FOR DELETE TO authenticated
    USING (
        user_id = (SELECT public.current_signup_user_id())
        AND EXISTS (
            SELECT 1 FROM public.chats AS c
            WHERE c.id = uploaded_files.chat_session_id
              AND c.user_id = (SELECT public.current_signup_user_id())
        )
    );

NOTIFY pgrst, 'reload schema';

-- Review rows the automatic backfill intentionally left unlinked.
WITH matches AS (
    SELECT su.id AS profile_id,
           su.email,
           count(DISTINCT au.id) FILTER (WHERE au.email_confirmed_at IS NOT NULL) AS confirmed_auth_matches,
           (SELECT count(*) FROM public.signup_users AS same_email
             WHERE lower(btrim(same_email.email)) = lower(btrim(su.email))) AS profile_matches
    FROM public.signup_users AS su
    LEFT JOIN auth.users AS au
      ON lower(btrim(su.email)) = lower(btrim(au.email))
    WHERE su.auth_user_id IS NULL
    GROUP BY su.id, su.email
)
SELECT profile_id, email, confirmed_auth_matches, profile_matches
FROM matches
WHERE confirmed_auth_matches <> 1 OR profile_matches <> 1
ORDER BY profile_id;

-- Review confirmed auth accounts that still have no linked profile.
SELECT au.id AS auth_user_id, au.email
FROM auth.users AS au
WHERE au.email_confirmed_at IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM public.signup_users AS su WHERE su.auth_user_id = au.id
  )
ORDER BY au.email;
