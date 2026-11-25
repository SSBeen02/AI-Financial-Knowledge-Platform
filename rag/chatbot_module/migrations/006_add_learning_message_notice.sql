-- 답변과 함께 전송한 안내를 assistant 메시지에 보존한다.
-- 기존 행은 NULL이며 재실행해도 안전하다.

ALTER TABLE public.learning_messages
    ADD COLUMN IF NOT EXISTS notice TEXT NULL;
