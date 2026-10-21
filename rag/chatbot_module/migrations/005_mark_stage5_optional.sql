-- Stage 5(TESAT·매경TEST 빈출 핵심 용어)를 선택 과정으로 표시한다.
-- 003 시드를 이미 적용한 DB용. 학습 흐름(스테이지 개방 순서)은 바뀌지 않는다.

begin;

update public.stages
set is_optional = true
where stage_id = 'stage5';

commit;
