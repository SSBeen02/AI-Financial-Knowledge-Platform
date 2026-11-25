-- 복습만 저장. 최초 제출과 학습·게임 상태는 변경하지 않는다.
create table if not exists public.quiz_reviews (
  id text primary key,
  user_id text not null,
  submission_id text not null references public.quiz_submissions(id),
  question_index integer not null,
  idempotency_key varchar(200) not null,
  submitted_answer varchar(500) not null,
  is_correct boolean not null,
  created_at timestamptz not null,
  constraint uq_quiz_reviews_user_key unique (user_id, idempotency_key)
);
create index if not exists ix_quiz_reviews_source
  on public.quiz_reviews(user_id, submission_id, question_index, created_at);
alter table public.quiz_reviews enable row level security;
