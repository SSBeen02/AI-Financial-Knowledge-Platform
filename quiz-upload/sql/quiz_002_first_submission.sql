-- PostgreSQL/Supabase: inspect and apply manually in a maintenance window.
-- No existing rows are deleted. Duplicates abort the entire migration.
begin;
lock table public.quiz_submissions in share row exclusive mode;
do $$
begin
  if exists (select 1 from public.quiz_submissions group by quiz_set_id having count(*) > 1) then
    raise exception 'Multiple first submissions exist. Review their learning/review references before migration; no records were deleted.';
  end if;
  if not exists (select 1 from pg_constraint
    where conrelid = 'public.quiz_submissions'::regclass
      and conname = 'uq_quiz_submissions_quiz_set') then
    alter table public.quiz_submissions
      add constraint uq_quiz_submissions_quiz_set unique (quiz_set_id);
  end if;
end $$;
commit;
