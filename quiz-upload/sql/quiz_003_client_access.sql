-- Supabase only. Owner-only APIs remain the public access path.
-- quiz_sets contains answer/explanation JSON: do NOT grant raw SELECT to learners.
-- The server must use a protected backend role with the required DB privileges.
-- Never expose that credential to browsers. Never apply before checking the server role.
begin;
alter table public.quiz_sets enable row level security;
alter table public.quiz_submissions enable row level security;
revoke all privileges on table public.quiz_sets from anon, authenticated;
revoke all privileges on table public.quiz_submissions from anon, authenticated;
-- No permissive client policies: default deny plus revoked privileges.
-- Do not grant direct client INSERT/UPDATE: grading and ownership are enforced by APIs.
commit;
