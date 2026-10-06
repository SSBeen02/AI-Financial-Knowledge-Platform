-- Rename the learning session stage column to the shared stage_id convention.
-- Apply after 001_learning_management.sql, 002_enable_rls.sql, and
-- 003_seed_stages_concepts.sql. PostgreSQL preserves the existing data,
-- indexes, and dependent foreign-key references during a column rename.

do $$
begin
    if exists (
        select 1
        from information_schema.columns
        where table_schema = 'public'
          and table_name = 'learning_sessions'
          and column_name = 'stage'
    ) and not exists (
        select 1
        from information_schema.columns
        where table_schema = 'public'
          and table_name = 'learning_sessions'
          and column_name = 'stage_id'
    ) then
        alter table public.learning_sessions rename column stage to stage_id;
    end if;
end
$$;
