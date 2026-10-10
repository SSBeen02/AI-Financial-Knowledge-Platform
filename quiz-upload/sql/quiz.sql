-- 모듈 5. 동적 퀴즈와 학습노트
-- 학습노트와 오답노트는 별도 테이블로 만들지 않습니다.
-- 학습노트 조회는 quiz_sets와 quiz_submissions의 outer join입니다.
-- stage_id는 학습노트 stage_id 필터, idempotency_key는 중복 제출 구분에 사용합니다.

create table if not exists public.quiz_sets (
  id text primary key,
  user_id text not null,
  concept_id text not null,
  learning_session_id text not null,
  stage_id text,
  questions jsonb not null default '[]'::jsonb,
  status text not null check (status in ('pending', 'processing', 'completed', 'failed')),
  created_at timestamptz not null
);

comment on table public.quiz_sets is
  'Gemini가 만든 OX 2문항과 상황형 1문항. 정답은 questions JSON에만 있고 조회 API에서는 빼서 반환합니다.';

create unique index if not exists quiz_sets_user_session_idx
  on public.quiz_sets (user_id, learning_session_id);

create index if not exists quiz_sets_user_id_idx on public.quiz_sets (user_id);
create index if not exists quiz_sets_user_concept_idx on public.quiz_sets (user_id, concept_id);
create index if not exists quiz_sets_stage_id_idx on public.quiz_sets (stage_id);

create table if not exists public.quiz_submissions (
  id text primary key,
  quiz_set_id text not null references public.quiz_sets (id),
  user_id text not null,
  idempotency_key text not null,
  submitted_answers jsonb not null,
  is_correct_list jsonb not null,
  correct_count integer not null,
  is_passed boolean not null,
  created_at timestamptz not null,
  unique (user_id, idempotency_key)
);

comment on table public.quiz_submissions is
  '퀴즈 제출. is_passed는 3문항 중 2문항 이상 정답일 때 true입니다.';

create index if not exists quiz_submissions_quiz_set_id_idx
  on public.quiz_submissions (quiz_set_id);

alter table public.quiz_sets enable row level security;
alter table public.quiz_submissions enable row level security;
