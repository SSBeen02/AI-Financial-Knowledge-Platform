# AGENTS.md — 「나의 경세학당」 RAG 챗봇 모듈

이 저장소는 Cursor로 1~4단계까지 구현한 뒤 Codex로 이어서 작업한다.
작업 전 이 문서와 `GUIDE/CHATBOT_SPEC.md`(명세 최신본)를 반드시 읽는다.

## 기준 문서
- `GUIDE/CHATBOT_SPEC.md` : 기능 명세. **10장 "확정 사항"이 다른 절과 충돌하면 10장이 우선**
- `rag_common.py` : 검색·인코더 공용 모듈 (**검색 로직 수정 금지**, import해서 사용)
- `data/stages.json` : 스테이지별 학습 개념 (Stage 1~5, 항목 250개, 고유 211개)

## 현재 진행 상황 (명세 8장 작업 순서 기준)
| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | config, schemas, integrations(X-User-Id 인증, SQL 기반 ConceptStatusService) | 완료 |
| 2 | concepts + `GET /learning/concepts` | 완료 |
| 3 | store(SQLAlchemy) + 상태·세션·대화 복원 API (`/learning/current`, `/learning/sessions/{id}`, `/messages`, `/history`) | 완료 |
| 4 | retrieval + 개념 캐시(시작 시 211개 1회 로드), SEARCH_PROFILES 자리 배분, band 판정 | 완료 |
| 5 | llm, prompts, relevance, 개념 감지 + `POST /learning/messages` | 완료 |
| 6 | 학습 완료, 학습 맥락, 퀴즈 결과 (`get_learning_context()`, `report_quiz_result()`) | 완료 |
| 7 | `POST /learning/messages/stream` (SSE) | 완료 |
| 8 | main_dev.py, README_chatbot.md | 완료 |

- **1~8단계 전체 구현 완료**
- 학습·스테이지 관리 A~D(실제 SQL 테이블·상태 전이·이벤트·QuizService·개발 화면) 구현 완료
- **3차 완료**: DB 자동 생성 제어, Supabase 001→002→003 SQL, 답변 지식 범위 3모드,
  역할별 README·API 요약까지 구현·문서화 완료
- **4차-B 완료**: 10/06 팀 문서 기준 history 시도 메타데이터·재학습 화면 구분선,
  `learning_sessions.stage_id` 보존 마이그레이션, CORS·fake LLM·팀 연동 예제를 반영
- **4차-C 완료**: 게임 이벤트 평면 계약, API 응답 `stage_id` 통일, 퀴즈·게임·프론트·인증
  연동 README와 Pydantic 검증 examples를 반영. dev UI 실시간 재학습 구분선과 한글·영문·숫자
  빠른 질문 조사 처리를 완료
- **LLM 제공자 확장**: `openai`·`fake`를 유지하면서 Upstage OpenAI 호환 Chat Completions를
  답변·SSE 스트리밍·관련성 판정에 추가하고 `LLM_BASE_URL` 설정과 mock 검증을 반영
- 테스트: Upstage 제공자 확장 기준 fake LLM·외부 연결 차단 전체 테스트 193개 통과, Qdrant 실제 연결 1개 skip
  (`python -m pytest -q`, 실제 OpenAI·Qdrant 호출 없음)
- 실제 메시지 확인: "분업/특화에 대해 알려줘" → 세션 시작, 1위 sisa_1281, band high, OpenAI 답변·두 행 저장 확인
- 실제 말투 확인: `CHAT_TONE=hao`로 "인플레이션에 대해 알려줘" OpenAI 1회 호출 → 4문장 하오체 응답 확인
- 실제 서버 수동 테스트: 추천 → 학습 → 완료 → 퀴즈 실패 → 재학습 → 통과 전체 흐름 명세 일치 확인

## 이미 확정된 동작 (바꾸지 말 것)
- 모드 우선순위: `quiz_generation_failed`/`quiz_pending` → `relearn` → `normal` (`/learning/current`, `/learning/concepts` 공통 함수)
  - `relearn`: `in_progress` 개념의 **최신 quiz_status가 failed**일 때만 (`quiz_status="failed"`는 유지)
  - 최신 quiz_status가 `passed`인데 개념 상태가 아직 `in_progress` → `quiz_pending` (상태 반영 대기)
  - 퀴즈 기록 없이 학습 중인 세션 → `normal`
  - `quiz_pending` 중 active 세션 존재는 불변 조건 위반 → 409
  - quiz_pending 안내는 `CHAT_TONE`을 따름. 기본 하오체: `현재 {term} 개념의 퀴즈 결과를 기다리는 중이오.`
- 검색: Dense 단독(KURE-v1), 하이브리드·리랭커 사용 안 함
- band: 최고 점수 ≥ `BAND_HIGH`(0.50) high / ≥ `BAND_LOW`(0.45) mid / 미만 low — concept_source 소스의 Dense 점수로만 판정
- 개념 캐시는 서버 시작 시 1회만 로드, 요청마다 Qdrant에서 개념을 조회하지 않음
- 메시지는 user/assistant 두 행, 응답 `message_id` 는 assistant 행
- 개념 상태·최신 퀴즈·attempt는 `(concept_id, stage_id)` 쌍으로 관리한다. 상태 코드는
  `not_started`/`in_progress`/`passed`이며 화면 문구는 `미학습`/`학습중`/`통과`로 고정한다. 현재 스테이지는 별도 저장하지
  않고 `not_started` 또는 `in_progress`가 남은 가장 낮은 단계로 계산한다. Stage 1~4 완료 후 Stage 5가
  되며, 겹치는 개념도 Stage 5에서 별도 `not_started`로 시작한다. Stage 5까지 완료해도 Stage 5를 유지한다.
- 챗봇 메시지는 `not_started → in_progress`만 변경한다. 퀴즈 모듈이 판정한 passed는 학습 관리의
  `apply_quiz_result()`가 `in_progress → passed`, 진행률, 이벤트를 한 트랜잭션으로 반영한다.
- 애플리케이션·DB·`stages.json`은 `concept_id`를 사용한다. 기존 Qdrant payload의 `doc_id`만 읽기
  하위 호환으로 남긴다.

## 5단계 구현 요점 (POST /learning/messages, 완료)
메시지 분기 순서:
1. active 세션이 있으면 그 세션에만 추가 (다른 개념 상태는 절대 변경하지 않음, 명세 3.5)
2. 최신 학습 맥락이 `quiz_pending` 이면 세션 없이 답변만, `free` 로 저장 (`concept_id` 가 있어도 세션 시작 안 함)
3. `in_progress` 개념의 최신 quiz_status가 `failed`이고 active 세션이 없으면 잠긴 `concept_id` 요청만
   `attempt+1` 재학습 세션을 연다. 다른 키워드 선택은 409, ID 없는 자유 질문은 free다.
4. `concept_id`가 현재 스테이지의 `not_started`이면 세션 시작, 아니면 409
5. 자유 질문에서 현재 스테이지 `not_started` 개념을 감지해도 기본값에서는 세션·상태를 바꾸지 않고
   `suggested_concept`와 학습 시작 notice를 반환한다. `FREE_QUESTION_AUTO_START=true`일 때만 이전 자동 시작.
6. 그 외는 답변만, `free` 로 저장
- 세션을 처음 열 때(keyword/detected)만 `mark_in_progress()`로 `not_started → in_progress`. 재학습 세션은 상태 변경 없음
- 관련성(is_related) 판정, mentioned_concepts, 프롬프트 구성은 명세 3.5, 5.1, 5.2, 10장을 따른다
- `keyword`/`detected` 첫 메시지만 `is_related=true`로 고정하고, `relearn` 첫 메시지는 일반 규칙으로 판정한다
- `GET /learning/concepts`와 메시지 요청은 `stage` 입력을 받지 않고 항상 `get_current_stage()` 결과만 사용한다
- LLM: OpenAI 어댑터. `LLM_MODEL`, `LLM_RELEVANCE_MODEL`(미지정·빈 값이면 `LLM_MODEL`)
  - **추론 강도(reasoning effort)를 설정값 `LLM_REASONING_EFFORT` 로 분리**. 코드 기본값은 빈 값(파라미터 생략), `.env.example`은 `low`
  - 답변 최대 토큰도 설정값으로 분리
- 화면 표시는 `display_sources`를 사용한다. 현재 세션 개념은 검색됐으면 항상 표시하고, 다른 문서는 `DISPLAY_SOURCE_MIN_SCORE`(기본 0.60) 이상만 표시한다. `sources`는 LLM 전체 근거 및 저장용으로 그대로 유지한다.
- `CHAT_TONE`은 `hao`(기본, 읽기 쉬운 학당 훈장 하오체) 또는 `modern`(해요체)이며 답변과 범위 밖·재학습·퀴즈 대기 안내에 일관되게 적용한다.

## 6단계 구현 요점 (학습 완료·학습 맥락·퀴즈 결과, 완료)
- `POST /learning/sessions/{id}/complete`: 필수 `Idempotency-Key`를 받아 active 세션을 완료하고 세션의
  모든 완성된 user/assistant 쌍을 `is_related`와 함께 학습 맥락으로 저장한다. 같은 키 재요청은 최초
  결과를 그대로 반환한다. free 메시지는 제외하며 관련 대화가 없으면 400이다.
- 학습 맥락의 `definition`은 캐시 문서의 `설명:` 이하이며, 세션의 모든 질문에서 현재 개념을 제외한 명시적 용어/별칭을 `mentioned_concepts`로 중복 없이 기록한다. 퀴즈 출제 중심과 상태 갱신 대상은 처음 개념의 `(concept_id, stage_id)` 하나다.
- `GET /learning/sessions/{id}/learning-context`, `GET /learning/learning-contexts?status=completed`로 본인 맥락을 조회한다. 타 사용자 세션은 404다.
- `POST /learning/sessions/{id}/quiz-result`는 `submission_id`, concept·stage, correct_count, passed를 받아
  실제 SQL 상태와 이벤트를 멱등 반영한다.
- failed 결과 후 잠긴 `concept_id` 요청은 같은 개념의 `attempt+1` 재학습 세션을 열며, 통과 후에는 다음 `not_started` 개념 5개가 노출된다.
- `quiz-result`는 완료 및 `pending` 상태인 학습 맥락에 한 번만 기록한다. active 세션과 결과 중복 제출은 409다.
- 완료 세션은 메시지 요청으로 직접 지정할 수 없다. 완료 후 `quiz_pending` 입력은 기존 세션에 추가하지 않고 free 메시지로 저장하며, failed 이후 입력은 새 attempt 재학습 세션을 연다.

## 7단계 구현 요점 (POST /learning/messages/stream, 완료)
- 비스트리밍과 SSE가 `prepare_message()`와 최종 저장 함수를 공유해 분기·검색·관련성·검증 결과가 같다.
- OpenAI Responses 스트림의 `response.output_text.delta`만 `event: token`으로 변환하고, 정상 종료 뒤 범위/출처 suffix까지 토큰으로 전송한다.
- 모든 토큰 생성이 성공하고 클라이언트 연결이 유지된 경우에만 세션 생성, `mark_in_progress()`, user/assistant 두 행 저장을 수행한 뒤 `event: done`을 보낸다.
- 중간 LLM 오류는 `{code,message,request_id}`의 `event: error`로 종료하며, 연결 끊김은 조용히 중단한다. 둘 다 저장 및 상태 변경이 없다.
- `done`은 답변 본문을 제외한 메시지 메타데이터이며 `sources`, `display_sources`, `message_id`를 포함한다.

## 8단계 구현 요점 (로컬 실행·인수인계 문서, 완료)
- `main_dev.py`는 FastAPI lifespan에서 설정, 카탈로그, DB, Qdrant, Dense 인코더, 211개 개념 캐시, 검색기, LLM 어댑터를 프로세스당 한 번 준비한다.
- `README_chatbot.md`에 로컬 실행, 전체 환경변수, 백엔드·퀴즈·프론트 통합, POST SSE 파싱, 검색 소스 추가 절차를 정리했다.
- 명세 9장 완료 기준 16개를 모두 충족했다. 비교 질문 LLM 판정과 화면 복원 조회 API도 구현·테스트 완료했다.
- Supabase PostgreSQL 배포를 위해 psycopg 3 연결, Session pooler·RLS 및 migration SQL을 문서화했다.
  학습 관리 테이블은 실행 환경과 무관하게 생성·시드되며 `DEV_ENABLE_TOOLS`는 개발 라우트만 제어한다.
- 수동 검증용 `/learning/dev/stage`, `/learning/dev/reset`, `/learning/dev/status`와 단일 페이지 `/dev/chat`은 `DEV_ENABLE_TOOLS=true`인 `main_dev.py` 앱에서만 등록된다. 배포 설정에는 개발 라우트가 존재하지 않는다.
- 개발용 `/learning/dev/stage`는 지정 단계 이전의 상태를 모두 통과 처리하고 `/learning/dev/pass-all`은 현재
  단계 전체를 통과시킨다. `dev_user_stage`는 폐기했으며 기존 로컬 테이블은 시작 시 제거한다.
- 이 모듈이 개념 통과·스테이지 완료 이벤트를 `learning_events`에 기록하고, 승급·보상 판정은
  게임 모듈(김선빈)이 담당한다.
- 메시지 응답과 SSE `done`의 `notice`는 다른 스테이지·통과·extra·excluded·low band 안내를 LLM과 분리해 서버가 생성한다. extra/excluded는 검색 1위 용어/별칭이 질문에 실제 포함된 경우만 적용한다.
- `/learning/current`는 active 세션이 없을 때 `complete_hint`를 주며 `learning_guide`, 상태 표시 매핑,
  현재 스테이지 `progress`를 포함한다. 전체 진행률은 `GET /learning/progress`에서 Stage 1~5별로 제공하고
  `passed` 개수만 퍼센트에 반영한다.
- 모든 JSON 오류는 `{code,message,request_id}`이며 응답 헤더에 `X-Request-ID`가 붙는다. 시간은 UTC
  ISO 8601이고 로그에는 토큰·비밀번호·요청 본문을 기록하지 않는다.
- `learning_sessions`와 `learning_messages`를 사용하며 기존 SQLite `chat_*` 테이블·`doc_id` 데이터와
  한국어 상태값은 시작 시 보존 마이그레이션한다. 이전 `dev_concept_status`도 실제
  `user_concept_progress`로 이전한 뒤 제거한다. 사용자당 active 세션과 `in_progress` 상태는 DB
  부분 유일 제약으로 각각 하나만 허용한다.

## 학습·스테이지 관리 실제 구현 (A~D 완료)

- `stages`, `concepts`, `user_concept_progress`, `user_stage_progress`, `learning_events` 및 내부 멱등
  테이블을 SQLAlchemy와 PostgreSQL migration으로 관리하고 `stages.json` 250행을 멱등 시드한다.
- `user_stage_progress`는 `in_progress`/`completed`; 행이 없으면 잠김이다. Stage 1만 행 없이 열리며
  첫 학습 시작 때 행을 만든다. 마지막 개념 통과 트랜잭션이 다음 단계 행을 연다.
- 퀴즈 완료 응답은 학습 맥락과 `quiz {quiz_set_id,status}`를 함께 반환한다. 생성 실패는
  `quiz_generation_failed`, 재요청은 새 `start_type=quiz_retry` 완료 세션과 같은 attempt를 쓴다.
- 게임 모듈은 `get_unprocessed_events()`/`mark_event_processed()`, 퀴즈 학습노트는
  `get_concept_status()`를 사용하며 테이블을 직접 읽지 않는다.
- `/learning/current.quick_prompts`와 학습 중 개념 칩을 제공하고, 학습 중에는 다른 키워드를 잠근다.
- 단위 테스트는 실제 `.env`와 OS의 LLM/Qdrant 설정을 격리하며 `integration` 표시 테스트만 실제
  연결 환경변수를 사용한다.

## 3차 완료 요점

- `DB_AUTO_CREATE` 코드 기본값은 `false`다. `true`인 로컬에서만 `create_all`·시드·SQLite 보존 이전을
  실행하며, `false`에서는 필요한 테이블 또는 카탈로그 시드가 없으면 migration 선적용 오류로 시작 실패한다.
- 공유 Supabase는 팀 검토 후 `001_learning_management.sql` → `002_enable_rls.sql` →
  `003_seed_stages_concepts.sql` 순으로 적용한다. 002는 정책 없이 모든 모듈 테이블의 RLS를 켜며,
  003은 `scripts/generate_stage_seed_sql.py`로 `data/stages.json`에서 재생성한다.
- `ANSWER_KNOWLEDGE_MODE`는 `dictionary_only`, `dictionary_plus`(기본), `free`다. 기본 모드는 핵심
  사전 정의를 지키면서 일반 경제 지식으로 배경·이유·생활 사례를 보충한다.

## 4차-B 팀 연동 요점

- `/learning/history`는 `limit`만 받고 각 메시지에 `session_id`, `attempt`, `concept_id`, `start_type`을
  반환한다. 개발 화면은 재학습 시도 경계에 구분선을 표시하지만 LLM·퀴즈 학습 맥락은 바꾸지 않는다.
- `learning_sessions`의 실제 DB 컬럼은 `stage_id`다. 기존 PostgreSQL은 004 migration, 로컬 SQLite는
  시작 시 데이터 보존 컬럼 변경을 사용한다. 001~003은 수정하지 않았다.
- `LLM_PROVIDER=fake`는 OpenAI 모델·키와 외부 호출 없이 고정 답변을 제공하며, 브라우저 origin은
  `CORS_ALLOW_ORIGINS`의 쉼표 구분 목록으로 허용한다.
- Qdrant payload 보강 스크립트는 기본 dry-run이며 `--apply`에서만 누락된 표준 메타데이터와
  `source=시사경제용어사전`을 저장한다.

## 완료 기준 보완 구현 요점
- `GET /learning/sessions/{id}/messages`와 `GET /learning/history?limit=50`은 `display_sources`를 포함한 메시지를 시간순으로 반환하고 사용자 격리를 적용한다. history에는 시도 복원용 `session_id`, `attempt`, `concept_id`, `start_type`도 포함한다.
- 다른 개념명만 있는 질문은 현재 개념과 최근 1~2턴을 포함해 LLM yes/no로 판정한다. 비교 질문은 관련, 독립 설명 질문은 비관련으로 처리한다.
- 사실·숫자·정의는 사전 근거를 따르되 사전 문장을 복사하지 않고 핵심 의미→중요성→생활 연결로 재구성한다. 같은 세션의 기존 내용은 짧게만 언급하고 원인·영향·유사 개념 차이 등 새 각도로 설명하며 숫자·유래·예시를 반복하지 않는다.
- 재학습에는 이전 시도의 최근 대화를 넣어 다른 설명·예시를 요구한다. Stage 5는 TESAT·매경TEST 중심의 심화 프롬프트를 사용한다.
- `LLM_TEMPERATURE` 기본값은 `0.7`이다. 답변 모델이 지원할 때만 보내며, 관련성 판정과 `reasoning.effort != none` 요청에는 생략한다.
- 학습 맥락의 `concept.status`는 완료 시점 스냅샷이며 실제 상태 갱신 대상은 `(concept.concept_id, concept.stage_id)`다.

## 작업 규칙
- 단계 시작 전 계획을 짧게 제시하고, 단계가 끝나면 테스트 결과와 실제 응답 예시를 보고한다
- Qdrant·LLM은 단위 테스트에서 mock. 실제 연결 테스트는 환경변수가 있을 때만 실행 (OpenAI 호출은 비용이 드니 최소한으로)
- API 키는 `.env` 에만 있다. 코드·로그·테스트 출력에 키를 남기지 않는다
- 모르는 부분은 임의로 정하지 말고 질문하거나 설정값으로 분리한다
- 명세를 바꿔야 하면 `GUIDE/CHATBOT_SPEC.md` 를 함께 수정하고 무엇을 바꿨는지 보고한다
