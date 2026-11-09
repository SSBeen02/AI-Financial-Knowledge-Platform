-- 제출 이력 조회용 인덱스만 추가한다. RLS·정책·접근 권한은 변경하지 않는다.
create index if not exists ix_quiz_submissions_user_created_set
  on public.quiz_submissions(user_id, created_at desc, id desc, quiz_set_id);
create index if not exists ix_quiz_submissions_user_set
  on public.quiz_submissions(user_id, quiz_set_id);
