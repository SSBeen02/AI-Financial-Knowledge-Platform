-- 기존 데이터는 삭제하지 않는다. Supabase SQL Editor에서 실행할 증분 마이그레이션.
begin;
alter table public.diagnostic_attempts
  add column if not exists retry_count integer not null default 0,
  add column if not exists report_started_at timestamptz;

-- 응시 시작은 반드시 이 함수를 통해 실행한다. 과거 중복은 제출된 응시를 우선한다.
create or replace function public.start_diagnostic_once(p_record jsonb)
returns setof public.diagnostic_attempts
language plpgsql security definer set search_path = public
as $$
declare existing public.diagnostic_attempts;
begin
  if coalesce(p_record->>'user_id', '') = '' then
    raise exception 'user_id is required';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_record->>'user_id', 0));
  select * into existing from public.diagnostic_attempts
    where user_id = p_record->>'user_id'
    order by (status = 'pending'), started_at, id limit 1;
  if found then
    return next existing;
    return;
  end if;
  return query insert into public.diagnostic_attempts
    (id, user_id, status, started_at, questions_snapshot, retry_count)
    values ((p_record->>'id')::uuid, p_record->>'user_id', 'pending',
      (p_record->>'started_at')::timestamptz, p_record->'questions_snapshot', 0)
    returning *;
end;
$$;
revoke all on function public.start_diagnostic_once(jsonb) from public, anon, authenticated;
grant execute on function public.start_diagnostic_once(jsonb) to service_role;
commit;
