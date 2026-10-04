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
| 1 | config, schemas, integrations(X-User-Id 인증, ConceptStatusService, SQLite 개발 구현, 퀴즈 통과 개발 훅) | 완료 |
| 2 | concepts + `GET /chat/concepts` | 완료 |
| 3 | store(SQLAlchemy) + `GET /chat/state`, `GET /chat/sessions/{id}` | 완료 |
| 4 | retrieval + 개념 캐시(시작 시 211개 1회 로드), SEARCH_PROFILES 자리 배분, band 판정 | 완료 |
| 5 | llm, prompts, relevance, 개념 감지 + `POST /chat/messages` | 완료 |
| 6 | 학습 완료, 학습 맥락, 퀴즈 결과 (`get_learning_context()`, `report_quiz_result()`) | 완료 |
| 7 | `POST /chat/messages/stream` (SSE) | 완료 |
| 8 | main_dev.py, README_chatbot.md | 완료 |

- **1~8단계 전체 구현 완료**
- 테스트: 단위 97개 + Qdrant 실제 연결 1개 통과 (`python -m pytest -q`)
- 실제 메시지 확인: "분업/특화에 대해 알려줘" → 세션 시작, 1위 sisa_1281, band high, OpenAI 답변·두 행 저장 확인

## 이미 확정된 동작 (바꾸지 말 것)
- 모드 우선순위: `quiz_pending` → `relearn` → `normal` (`/chat/state`, `/chat/concepts` 공통 함수)
  - `relearn`: 미통과 개념의 **최신 quiz_status가 failed** 일 때만
  - 최신 quiz_status가 `passed` 인데 개념 상태가 아직 미통과 → `quiz_pending` (상태 반영 대기)
  - 퀴즈 기록 없이 학습 중인 세션 → `normal`
  - `quiz_pending` 중 active 세션 존재는 불변 조건 위반 → 409
  - quiz_pending 안내: `현재 {term} 개념의 퀴즈 결과를 기다리는 중입니다.`
- 검색: Dense 단독(KURE-v1), 하이브리드·리랭커 사용 안 함
- band: 최고 점수 ≥ `BAND_HIGH`(0.50) high / ≥ `BAND_LOW`(0.45) mid / 미만 low — concept_source 소스의 Dense 점수로만 판정
- 개념 캐시는 서버 시작 시 1회만 로드, 요청마다 Qdrant에서 개념을 조회하지 않음
- 메시지는 user/assistant 두 행, 응답 `message_id` 는 assistant 행
- 개념 상태: 챗봇은 `미학습 → 미통과` 만 변경. `통과` 처리는 퀴즈 모듈 몫 (개발 환경에서만 `DEV_SIMULATE_QUIZ_STATUS` 훅으로 시뮬레이션)

## 5단계 구현 요점 (POST /chat/messages, 완료)
메시지 분기 순서:
1. active 세션이 있으면 그 세션에만 추가 (다른 개념 상태는 절대 변경하지 않음, 명세 3.5)
2. 최신 학습 맥락이 `quiz_pending` 이면 세션 없이 답변만, `free` 로 저장 (`selected_doc_id` 가 있어도 세션 시작 안 함)
3. 미통과 개념의 최신 quiz_status가 `failed` 이고 active 세션이 없으면 그 개념으로 `attempt+1` 재학습 세션. 다른 키워드 선택이면 409
4. `selected_doc_id` 가 현재 스테이지의 미학습이면 세션 시작, 아니면 409
5. 자유 질문이 현재 스테이지 미학습 개념으로 감지되면 세션 시작 (명세 5.1의 감지 규칙, 공백 무시)
6. 그 외는 답변만, `free` 로 저장
- 세션을 처음 열 때(keyword/detected)만 `mark_failed()` 로 `미학습 → 미통과`. 재학습 세션은 상태 변경 없음
- 관련성(is_related) 판정, mentioned_concepts, 프롬프트 구성은 명세 3.5, 5.1, 5.2, 10장을 따른다
- `keyword`/`detected` 첫 메시지만 `is_related=true`로 고정하고, `relearn` 첫 메시지는 일반 규칙으로 판정한다
- 명시적 `stage=stage5` + `selected_doc_id` 조합은 현재 스테이지와 무관하게 Stage 5 미학습 개념을 시작할 수 있다
- LLM: OpenAI 어댑터. `LLM_MODEL`, `LLM_RELEVANCE_MODEL`(미지정·빈 값이면 `LLM_MODEL`)
  - **추론 강도(reasoning effort)를 설정값 `LLM_REASONING_EFFORT` 로 분리**. 코드 기본값은 빈 값(파라미터 생략), `.env.example`은 `low`
  - 답변 최대 토큰도 설정값으로 분리
- 화면 표시는 `display_sources`를 사용한다. 현재 세션 개념은 검색됐으면 항상 표시하고, 다른 문서는 `DISPLAY_SOURCE_MIN_SCORE`(기본 0.60) 이상만 표시한다. `sources`는 LLM 전체 근거 및 저장용으로 그대로 유지한다.

## 6단계 구현 요점 (학습 완료·학습 맥락·퀴즈 결과, 완료)
- `POST /chat/sessions/{id}/complete`: active 세션을 완료하고 `is_related=true`인 user/assistant 쌍만 학습 맥락으로 저장한다. 관련 대화가 없으면 400이다.
- 학습 맥락의 `definition`은 캐시 문서의 `설명:` 이하이며, 전체 사용자 질문에서 현재 개념을 제외한 명시적 용어/별칭을 `mentioned_concepts`로 중복 없이 기록한다.
- `GET /chat/sessions/{id}/learning-context`, `GET /chat/learning-contexts?status=completed`로 본인 맥락을 조회한다. 타 사용자 세션은 404다.
- `POST /chat/sessions/{id}/quiz-result`는 저장된 `quiz_status`를 갱신하고 `ConceptStatusService.note_quiz_result()`에만 통보한다. 개발 훅이 켜진 경우에만 passed를 실제 `통과`로 시뮬레이션한다.
- 실패 결과 후 첫 메시지는 같은 개념의 `attempt+1` 재학습 세션을 열며, 통과 후에는 다음 미학습 개념 5개가 노출되는 흐름을 시나리오 테스트로 검증한다.
- `quiz-result`는 완료 및 `pending` 상태인 학습 맥락에 한 번만 기록한다. active 세션과 결과 중복 제출은 409다.
- 완료 세션은 메시지 요청으로 직접 지정할 수 없다. 완료 후 `quiz_pending` 입력은 기존 세션에 추가하지 않고 free 메시지로 저장하며, failed 이후 입력은 새 attempt 재학습 세션을 연다.

## 7단계 구현 요점 (POST /chat/messages/stream, 완료)
- 비스트리밍과 SSE가 `prepare_message()`와 최종 저장 함수를 공유해 분기·검색·관련성·검증 결과가 같다.
- OpenAI Responses 스트림의 `response.output_text.delta`만 `event: token`으로 변환하고, 정상 종료 뒤 범위/출처 suffix까지 토큰으로 전송한다.
- 모든 토큰 생성이 성공하고 클라이언트 연결이 유지된 경우에만 세션 생성, `mark_failed()`, user/assistant 두 행 저장을 수행한 뒤 `event: done`을 보낸다.
- 중간 LLM 오류는 `event: error`로 종료하며, 연결 끊김은 조용히 중단한다. 둘 다 저장 및 상태 변경이 없다.
- `done`은 답변 본문을 제외한 메시지 메타데이터이며 `sources`, `display_sources`, `message_id`를 포함한다.

## 8단계 구현 요점 (로컬 실행·인수인계 문서, 완료)
- `main_dev.py`는 FastAPI lifespan에서 설정, 카탈로그, DB, Qdrant, Dense 인코더, 211개 개념 캐시, 검색기, LLM 어댑터를 프로세스당 한 번 준비한다.
- `README_chatbot.md`에 로컬 실행, 전체 환경변수, 백엔드·퀴즈·프론트 통합, POST SSE 파싱, 검색 소스 추가 절차를 정리했다.
- 명세 9장 완료 기준은 README에 별도 평가했다. 단계별 예정 구현은 끝났지만 비교 질문 관련성 및 화면 복원 조회 API는 후속 보완 대상으로 남아 있다.
- Supabase PostgreSQL 배포를 위해 psycopg 3 연결, Session pooler·RLS 절차를 문서화했다. 개발용 상태 테이블은 `DEV_USE_LOCAL_STATUS=true`일 때만 생성되며 배포 기본값은 `false`다.

## 작업 규칙
- 단계 시작 전 계획을 짧게 제시하고, 단계가 끝나면 테스트 결과와 실제 응답 예시를 보고한다
- Qdrant·LLM은 단위 테스트에서 mock. 실제 연결 테스트는 환경변수가 있을 때만 실행 (OpenAI 호출은 비용이 드니 최소한으로)
- API 키는 `.env` 에만 있다. 코드·로그·테스트 출력에 키를 남기지 않는다
- 모르는 부분은 임의로 정하지 말고 질문하거나 설정값으로 분리한다
- 명세를 바꿔야 하면 `GUIDE/CHATBOT_SPEC.md` 를 함께 수정하고 무엇을 바꿨는지 보고한다
