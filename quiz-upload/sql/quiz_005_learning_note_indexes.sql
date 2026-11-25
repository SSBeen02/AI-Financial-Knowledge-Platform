-- 학습노트 조회용 인덱스. 공유 DB 적용 전 관련 담당자가 검토한다.
-- 기존 DB에는 create_all이 인덱스를 추가하지 않으므로 이 migration을 적용한다.
create index if not exists ix_quiz_sets_user_stage_created
  on public.quiz_sets (user_id, stage_id, created_at);
create index if not exists ix_quiz_sets_user_created
  on public.quiz_sets (user_id, created_at);
