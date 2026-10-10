# 유빈님·선빈님 전달: 퀴즈 연결 안내

## 제공 코드

- 동기 연동 계약: `app/services/team_quiz.py`, `TeamQuizService`
- 실제 비동기 생성·채점: `app/services/quiz_service.py`, `QuizService`
- 학습 관리 결과·실패 호출: `app/services/learning_callbacks.py`
- Stage 5 고정 문제: `stage5_questions.json`, `app/services/stage5_bank.py`

`TeamQuizService(loop)`는 실행 중인 통합 서버 이벤트 루프를 받습니다. DB 세션은 내부에서 준비하며 LLM 키는 환경변수에서 읽습니다. 유빈님 패키지의 `QuizSetResult`, `QuizServiceError`를 직접 사용합니다. 상속 대신 동일한 메서드 계약을 제공하는 어댑터입니다.

## 통합 등록

퀴즈 코드를 통합 서버의 Python import 경로에 두고, 유빈님 패키지를 `import chatbot`으로 사용할 수 있게 배치합니다. 기존 `app` 패키지가 있으면 퀴즈 쪽 네임스페이스와 import 경로를 통합 담당자가 조정해야 합니다.

통합 앱의 **async lifespan**, 챗봇 초기화와 퀴즈 DB 준비 이후에 실행합니다.

```python
from app.db import ensure_quiz_schema
from app.services.team_quiz import register_quiz_integration

await ensure_quiz_schema()
register_quiz_integration(app)
```

이 함수가 `app.dependency_overrides[chatbot.deps.get_quiz_service]`를 실제 퀴즈 구현으로 바꾸고, 결과 콜백의 저장소·상태 서비스 provider를 설정합니다. 직접 provider를 전달할 수도 있습니다.

```python
register_quiz_integration(
    app,
    store_provider=team_chat_store_provider,
    status_provider=team_status_service_provider,
)
```

Provider는 인자 없이 호출 가능한 동기 함수여야 합니다. FastAPI 의존성이 다른 Depends 인자를 요구하면 이를 감싸는 provider를 전달하세요.

유빈님의 동기 학습 완료 처리는 FastAPI 작업 스레드에서 실행해야 합니다. async 엔드포인트에서는 `await asyncio.to_thread(...)`로 호출하세요. 이벤트 루프 스레드에서 동기 어댑터를 호출하면 교착 방지를 위해 `QuizServiceError`를 반환합니다.

## 호출·중복·오류 규칙

- `(user_id, session_id)`당 세트 하나. failed 포함 기존 세트를 반환합니다.
- 생성·저장 실패로 세트 자체를 만들 수 없으면 `QuizServiceError`로 전달합니다.
- LLM 생성 실패를 DB에 저장하면 `status=failed` 반환과 `report_quiz_generation_failed(store, user_id, session_id)` 호출이 함께 발생합니다. 학습 관리의 멱등 처리에 의존합니다.
- 채점 결과 저장 후 `report_quiz_result`에 provider가 반환한 store/status_service와 user_id, session_id, submission_id, concept_id, stage_id, correct_count, passed를 전달합니다.
- 같은 제출 키 재요청은 저장된 submission_id로 결과를 재전달합니다. 새 결과를 만들지 않습니다.
- 콜백 오류가 발생해도 퀴즈 결과 저장은 유지하고 오류 로그를 남깁니다. 자동 재전달 작업은 없으며, 같은 제출 키 재요청으로 결과 보고를 다시 수행합니다. 생성 실패 알림만의 자동 재전달은 없고 failed 반환값으로 학습 관리가 반영해야 합니다.
- 미등록 단독 개발에서는 학습 관리 호출을 생략하고 경고를 남깁니다. 운영 통합에서는 반드시 등록하세요.
- 재요청은 유빈님이 만든 새 session_id로 생성하고 결과도 그 새 ID로 전달합니다.
- Stage 5는 고정 70개 개념·210문제 파일을 사용하며 외부 LLM을 호출하지 않습니다. 파일에 없는 개념이면 생성 실패로 저장합니다.

## DB SQL

`sql/quiz_001_tables.sql`: `quiz_sets`, `quiz_submissions`, 인덱스·유일 제약·RLS를 생성합니다. 기존 `sql/quiz.sql`과 같은 테이블입니다. 공유 Supabase 적용은 아직 하지 않았습니다.

현재 Stage 5 풀이도 위 테이블에 저장합니다. `exam_questions`, `exam_submissions`는 구현되어 있지 않습니다. 이 별도 테이블이 팀 통합의 필수 조건이면 정책·스키마를 합의한 후 별도 migration이 필요합니다. 이 인수인계에 해당 테이블이 있다고 전제하면 안 됩니다.

## 환경변수·패키지

- `QUIZ_DATABASE_URL`: SQLite 기본 `sqlite+aiosqlite:///./data/quiz.db`; Supabase `postgresql+asyncpg://USER:PASSWORD@HOST:PORT/postgres` (비밀번호 URL 인코딩, 실제 SSL/연결 방식은 배포 환경에 맞춰 설정).
- `OPENAI_API_KEY`: Stage 1~4 퀴즈 생성 서버 키. 비밀값은 개인 채널 전달.
- `OPENAI_MODEL`: 퀴즈 생성 모델. 리포트와 현재 같은 설정을 사용합니다.
- `DEV_MODE=false`: 운영에서는 통합 서버의 공통 인증을 연결합니다.
- `CORS_ORIGINS`: 프론트 주소 목록. 통합 서버에서 CORS는 한 번 등록합니다.
- `requirements.txt`: FastAPI, SQLAlchemy asyncio, aiosqlite, OpenAI 등. PostgreSQL용 `asyncpg>=0.30.0` 추가.

## 프론트 API (실제 현재 경로)

- `GET /api/v1/quiz-sets/{id}`
- `POST /api/v1/quiz-sets/{id}/submit`: `submitted_answers`, `idempotency_key`
- `GET /api/v1/learning-notes?stage_id=...&concept_id=...&filter=all|correct|wrong&page=1`

공유 문서의 `/quiz-sets`와 현재 `/api/v1/quiz-sets`는 prefix가 다릅니다. 프론트에 위 실제 경로를 전달하거나 통합 서버에서 prefix를 합의하세요. 인증은 통합 서버의 검증된 사용자 provider로 교체해야 합니다.

## 검증 범위

`tests/test_team_quiz_adapter.py`: 실제 SQLite·생성·채점 서비스와 공개 계약 대역을 사용합니다. 외부 LLM, 챗봇, Supabase 호출은 없습니다.

2026-10-08 연결·기존 퀴즈 테스트 21개 통과 (`python -m unittest tests.test_team_quiz_adapter tests.test_quizzes -q`). 검증에는 생성 1회·같은 세션 재사용·failed 재사용·저장소 예외·이벤트 루프 교착 방지·통과/실패 결과·동일 submission_id 재전달·Stage 5 70개/210문항 형식이 포함됩니다.

유빈님 패키지가 현재 작업 폴더에 없으므로 실제 학습 상태·진행률·게임 이벤트가 갱신됐다는 통합 검증은 아직 할 수 없습니다. 통합 서버에서 학습 완료→퀴즈 생성→통과/실패 상태 반영, 생성 실패→다시 받기, 새 retry 세션 결과, submission_id 중복 이벤트 방지를 함께 확인해야 합니다.

전체 회귀 검증: 2026-10-08 `python -m unittest discover -s tests -q` 59개 통과. 실패 로그는 오류 처리 테스트에서 의도한 예외입니다.
