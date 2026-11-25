-- Apply as a separately reviewed migration before deploying the new game code.
-- Existing records are not reconstructed; logging begins after deployment.
CREATE TABLE public.game_audit_logs (
  audit_id varchar(36) PRIMARY KEY,
  user_id varchar(36) NOT NULL,
  character_id varchar(36) NOT NULL REFERENCES public.game_characters(character_id),
  change_type varchar(30) NOT NULL,
  source_type varchar(30) NOT NULL,
  source_id varchar(200) NOT NULL,
  before_value json NOT NULL,
  after_value json NOT NULL,
  created_at timestamptz NOT NULL
);
CREATE INDEX ix_game_audit_logs_user_id ON public.game_audit_logs(user_id);
CREATE INDEX ix_game_audit_logs_character_id ON public.game_audit_logs(character_id);
ALTER TABLE public.game_audit_logs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.game_audit_logs FROM public, anon, authenticated;
GRANT SELECT ON TABLE public.game_audit_logs TO authenticated;
CREATE POLICY game_select_own ON public.game_audit_logs FOR SELECT TO authenticated
  USING (user_id = (SELECT auth.uid())::text);
CREATE FUNCTION public.game_audit_append_only() RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN RAISE EXCEPTION 'audit log is append only'; END; $$;
CREATE TRIGGER game_audit_no_mutation BEFORE UPDATE OR DELETE ON public.game_audit_logs
  FOR EACH ROW EXECUTE FUNCTION public.game_audit_append_only();
CREATE TRIGGER game_audit_no_truncate BEFORE TRUNCATE ON public.game_audit_logs
  FOR EACH STATEMENT EXECUTE FUNCTION public.game_audit_append_only();
