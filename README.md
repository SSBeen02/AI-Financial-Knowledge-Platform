# 나의 경세학당 — 사전테스트·퀴즈·학습노트 통합 전달 안내

담당: 박서현 · 전달 대상: 안유빈(학습 관리·RAG), 김선빈(프론트엔드·인증·게임·통합)  
작성 기준: 2026-10-18, 현재 작업 폴더의 코드 및 기존 검증 기록

이 문서는 박서현 담당 기능을 하나의 FastAPI 서버에 연결하기 위한 안내다. 「공유 API 및 DB 스키마 10/06」의 모듈 책임을 따르며, 이후 구현된 변경 사항을 아래에 구분했다. 기존 개별 HANDOFF 문서의 과거 설명과 충돌하는 학습노트 내용은 이 README와 현재 코드를 기준으로 확인한다. 외부 공유 설계 원본을 수정한 것은 아니다.

## 먼저 확인: 팀원별 읽을 부분과 연결할 작업

### 안유빈님 — 학습 관리·RAG 연결

**읽을 부분:** 2절 변경 사항 → 4절 ‘유빈님 학습 관리 ↔ 퀴즈’ → 5절 ‘퀴즈’, ‘학습노트·복습’ → 7절 검증 범위.

| 연결할 작업 | 전달 내용·확인 기준 | 관련 코드 |
| --- | --- | --- |
| 학습 완료 시 퀴즈 생성 | 인증된 user_id, session_id, concept_id, stage_id, learning_context, reference_chunk_ids 전달. 반환된 quiz_set_id와 status 사용 | `app/services/team_quiz.py` |
| 통합 시작 시 어댑터 등록 | 챗봇 초기화 후 async lifespan에서 `register_quiz_integration` 호출. store/status provider 연결. 동기 생성 호출은 작업 스레드에서 실행 | `app/services/team_quiz.py` |
| 채점 결과 반영 | `report_quiz_result`로 받은 passed를 개념 상태·진행률·스테이지 완료에 반영. 같은 submission_id는 한 번만 처리 | `app/services/learning_callbacks.py` |
| 생성 실패·다시 받기 | failed와 실패 알림을 중복 처리하지 않고 개념은 학습중 유지. 맥락을 복사한 새 session_id로 재요청하며 attempt 유지 | `app/services/team_quiz.py`, `app/services/learning_callbacks.py` |
| 학습노트 현재 상태 제공 | `read_concept_status(*, user_id, concept_id, stage_id)` 래퍼를 concept_status_reader로 등록 | `app/services/learning_callbacks.py` |
| Stage 5 연결 | 고정 문제도 같은 퀴즈 계약 사용. 스테이지별 개념 상태 분리, 70개 모두 통과 시 학습 관리에서 완료 판정 | `stage5_questions.json`, `app/services/stage5_bank.py` |

유빈님 연결 완료 기준:

- [ ] 학습 완료 → 퀴즈 생성 → 제출 결과 → 개념 통과·진행률 반영이 실제 chatbot 패키지에서 이어진다.
- [ ] 생성 실패 후 새 세션으로 다시 받고, 결과가 그 새 세션에 반영된다.
- [ ] 같은 제출 결과를 다시 받아도 통과 수·이벤트가 중복 증가하지 않는다.
- [ ] 학습노트에 현재 개념 상태가 표시되며 복습 제출은 학습 상태를 바꾸지 않는다.

### 김선빈님 — 화면·인증·게임·통합 서버 연결

**읽을 부분:** 2절 변경 사항 → 3절 실행·환경변수 → 4절 ‘공통 라우터·인증’ → 5절 전체 API → 6절 DB·파일 → 7절 검증 범위.

| 연결할 작업 | 전달 내용·확인 기준 | 관련 코드·설정 |
| --- | --- | --- |
| 공통 인증·서버 등록 | 네 라우터 등록, 검증된 사용자 ID provider 연결, DEV_MODE=false. CORS·request_id·오류 처리 통합 | `main.py`, `dependencies.py`, `app/api/deps.py`, 4절 예시 |
| 사전테스트 화면 | 시작 응답의 공개 문항으로 출제, 전체 답안을 Idempotency-Key 헤더와 제출 | `routers/diagnostics.py`, `index.html` |
| 리포트·이름 설정 | 제출 접수 후 이름 설정은 독립 처리. 리포트 상태 조회 후 domain_scores로 그래프, llm_report로 분석 표시. failed·재시도 안내 | `routers/reports.py`, 5절 사전테스트·리포트 |
| 퀴즈 화면 | `/api/v1/quiz-sets/{id}` 조회·제출. 보기 key 사용, 본문에 idempotency_key. 결과 후 학습 관리 API로 최신 진행 상태 조회 | `app/api/v1/endpoints/quizzes.py`, `quiz.html` |
| 학습노트 화면 | concepts API로 개념·문항 표시, Stage 1 기본 선택, 목록과 문항 탭에 같은 필터 적용 | `app/services/learning_notes.py`, `learning_notes.html` |
| 문항 복습 | 원본 submission_id·question_index로 퀴즈 복습 화면 이동, reviews API 저장. 최초 결과·보상 유지. ‘개념 다시 학습’ 버튼 연결 없음 | `quiz.html`, `app/services/learning_notes.py` |
| 게임 연결 | 유빈님 학습 관리가 확정한 이벤트로 신분·엽전·보상 처리. 복습 결과로 보상 지급하지 않음 | 학습 관리·게임 모듈의 이벤트 계약 |

선빈님 연결 완료 기준:

- [ ] 로그인 후 본인 기록만 보이고 다른 사용자의 조회·제출·복습 접근이 차단된다.
- [ ] 사전테스트 제출·이름 설정·리포트 로딩·실패·재시도 화면이 연결된다.
- [ ] 퀴즈 조회·제출과 학습노트 필터·복습·새로고침 복원이 실제 HTTP로 동작한다.
- [ ] 최초 퀴즈 결과와 복습 결과를 구분하고, 중복 요청으로 보상이 늘어나지 않는다.

### 박서현 — 제공 기능 및 통합 중 확인할 부분

사전테스트 출제·채점·리포트, 퀴즈 생성·채점·결과 콜백, Stage 5 고정 문제, 학습노트 조회·복습 저장 코드와 SQL을 제공한다. 연동 중 생성·채점·조회 응답이나 어댑터 계약에 문제가 있으면 해당 모듈에서 확인한다. 관련 구현 위치는 6절, 기존 검증 근거는 7절에 정리했다.

### 세 명이 함께 확인할 사항

- API prefix와 공통 인증 반환 형식, 패키지 이름 충돌을 통합 전에 확인한다.
- 대상 Supabase의 SQL 적용 상태를 확인하고 DB 변경은 관련 담당자 검토 후 반영한다.
- 실제 chatbot·로그인·HTTP·게임까지 연결한 통합 검증은 아직 남아 있다. 7절의 기존 검증 결과와 구분한다.
- 공유 설계 원본에는 2절의 변경 사항을 함께 반영한다.

아래는 각 작업에 필요한 상세 계약과 실행 방법이다.

## 1. 전달 범위와 담당

| 기능 | 박서현 구현 범위 | 연결 담당 |
| --- | --- | --- |
| 사전테스트·리포트 | 출제, 채점, 영역별 점수, 분석 생성·저장·조회·재시도 | 선빈: 인증, 화면·그래프, 캐릭터 이름 설정 |
| Stage 1~4 퀴즈 | 학습 맥락 기반 OX 2문제·상황형 1문제 생성, 저장·채점 | 유빈: 맥락 전달, 결과로 개념 상태·진행률 갱신 |
| Stage 5 | 70개 개념·고정 210문제, 개념당 3문제 제공·채점 | 유빈: Stage 5 개방·70개 개념 통과에 따른 완료 판정 |
| 학습노트 | 개념별 풀이 조회, 정답·오답 필터, 문항 복습 저장 | 선빈: 화면 연결 / 유빈: 현재 개념 상태 조회 함수 |

퀴즈는 3문제 중 2문제 이상 정답이면 통과다. 개념 통과·스테이지 완료·진행률은 학습 관리가, 신분·엽전·보상은 게임 모듈이 처리한다. 다른 담당자의 테이블을 직접 수정하지 않는다.

사전테스트 결과는 취약 영역 리포트에만 사용한다. 학습 순서·난이도·개념 통과·진행률에 반영하지 않는다. 리포트 생성과 캐릭터 이름 설정은 독립적으로 저장한다.

## 2. 10/06 공유 설계에서 달라진 부분

| 항목 | 현재 구현 및 전달 사항 |
| --- | --- |
| 사전테스트 시작 응답 | 정답·해설·개념명을 공개하지 않는다. 공유 초안의 ‘답안’은 시작 응답에서 제외해야 한다. |
| 퀴즈·학습노트 API 경로 | 실제 경로에 `/api/v1`이 있다. 사전테스트·리포트 경로에는 없다. |
| Stage 5 저장 | 별도 `exam_questions`, `exam_submissions` 테이블 없음. 원본은 `stage5_questions.json`, 제공 세트·제출은 `quiz_sets`, `quiz_submissions` 사용. |
| 학습노트 현재 화면 | `/api/v1/learning-notes/concepts` 사용. 제출된 문항만 표시한다. 기존 문항 단위 API는 미제출 기록도 포함하는 호환 API로 유지한다. |
| 개념 그룹 | `concept_id` 하나로 묶는다. 여러 스테이지 기록 조회 시에도 같은 개념은 한 그룹이다. 개념 상태 자체는 계속 `(concept_id, stage_id)` 단위다. |
| 복습 | 원본 문항 다시 풀기 구현. `quiz_reviews`에 복습 답안만 추가하고 최초 채점·통과·보상은 유지한다. |
| 개념 다시 학습 | 10/18 학습노트의 전용 버튼·API 제거. 일반 학습 관리의 재학습 기능과 구분한다. |
| 최신 진행 상태 | 퀴즈 제출 응답에 최신 진행률이 포함된다고 가정하지 않는다. 학습 관리 상태·진행률 API를 다시 조회한다. |

Stage 5는 고정 OX 2문제·상황형 1문제를 사용하며 외부 LLM을 호출하지 않는다. 출제 파일에 없는 개념은 생성 실패로 처리한다. 같은 세션 재요청은 failed를 포함해 기존 세트를 반환한다. 추가적인 Stage 5 반복 제출 정책은 팀 합의가 필요하다.

## 3. 실행 방법과 환경변수

Python 3.10 이상. 저장소 루트에서 실행한다.

```bash
python -m pip install -r requirements.txt
```

`.env.example`을 `.env`로 복사해 설정한 후 실행한다.

```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

| 주소 | 용도 |
| --- | --- |
| `http://127.0.0.1:8000/` | 사전테스트 화면 |
| `http://127.0.0.1:8000/quiz` | 퀴즈 화면 |
| `http://127.0.0.1:8000/learning-notes` | 학습노트 화면 |
| `http://127.0.0.1:8000/docs` | 실제 요청·응답 스키마 |

외부 AI 없이 화면을 확인하려면 `python -m uvicorn quiz_preview:app --host 127.0.0.1 --port 8012` 실행 후 `/learning-notes`에 접속한다. 미리보기는 예시 문제와 임시 SQLite를 사용하며 서버 종료 시 기록이 사라진다.

| 변수 | 설정 및 용도 |
| --- | --- |
| `DEV_MODE` | 단독 개발만 `true`. 통합·운영은 `false`, 공통 인증 연결 필수 |
| `DIAGNOSTIC_REPOSITORY` | 로컬 `memory`, 통합 `supabase`. 메모리는 재시작 시 소멸 |
| `SUPABASE_URL` | 사전테스트 저장용 Supabase 프로젝트 URL |
| `SUPABASE_SERVICE_ROLE_KEY` | 사전테스트 서버 전용 키 |
| `QUIZ_DATABASE_URL` | 퀴즈·학습노트 DB. 미설정 시 `sqlite+aiosqlite:///./data/quiz.db` |
| `OPENAI_API_KEY` | Stage 1~4 퀴즈 및 OpenAI 리포트 생성용 서버 키 |
| `OPENAI_MODEL` | 생성 모델. 현재 `.env.example`은 `gpt-4o-mini` |
| `LLM_REPORT_MODE` | 단독 `local`, 통합 `openai` 권장. `local`은 리포트에만 적용 |
| `CORS_ORIGINS` | 허용 프론트 주소, 쉼표 구분 |

Supabase 퀴즈 연결 URL은 `postgresql+asyncpg://USER:PASSWORD@HOST:PORT/postgres?ssl=require` 형식이며 비밀번호는 URL 인코딩한다. 호스트·포트·SSL은 배포 환경에 맞춘다. 사전테스트 저장 설정과 퀴즈 DB 연결 설정은 각각 필요하다. `.env`와 실제 키·연결 URL은 Git이나 프론트에 포함하지 않는다.

## 4. 통합 서버 등록

모듈별 서버를 따로 만들지 않고 통합 FastAPI 앱에 연결한다. `main.py`는 단독 개발 진입점이며, 현재 자동으로 챗봇 연동을 등록하지 않는다.

### 공통 라우터·인증

```python
from dependencies import get_current_user_id
from routers.diagnostics import router as diagnostics_router
from routers.reports import router as reports_router
from app.api.v1.endpoints.quizzes import router as quizzes_router
from app.services.learning_notes import router as learning_notes_router

app.include_router(diagnostics_router)
app.include_router(reports_router)
app.include_router(quizzes_router)
app.include_router(learning_notes_router)
app.dependency_overrides[get_current_user_id] = verified_user_provider
```

`verified_user_provider`는 선빈님 공통 인증 함수로 교체한다. 검증된 Supabase Auth 사용자 UUID 문자열을 반환해야 한다. 본문의 `user_id`나 서명 미검증 JWT로 사용자를 판단하지 않는다. 퀴즈·학습노트도 위 공통 사용자 의존성을 사용한다.

통합 저장소에 기존 `app`, `database`, `services`, `schemas`, `dependencies` 패키지가 있으면 네임스페이스와 import 충돌을 먼저 조정한다. CORS, 루트 화면, request_id 미들웨어, 요청 검증 오류 핸들러는 통합 서버에서 한 번 구성한다. `app/errors.py`, `routers/errors.py`를 참고해 기능별 오류를 공통 `code/message/request_id` 응답에 연결한다.

### 유빈님 학습 관리 ↔ 퀴즈

유빈님 패키지가 `import chatbot`으로 사용 가능해야 한다. 통합 앱의 **async lifespan에서 챗봇 초기화 후** 다음을 실행한다.

```python
from app.db import ensure_quiz_schema
from app.services.team_quiz import register_quiz_integration

await ensure_quiz_schema()
register_quiz_integration(
    app,
    store_provider=team_chat_store_provider,
    status_provider=team_status_service_provider,
    concept_status_reader=read_concept_status,
)
```

예시의 provider와 reader는 통합 코드에서 구현한다. provider는 인자 없는 동기 함수여야 하며, 추가 Depends가 필요한 의존성은 감싸서 전달한다. `read_concept_status(*, user_id, concept_id, stage_id)`는 학습 관리의 공개 함수를 호출하여 `not_started / in_progress / passed`를 반환한다. 동기·비동기 reader를 지원하며 미연결 시 학습노트 상태는 `null`이다. 종료 시 `dispose_quiz_database()`로 DB 연결을 정리한다.

`TeamQuizService`는 유빈님 동기 계약을 비동기 퀴즈 서비스에 연결한다. 동기 학습 완료 처리는 작업 스레드에서 실행한다. async 엔드포인트에서 호출할 때는 `await asyncio.to_thread(...)`로 감싼다. 이벤트 루프 스레드에서 직접 호출하면 오류를 반환한다.

| 내부 함수 | 전달 및 처리 |
| --- | --- |
| `create_quiz_set` | `user_id, session_id, concept_id, stage_id, learning_context, reference_chunk_ids` → `quiz_set_id, status`. 사용자·세션당 세트 하나, failed 포함 재사용. 참고 청크 ID는 전달받되 출제에 사용하지 않음 |
| `report_quiz_result` | 저장 후 `user_id, submission_id, session_id, concept_id, stage_id, correct_count, passed` 전달. 학습 관리가 제출 ID 기준 중복 반영 방지 |
| `report_quiz_generation_failed` | 사용자·세션 기준 생성 실패 알림. 개념은 학습중 유지, 학습 관리가 같은 실패 중복 처리 방지 |
| `get_concept_status` | 학습 관리 공개 함수로 현재 상태 조회. 다른 담당 테이블 직접 접근 없음 |

생성 실패 후 ‘퀴즈 다시 받기’는 학습 관리가 학습 맥락을 복사한 **새 session_id**로 생성한다. 이 재요청에서 attempt는 올리지 않고, 이후 결과도 새 session_id로 전달한다.

퀴즈 결과 콜백 실패 시 채점 저장은 유지한다. 자동 재전달 작업은 없으며 같은 제출 키로 요청하면 저장된 submission_id로 결과를 다시 전달한다. 생성 실패 알림에도 자동 재전달은 없으므로 학습 관리는 반환된 failed 상태를 반영해야 한다.

## 5. 프론트 API

### 사전테스트·리포트

| API | 요청·응답 규칙 |
| --- | --- |
| `POST /diagnostics` | 본문 없음. 201, 진단 ID·공개 문항·보기 반환 |
| `POST /diagnostics/{id}/submit` | `Idempotency-Key` 헤더 필수. 모든 문항을 한 번씩 제출. 최초 202, 채점 결과와 processing 상태 반환 |
| `GET /reports/{id}` | 200, pending/processing/completed/failed 및 저장된 결과. 진단 ID = 리포트 ID |
| `POST /reports/{id}/retry` | failed 리포트의 저장된 채점 결과로 재생성 요청 시 202. 처리 중·완료는 현재 결과 반환 |

사전테스트 제출 본문 예시(실제 응답의 전체 문항을 포함해야 함):

```json
{"answers":[{"question_id":"finance_investment_001","selected_answer":2}]}
```

보기 번호는 1부터 시작한다. 헤더 키는 1~128자이며 공백만인 값은 금지한다. 같은 진단·키·답안은 처리 중 202, 완료·실패 후 200으로 기존 결과를 반환한다. 답안 순서는 무관하며 다른 키 또는 답안은 409다. 같은 제출로 생성 작업을 재시작하지 않는다.

프론트는 제출 접수 후 캐릭터 이름 설정을 독립 호출하고 리포트 상태를 조회한다. 그래프는 `domain_scores`, 분석 문장은 `llm_report`를 사용한다. failed여도 채점 결과는 표시하고 `error.code/message`로 실패를 안내한다.

리포트 생성 목표는 제출 후 30초, LLM 예산은 최대 28초다. 완료 보장 시간은 아니다. 프로세스 내 BackgroundTasks이므로 서버 종료로 작업이 유실될 수 있으며, 제출 후 30초가 지난 processing 조회는 failed로 정리한다. 운영 자동 복구가 필요하면 영속 작업 큐가 후속 과제다.

### 퀴즈

| API | 요청·응답 규칙 |
| --- | --- |
| `GET /api/v1/quiz-sets/{id}` | 생성 상태·문제·보기 조회. 정답·해설 제외 |
| `POST /api/v1/quiz-sets/{id}/submit` | `submitted_answers`, `idempotency_key`. 문항별 결과·정답·해설·정답 수·`is_passed` 반환 |

퀴즈는 헤더 대신 **본문**에 중복 방지 키를 넣는다. 각 `answer`에는 조회 응답에 있는 보기의 `key` 값을 문자열로 넣는다. 아래는 형식 예시이며 실제 보기를 기준으로 제출한다.

```json
{
  "submitted_answers": [
    {"question_index": 1, "answer": "O"},
    {"question_index": 2, "answer": "X"},
    {"question_index": 3, "answer": "1"}
  ],
  "idempotency_key": "unique-submit-key"
}
```

`question_index`는 1~3이며 세 문항을 제출한다. `learning_module_result`는 내부 전달용 결과다. 화면의 진행률·완료 상태는 학습 관리 API를 조회해 표시한다.

### 학습노트·복습

| API | 용도 |
| --- | --- |
| `GET /api/v1/learning-notes/concepts` | 현재 화면용 개념 그룹 조회. `stage_id`, `concept_id`, `filter=all\|correct\|wrong`, `page` |
| `GET /api/v1/learning-notes` | 기존 문항 단위 호환 조회. 같은 필터, 페이지당 문항 20개, 미제출도 포함 |
| `POST /api/v1/learning-notes/submissions/{submission_id}/questions/{question_index}/reviews` | 복습 답안 저장. 본문 `answer`, `idempotency_key` |

현재 화면은 Stage 1~5를 선택하며 기본값은 Stage 1이다. 전체 스테이지 선택 UI는 제공하지 않는다. 개념 API는 제출된 문항에 필터를 먼저 적용하고 개념별로 묶은 뒤 페이지당 **개념 20개**를 반환한다. `total`도 문항 수가 아닌 개념 그룹 수다.

그룹은 `concept_id, stage_id, stage_ids, term, latest_at, concept_status, questions`를 제공한다. 그룹의 단일 stage_id·상태는 최신 기록의 호환 필드다. 실제 문항 동작에는 선택한 문항의 stage_id·concept_status를 사용한다. 문항은 `submission_id + question_index`로 식별하고 `reviews`에 복습 이력을 제공한다. 상태 표시는 미학습·학습중·통과로 한다.

‘다시 풀기’는 `/quiz?mode=review&concept_id=...&stage_id=...&submission_id=...&question_index=...`로 이동해 원본 한 문항만 푼다. 복습 API는 원본 제출 소유권을 검증하고 quiz_reviews에만 기록한다. 같은 키·같은 요청은 기존 기록, 같은 키·다른 요청은 409다. 최초 답안·정오답·통과·학습 상태·보상은 변경하지 않는다. 정답·오답 필터도 최초 결과 기준이다.

## 6. DB와 전달 파일

| 파일·디렉터리 | 용도 |
| --- | --- |
| `main.py`, `dependencies.py`, `.env.example`, `requirements.txt` | 단독 서버·공통 인증 연결점·환경 설정 |
| `routers/`, `services/`, `schemas/`, `database/` | 사전테스트·리포트 구현 |
| `data/pretest_questions_v2.json` | 사전테스트 문항 원본 |
| `app/` | 퀴즈·학습노트·복습·학습 관리 어댑터 |
| `stage5_questions.json` | Stage 5 고정 문제 원본 |
| `index.html`, `quiz.html`, `learning_notes.html` | 단독 확인용 화면 |
| `sql/`, `tests/`, `verification/` | DB 스크립트·회귀 테스트·기존 검증 근거 |

| SQL | 적용 대상 |
| --- | --- |
| `sql/diagnostic_attempts.sql` | 사전테스트 결과·문항 스냅샷·제출 키·오류 |
| `sql/quiz_001_tables.sql` | quiz_sets·quiz_submissions 및 제약·인덱스·RLS. `quiz.sql`과 같은 테이블이므로 중복 적용 전 확인 |
| `sql/quiz_002_learning_note_indexes.sql` | 학습노트 조회 인덱스 |
| `sql/quiz_003_reviews.sql` | 복습 답안 전용 quiz_reviews |

학습노트 내용 전체를 복제하는 전용 테이블은 만들지 않는다. quiz_reviews는 복습 답안만 저장한다. 10/18 기존 검증 기록과 업로드 README에 따르면 검증에 사용한 공유 Supabase에는 quiz_reviews 및 추가 인덱스가 적용되어 있다. 다른 환경의 적용 여부는 별도로 확인해야 한다. 사전테스트 SQL의 공유 DB 적용 완료 여부는 이번 문서 작성에서 확인하지 않았다.

사전테스트 `user_id`는 현재 text에 인증 UUID 문자열을 저장한다. uuid 타입·auth.users 외래키 변경은 팀 DB 합의 후 진행한다. 정답이 포함된 `questions_snapshot`과 퀴즈 내부 문제 데이터는 직접 클라이언트 조회로 노출하지 않는다. 통합 DB 변경은 담당자 검토 후 스크립트 기준으로 적용한다.

## 7. 검증된 범위와 남은 통합 확인

이 README 작성 시에는 코드·문서 대조만 수행했다. 아래 결과는 기존 검증 기록이며 이번에 새로 테스트하거나 공유 DB를 변경한 결과가 아니다.

| 기존 기록 | 확인 내용 및 제한 |
| --- | --- |
| 10/06 리포트 실제 OpenAI 30회 | 채점 불일치·실패·30초 초과 0건. 로컬 메모리 기반, Supabase·HTTP·동시 부하 제외 |
| 10/08 퀴즈 HANDOFF | 어댑터·퀴즈 테스트 21개, 당시 전체 회귀 59개 통과. 실제 chatbot 통합 제외, 현재 코드 전체의 최신 통과 결과를 뜻하지 않음 |
| 10/11 퀴즈 HANDOFF | 공유 Supabase 저장·조회·채점·중복 제출·Stage 5 검증 통과 기록 |
| 10/18 학습노트 Supabase 검증 | 실제 DB 함수 조회·복습 저장·멱등·소유권 차단·최초 결과 보존 통과. 검증용 복습 기록 롤백 확인 |

학습노트 검증에는 실제 로그인 토큰, 프론트 HTTP 연결, anon/authenticated 역할별 RLS 검증이 포함되지 않았다. 현재 폴더에는 유빈님 chatbot 패키지가 없어 실제 학습 상태·진행률·게임 이벤트까지 이어지는 통합 검증은 남아 있다.

팀 통합 시 확인할 항목:

- [ ] 선빈: 공통 인증 연결, DEV_MODE=false에서 사용자별 접근 차단, API prefix 확인
- [ ] 선빈: 사전테스트 제출 → 이름 설정과 리포트 조회 → 실패·재생성 화면 확인
- [ ] 유빈: 학습 완료 → 퀴즈 생성 → 결과 수신 → 개념 상태·진행률 반영 확인
- [ ] 유빈: 생성 실패 → 새 재요청 세션 → 새 퀴즈 ID·결과 세션 일치 확인
- [ ] 유빈·선빈: 같은 submission_id 재전달 시 진행률·게임 이벤트·보상 중복 방지
- [ ] 유빈·선빈: Stage 5 개방, stage별 개념 상태 분리, 70개 통과 완료 연결
- [ ] 선빈: 학습노트 필터·문항 전환·복습 저장·새로고침 복원 및 최초 결과 유지 확인
- [ ] 전원: 대상 DB SQL 적용 상태, 로그인·HTTP·역할별 RLS, 저장 실패·중복 요청 확인

로컬 회귀 명령: `python -m unittest discover -s tests -q`.
