-- 사전테스트 시도 및 취약점 리포트
-- Supabase SQL Editor에서 한 번 실행합니다.
-- 서버는 service role 키로 이 테이블에 접근합니다. RLS를 켜 두면 anon 키로는 직접 읽거나 쓸 수 없습니다.

begin;

create table if not exists public.diagnostic_attempts (
  id uuid primary key default gen_random_uuid(),
  user_id text not null,
  status text not null check (status in ('pending', 'processing', 'completed', 'failed')),
  started_at timestamptz not null,
  submitted_at timestamptz,
  answers jsonb,
  questions_snapshot jsonb,
  submission_key text,
  error jsonb,
  summary jsonb,
  domain_scores jsonb,
  question_results jsonb,
  vulnerabilities jsonb,
  llm_report jsonb,
  report jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table public.diagnostic_attempts is
  '사전테스트 시도. 개별 채점·LLM 컬럼으로 GET /reports/{id} 응답을 구성합니다. report는 이전 데이터 호환용입니다. report id는 이 테이블의 id와 같습니다.';

-- 이미 테이블을 만들어 둔 경우에만 컬럼을 추가합니다.
alter table public.diagnostic_attempts
  add column if not exists llm_report jsonb,
  add column if not exists questions_snapshot jsonb,
  add column if not exists submission_key text,
  add column if not exists error jsonb;

comment on column public.diagnostic_attempts.llm_report is
  'LLM 맞춤 리포트 JSON. level_diagnosis, wrong_answer_analysis, recommendations';

create index if not exists diagnostic_attempts_user_id_idx
  on public.diagnostic_attempts (user_id);

alter table public.diagnostic_attempts enable row level security;

-- 이미 in_progress를 쓰던 테이블은 상태 제약을 문서 값으로 바꿉니다.
alter table public.diagnostic_attempts drop constraint if exists diagnostic_attempts_status_check;

update public.diagnostic_attempts
set status = 'pending'
where status = 'in_progress';

alter table public.diagnostic_attempts
  add constraint diagnostic_attempts_status_check
  check (status in ('pending', 'processing', 'completed', 'failed'));

commit;
