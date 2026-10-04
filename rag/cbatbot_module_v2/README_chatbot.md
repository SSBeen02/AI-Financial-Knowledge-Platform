# RAG 챗봇 모듈

「나의 경세학당」의 경제 개념 학습용 FastAPI 모듈이다. 개념 추천, RAG 답변, 학습 세션,
학습 완료 맥락, 퀴즈 결과, SSE 스트리밍을 독립된 `APIRouter`로 제공한다.

## 1. 로컬 실행

### 1.1 가상환경과 패키지 설치

저장소 루트에서 PowerShell로 실행한다.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

처음 실행할 때 `nlpai-lab/KURE-v1` 모델을 내려받고 메모리에 올리므로 시작에 시간이 걸릴 수 있다.

### 1.2 환경변수 설정

```powershell
Copy-Item .env.example .env
```

`.env`에서 최소한 `QDRANT_URL`, `QDRANT_API_KEY`, `LLM_MODEL`, `LLM_API_KEY`를 채운다.
비밀값이 들어 있는 `.env`는 Git에 커밋하지 않는다.
기존 `.env`를 계속 쓰는 경우 로컬 단독 실행을 위해 `DEV_USE_LOCAL_STATUS=true`도 추가한다.

### 1.3 개발 서버 실행

```powershell
python main_dev.py
```

- API 문서: <http://127.0.0.1:8000/docs>
- 상태 확인: <http://127.0.0.1:8000/health>
- 기본 API prefix: `/learning`

`/docs`에서 요청을 시험할 때는 다음 순서로 진행한다.

1. 원하는 `/learning/...` API를 펼치고 **Try it out**을 누른다.
2. `X-User-Id` 헤더 입력란에 `local-user-1`처럼 테스트 사용자 ID를 넣는다.
3. 메시지 API라면 요청 본문을 입력한 뒤 **Execute**를 누른다.

예를 들어 `POST /learning/messages`의 본문은 다음과 같다.

```json
{
  "message": "분업/특화에 대해 알려줘",
  "concept_id": "sisa_1281"
}
```

Stage 5도 현재 스테이지가 열린 뒤 같은 요청 형식을 사용한다. `stage` 필드는 보내지 않는다.

### 1.4 개발용 채팅 화면과 상태 도구

`.env`에서 `DEV_USE_LOCAL_STATUS=true`로 설정하고 서버를 다시 시작한 뒤
<http://127.0.0.1:8000/dev/chat>을 연다. 이 페이지는 외부 JavaScript/CSS 라이브러리 없이
`main_dev.py`가 직접 제공하며 다음 수동 흐름을 한 화면에서 확인할 수 있다.

- `X-User-Id`를 바꿔 사용자별 기록을 불러오고 `/learning/current`의 mode·notice를 확인한다.
- 상단 `learning_guide`를 확인하고, 현재 스테이지의 키워드 5개를 선택하거나 다음 5개를 본다.
- 자유 질문에서 현재 스테이지 개념이 감지되면 답변 아래의 `{term} 학습 시작하기` 제안 버튼으로
  `concept_id`가 포함된 새 요청을 보내 명시적으로 학습을 시작한다.
- SSE 답변과
  `display_sources`, `is_related`, `band`를 확인한다.
- 답변 아래 별도 `notice` 상자와 상단 진행률 바·`남은 개념 N개`를 확인한다.
- 학습 완료 버튼은 세션이 없어도 활성화되며, 이때 API를 호출하지 않고 `/learning/current`의
  `complete_hint`를 표시한다.
- 학습 완료 후 학습 맥락을 보고, pending 퀴즈에 통과/실패 결과를 보낸다.
- 새로고침하면 `/learning/history?limit=50`으로 최근 대화를 복원한다.
- 스테이지 드롭다운은 선택한 스테이지보다 앞선 단계의 개념을 모두 통과 처리한다. 현재 스테이지는
  별도로 저장하지 않고 미완료 상태가 남은 가장 낮은 단계로 다시 계산한다.
- **현재 스테이지 전체 통과** 버튼으로 현재 단계의 모든 개념을 통과 처리해 다음 단계 전환을 확인한다.
- 초기화 버튼은 현재 사용자의 로컬 개념 상태·세션·메시지·학습 맥락을 지운다. 모든 개념이 다시
  `not_started`가 되므로 계산된 현재 스테이지는 `stage1`이다.

전체 학습 흐름에서 퀴즈 통과까지 개념 상태에 반영하려면 로컬에서만
`DEV_SIMULATE_QUIZ_STATUS=true`도 설정한다.

같은 기능은 Swagger 또는 HTTP 요청으로도 사용할 수 있다.

```text
POST /learning/dev/stage       {"stage":"stage5"}
POST /learning/dev/pass-all
POST /learning/dev/reset
GET  /learning/dev/status?stage=stage1
```

네 요청 모두 `X-User-Id`가 필요하다. `/stage`는 지정 단계보다 앞선 스테이지를 모두 통과 처리하고,
`/pass-all`은 계산된 현재 스테이지를 모두 통과 처리한다. 두 응답의 `stage`는 처리 후 다시 계산한
현재 스테이지다. status 응답은 요청한 스테이지의 전체 개념을 order 순으로
반환하며 각 항목에 `concept_id`, 용어, order, 현재 상태를 담는다. 이 개발 API와 `/dev/chat`은
`DEV_USE_LOCAL_STATUS=false`인 앱에는 **라우트 자체가 등록되지 않으므로** 배포에서 404다.

### 1.5 테스트

```powershell
python -m pytest -q
```

Qdrant 실제 연결 테스트는 `.env`에 연결 정보가 있을 때 실행하며, 단위 테스트의 Qdrant와 LLM은 mock이다.

## 2. 환경변수

표의 기본값은 코드 기본값이다. `.env.example`은 로컬 흐름 확인을 위해 일부 값을 다르게 제안할 수 있다.

| 환경변수 | 필수 여부 | 기본값 | 설명 |
|---|---:|---|---|
| `QDRANT_URL` | 필수 | 빈 값 | Qdrant 서버 URL |
| `QDRANT_API_KEY` | 필수 | 빈 값 | Qdrant Cloud API 키 |
| `QDRANT_COLLECTION` | 선택 | `sisa_terms` | 기본 개념 컬렉션. 기본 검색 프로필의 컬렉션명도 함께 바뀐다. |
| `DENSE_MODEL` | 선택 | `nlpai-lab/KURE-v1` | 프로세스 시작 시 한 번 로드하는 Dense 임베딩 모델 |
| `LLM_PROVIDER` | 선택 | `openai` | LLM 제공자. 현재 구현은 `openai`만 지원한다. |
| `LLM_MODEL` | 필수 | 없음 | 답변 생성용 OpenAI 모델. 빈 값이면 설정 오류로 시작에 실패한다. |
| `LLM_API_KEY` | 필수 | 빈 값 | OpenAI API 키 |
| `LLM_RELEVANCE_MODEL` | 선택 | 빈 값 | 관련성 판정 모델. 비우면 `LLM_MODEL`을 사용한다. |
| `LLM_REASONING_EFFORT` | 선택 | 빈 값 | 비우면 요청 파라미터를 생략한다. 모델이 지원할 때만 `low` 등을 지정한다. |
| `LLM_MAX_OUTPUT_TOKENS` | 선택 | `1200` | 답변 생성의 최대 출력 토큰 수 |
| `LLM_TEMPERATURE` | 선택 | `0.7` | 답변 생성의 무작위성(0~2). 지원 모델에만 보낸다. `reasoning.effort`가 `none`이 아니거나 지원 여부가 불명확한 추론 모델에는 자동으로 생략하며, 관련성 yes/no 판정에도 사용하지 않는다. |
| `CHAT_TONE` | 선택 | `hao` | `hao`는 읽기 쉬운 학당 훈장 하오체, `modern`은 현대 해요체. 답변과 범위 밖·재학습·퀴즈 대기 안내에 함께 적용한다. |
| `CONCEPT_STATUS_LABEL_NOT_STARTED` | 선택 | `미학습` | `not_started`의 화면 표시 문구 |
| `CONCEPT_STATUS_LABEL_IN_PROGRESS` | 선택 | `학습중` | `in_progress`의 화면 표시 문구. 팀 용어 확정 전 `미통과` 등으로 교체할 수 있다. |
| `CONCEPT_STATUS_LABEL_PASSED` | 선택 | `통과` | `passed`의 화면 표시 문구 |
| `FREE_QUESTION_AUTO_START` | 선택 | `false` | `false`면 자유 질문은 학습 상태를 바꾸지 않고 `suggested_concept`만 반환한다. 이전 자동 시작 동작이 필요할 때만 `true`로 둔다. |
| `BAND_HIGH` | 선택 | `0.50` | high band 최소 Dense 점수 |
| `BAND_LOW` | 선택 | `0.45` | mid band 최소 Dense 점수. 이 값 미만은 low다. |
| `DISPLAY_SOURCE_MIN_SCORE` | 선택 | `0.60` | 현재 세션 개념 외 문서를 `display_sources`에 노출할 최소 점수 |
| `STAGES_JSON_PATH` | 선택 | `data/stages.json` | 스테이지·학습 개념 정의 파일 |
| `CHAT_DB_URL` | 선택 | `sqlite:///chat.db` | SQLAlchemy DB URL. 배포에서는 Supabase PostgreSQL URL로 교체한다. |
| `DEV_USE_LOCAL_STATUS` | 선택 | `false` | 개발용 `ConceptStatusService`, `dev_` 테이블, `/learning/dev/*`, `/dev/chat` 사용 여부. 로컬 단독 실행에서만 `true`, **배포에서는 `false`**로 둔다. |
| `DEV_SIMULATE_QUIZ_STATUS` | 선택 | `false` | 개발 구현에서 passed 결과를 실제 `통과` 상태로 시뮬레이션한다. **배포에서는 반드시 `false`**로 둔다. |

`LLM_MODEL`에는 계정에서 실제 사용할 수 있는 모델을 지정한다. 모델 지원 여부는
[OpenAI 모델 카탈로그](https://developers.openai.com/api/docs/models)에서 확인한다.

이 변경 전에는 `temperature` 설정이 없어서 OpenAI 요청에서 파라미터를 생략했다. 현재 기본 설정값은
`0.7`이지만 실제 전달 여부는 모델과 추론 설정에 따라 달라진다. OpenAI Responses API의 허용 범위는
0~2이며, OpenAI 배포 가이드에 따라 `reasoning.effort`가 `none`이 아니면 `temperature`를 보내지 않는다.
따라서 예시 `.env`처럼 추론 모델에 `LLM_REASONING_EFFORT=low`를 쓰면 `LLM_TEMPERATURE` 값은 유지하되
요청 파라미터에서는 생략된다. 추론 모델은 `reasoning.effort=none`일 때만 전달하고, `o1`/`o3`/`o4`
계열은 항상 생략한다. 비추론 모델은 설정값을 전달한다.

- [OpenAI Responses API `temperature`](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)
- [OpenAI 배포 체크리스트의 추론 모델 파라미터 안내](https://developers.openai.com/api/docs/guides/deployment-checklist)

## 3. 백엔드 통합 가이드

### 3.1 라우터 등록

기존 FastAPI 앱에 다음 한 줄을 추가한다.

```python
from chatbot.router import router as chat_router
from chatbot.errors import install_learning_error_handlers

app.include_router(chat_router)
install_learning_error_handlers(app)
```

예외 처리기는 모든 JSON 오류를 `{code, message, request_id}`로 통일하고 성공·실패 응답에
`X-Request-ID`를 붙인다. 기존 공통 예외 처리기가 있다면 같은 계약을 유지하도록 합친다.

### 3.2 lifespan에서 검색 의존성 1회 로드

임베딩 모델과 211개 학습 개념 캐시는 요청마다 만들면 안 된다. 기존 백엔드의 lifespan에 다음
초기화를 합친다.

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

from chatbot.deps import (
    get_cached_settings,
    get_concept_cache,
    get_dense_encoder,
    get_qdrant_client,
    get_retriever,
    get_stage_catalog,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_cached_settings()
    get_stage_catalog()
    get_qdrant_client()
    get_dense_encoder()
    get_concept_cache()
    get_retriever()
    yield


app = FastAPI(lifespan=lifespan)
```

`main_dev.py`는 챗봇을 단독 실행하기 위한 예시이며, 통합 백엔드에서는 기존 앱과 lifespan을 유지한다.

### 3.3 통합 시 반드시 교체할 것

1. **인증**: 개발용 `get_current_user_id()`는 `X-User-Id`를 그대로 신뢰한다. 공통 인증 함수로
   교체하거나 FastAPI dependency override를 등록한다.

   ```python
   from chatbot.integrations import get_current_user_id

   app.dependency_overrides[get_current_user_id] = common_get_current_user_id
   ```

2. **학습 상태**: `DevConceptStatusService` 대신 학습 관리 모듈의 실제
   `ConceptStatusService` 구현을 주입한다.

   ```python
   from chatbot.deps import get_concept_status_service

   app.dependency_overrides[get_concept_status_service] = get_real_concept_status_service
   ```

   실제 구현은 `get_statuses(user_id, stage)`,
   `get_in_progress_concept(user_id, stage)`, `mark_in_progress(user_id, concept_id, stage)`,
   `note_quiz_result(user_id, concept_id, stage, passed)` 계약을 지켜야 한다. 상태 키는 반드시
   `(user_id, concept_id, stage)`여야 한다. 저장·API 상태 코드는 `not_started`, `in_progress`,
   `passed`이며 화면 문구는 `/learning/current.status_labels`를 사용한다. `get_current_stage()` 기본 구현은
   Stage 1부터 순서대로 `get_statuses()`를 읽어 `not_started` 또는 `in_progress`가 하나라도 남은 가장
   낮은 단계를 반환한다. Stage 1~4가 모두 `passed`면 Stage 5이며, Stage 5까지 모두 통과해도 완료
   상태의 현재 단계는 Stage 5다.

   스테이지 완료에 따른 캐릭터 승급·보상 이벤트는 챗봇 범위가 아니며 학습 관리 모듈이 담당한다.

3. **DB**: `CHAT_DB_URL`을 Supabase PostgreSQL 연결 문자열로 바꾼다. SQLAlchemy psycopg 형식은
   보통 `postgresql+psycopg://...`이다. 비밀번호와 SSL 옵션은 배포 환경의 secret으로 관리한다.

4. **개발 구현 해제**: 배포 환경에서는 `DEV_USE_LOCAL_STATUS=false`,
   `DEV_SIMULATE_QUIZ_STATUS=false`로 두고 실제 학습 관리 구현을 주입한다. 운영에서
   `in_progress → passed` 처리는 퀴즈·학습 관리 모듈만 수행한다. 이 설정에서는 개발 API와 개발용
   채팅 화면도 등록되지 않는다.

### 3.4 테이블 생성 방식

현재 `SqlChatStore`는 생성될 때 SQLAlchemy의 `Base.metadata.create_all()`을 호출한다. 따라서
`CHAT_DB_URL`이 가리키는 DB에 `learning_sessions`, `learning_messages`, `learning_contexts`,
`learning_completion_requests`가 없으면 서버 시작 중 자동 생성한다. `create_all()`은 일반적인 컬럼
변경·삭제를 수행하는 migration 도구가 아니다. 다만 기존 로컬 SQLite와의 호환을 위해 시작 시
`chat_sessions`/`chat_messages`를 각각 `learning_sessions`/`learning_messages`로 이름 변경하고,
`doc_id` 컬럼과 저장 JSON 키를 `concept_id`로 바꾸며 기존 상태값도 영문 코드로 보존 변환한다.
Supabase 배포 전에는 별도 migration/DDL로 스키마를
관리하고, 최초 생성 역할에 필요한 DB 권한이 있는지 확인하는 방식을 권장한다.

개발용 `dev_concept_status`는 `DEV_USE_LOCAL_STATUS=true`일 때만 생성한다. 현재 스테이지는 이 테이블의
개념 상태로 계산하며 별도 저장하지 않는다. 이전 버전의 `dev_user_stage`가 로컬 DB에 있으면 개발 상태
서비스 시작 시 제거한다. 기본값은 `false`이며, 이 상태에서 기본 개발 구현을 실수로 사용하면 시작
단계에서 명확한 오류가 난다. 배포에서는 플래그를 켜지 말고 실제 `ConceptStatusService`를 주입한다.

## 4. Supabase로 옮기기

1. Supabase Dashboard에서 대상 프로젝트를 연 뒤 상단 **Connect** → **Session pooler**를 선택해 연결
   문자열을 복사한다. 장시간 실행되는 FastAPI 백엔드가 IPv4 환경에서 접속하는 경우 Session pooler가
   적합하고 prepared statement도 지원한다. 자세한 선택 기준은
   [Supabase 연결 방식 문서](https://supabase.com/docs/guides/database/connecting-to-postgres)를 참고한다.
2. 복사한 `postgresql://...`의 scheme을 SQLAlchemy psycopg용 `postgresql+psycopg://...`로 바꾸고
   `CHAT_DB_URL` secret에 저장한다. Session pooler 포트는 Dashboard가 제공한 `5432` 값을 그대로 쓰고,
   전송 암호화를 위해 `?sslmode=require`를 붙인다.

   ```dotenv
   CHAT_DB_URL=postgresql+psycopg://postgres.PROJECT_REF:URL_ENCODED_PASSWORD@POOLER_HOST:5432/postgres?sslmode=require
   ```

3. 비밀번호의 `@`, `:`, `/`, `?`, `#`, `%`, 공백 같은 예약 문자는 URL 인코딩해야 한다. 다음처럼
   비밀번호 값만 변환한 뒤 연결 문자열에 넣는다. 완성된 URL과 원문 비밀번호는 로그나 Git에 남기지 않는다.

   ```python
   from urllib.parse import quote

   encoded_password = quote("실제 비밀번호", safe="")
   ```

4. 배포 설정은 `DEV_USE_LOCAL_STATUS=false`, `DEV_SIMULATE_QUIZ_STATUS=false`로 두고 공통 인증과 실제
   학습 상태 서비스를 주입한다. 인증 의존성이 반환하는 `user_id`는 Supabase Auth JWT의 `sub`, 즉 사용자
   UUID여야 한다. 현재 컬럼은 SQLite 호환 `String`이므로 이 UUID를 표준 문자열 형태로 일관되게 저장한다.
5. 현재 코드는 첫 연결 때 채팅 테이블을 자동 생성한다. 운영에서는 자동 생성이나 SQLite 전용 호환
   마이그레이션에 의존하지 말고, `learning_messages.display_sources`를 포함한 검토된 migration/DDL을 먼저
   적용하는 편이 안전하다.
6. 브라우저의 Supabase Data API에서 학습 데이터가 직접 노출되지 않도록 모듈의 사용자 데이터 테이블
   모두에 RLS를 켜고 정책은 만들지 않는다. 권한도 함께 회수하면 `anon`과 `authenticated` 역할은 아무
   행에도 접근할 수 없다. 서버 전용 DB URL은 백엔드 secret으로만 보관한다.

   ```sql
   alter table public.learning_sessions enable row level security;
   alter table public.learning_messages enable row level security;
   alter table public.learning_contexts enable row level security;
   alter table public.learning_completion_requests enable row level security;

   revoke all on table public.learning_sessions from anon, authenticated;
   revoke all on table public.learning_messages from anon, authenticated;
   revoke all on table public.learning_contexts from anon, authenticated;
   revoke all on table public.learning_completion_requests from anon, authenticated;
   ```

   정책 없는 RLS의 동작과 역할별 권한은
   [Supabase RLS 문서](https://supabase.com/docs/guides/database/postgres/row-level-security)를 참고한다.
   서버 연결에 쓰는 DB 소유자/서버 역할은 RLS를 우회할 수 있으므로, 사용자 격리는 지금처럼 모든 저장소
   조회 조건에 `user_id`를 포함해 유지해야 한다.

## 5. 퀴즈 모듈 연동 가이드

### 5.1 학습 완료와 맥락 조회

사용자가 학습 완료 버튼을 누르면 먼저 다음 API를 호출한다.

```http
POST /learning/sessions/{session_id}/complete
X-User-Id: {user_id}
Idempotency-Key: {client-generated-unique-key}
```

`Idempotency-Key`는 필수다. 같은 사용자와 같은 키로 재요청하면 퀴즈 결과가 이후 바뀌었더라도
최초 완료 시 반환한 학습 맥락을 그대로 재반환한다. 클라이언트는 한 번의 완료 동작에 같은 키를
재사용하고, 새 완료 동작에는 새 키를 만든다.

완료된 맥락은 다음 REST API로 다시 조회할 수 있다.

```http
GET /learning/sessions/{session_id}/learning-context
X-User-Id: {user_id}
```

같은 백엔드 프로세스에서는 서비스 함수를 직접 사용할 수도 있다.

```python
from chatbot.service import get_learning_context

context = get_learning_context(chat_store, user_id, session_id)
```

주요 응답 구조는 다음과 같다.

```json
{
  "session_id": "...",
  "user_id": "...",
  "status": "completed",
  "quiz_status": "pending",
  "concept": {
    "concept_id": "sisa_1281",
    "term": "분업/특화",
    "stage": "stage1",
    "status": "in_progress",
    "attempt": 1,
    "definition": "..."
  },
  "turns": [
    {
      "question": "...",
      "answer": "...",
      "is_related": true,
      "sources": [
        {"concept_id": "sisa_1281", "collection": "sisa_terms", "label": "시사경제용어사전"}
      ],
      "created_at": "..."
    }
  ],
  "mentioned_concepts": [
    {"concept_id": "sisa_2309", "term": "젠트리피케이션"}
  ],
  "completed_at": "..."
}
```

`turns`에는 해당 세션의 관련·비관련 대화를 모두 넣고 각 turn의 `is_related`로 **핵심 대화와 곁가지
대화**를 구분한다. `mentioned_concepts`도 세션의 모든 질문에서 수집하지만 문제 구성 참고용일 뿐이다.
퀴즈 출제 중심과 상태 갱신의 유일한 대상은 처음 학습한 `(concept.concept_id, concept.stage)` 쌍이다.
Stage 3에서 통과한 같은 `concept_id`라도 Stage 5 상태를 갱신하면 안 된다. 세션 밖 free 메시지는 맥락에
들어가지 않으며, 관련 대화가 하나도 없는 세션은 완료할 수 없다(400).

`concept.status`는 **학습 완료 시점의 스냅샷**이다. 퀴즈 생성 시 참고할 수 있지만, 이후 퀴즈 결과나
스테이지 진행이 반영된 현재 상태를 판단할 때는 반드시 학습 관리 모듈의 상태 조회 결과를 기준으로 한다.

### 5.2 퀴즈 결과 보고

3문제 채점과 최종 passed 여부가 결정된 직후 한 번 호출한다.

```http
POST /learning/sessions/{session_id}/quiz-result
X-User-Id: {user_id}
Content-Type: application/json

{"passed": true}
```

같은 프로세스에서는 다음 함수를 호출할 수 있다.

```python
from chatbot.service import report_quiz_result

context = report_quiz_result(
    status_service=concept_status_service,
    store=chat_store,
    user_id=user_id,
    session_id=session_id,
    passed=passed,
)
```

active 세션이나 이미 결과가 기록된 세션은 409다. 챗봇 서비스는 `quiz_status`를 저장하고
`ConceptStatusService.note_quiz_result()`에 알릴 뿐, 운영 개념 상태를 직접 `통과`로 바꾸지 않는다.

## 6. 프론트엔드 연동 가이드

### 6.1 화면 모드와 키워드 버튼

화면 진입과 새로고침 때 `GET /learning/current`를 호출한다. 상단에는 응답의 `learning_guide`를
고정 표시하고, 상태 이름이 필요하면 `status_labels`의 영문 코드별 표시 문구를 사용한다.

`active_session`이 없을 때도 학습 완료 버튼은 활성화해 둔다. 사용자가 누르면 완료 API를 호출하지 않고
상태 응답의 `complete_hint`를 표시한다. active 세션이 있을 때만
`POST /learning/sessions/{session_id}/complete`를 호출한다.

| `mode` | 화면 처리 |
|---|---|
| `normal` | `active_session`이 없으면 `/learning/concepts`의 키워드 버튼을 활성화한다. active 세션이 있으면 다른 개념으로 전환하지 않도록 버튼을 비활성화한다. |
| `relearn` | `locked_concept` 안내와 `notice`를 표시하고 다른 키워드 버튼을 비활성화한다. 첫 메시지가 attempt가 증가한 재학습 세션을 연다. |
| `quiz_pending` | 퀴즈 결과 대기 안내를 표시하고 모든 키워드 버튼을 비활성화한다. 이때 보낸 메시지는 free 대화로 처리된다. |

키워드 목록은 `GET /learning/concepts?offset=0&limit=5`로 읽는다. 키워드를 클릭하면 자동 전송하지
말고 입력창에 `{term}에 대해 알려줘`를 채운다. 사용자가 전송할 때 다음처럼 `concept_id`를
함께 보낸다.

```json
{
  "message": "분업/특화에 대해 알려줘",
  "concept_id": "sisa_1281"
}
```

Stage 5도 별도 파라미터 없이 동일하게 전송한다. 서버는 항상 학습 관리 모듈의
상태 기반 `get_current_stage()` 결과만 사용하며, 요청의 `stage` 필드는 받지 않는다. 자유 질문에는
`concept_id`를 넣지 않으며 기본 설정에서는 세션이나 상태가 바뀌지 않는다. 서버가 현재 스테이지의
`not_started` 개념을 감지하면 `suggested_concept: {concept_id, term}`과 안내 `notice`를 반환한다.
프론트는 `{term} 학습 시작하기` 버튼을 표시하고, 클릭할 때 키워드 버튼과 같은 `concept_id` 포함
요청을 보내야 한다. 학습 시작은 키워드·제안 버튼·재학습처럼 `concept_id`가 명시된 요청에서만 일어난다.

### 6.2 POST SSE 스트리밍

브라우저 `EventSource`는 POST 요청 본문을 지원하지 않으므로 `fetch()`와 `ReadableStream`으로
SSE를 파싱한다. 다음은 최소 TypeScript 예시다.

```ts
type ChatDone = {
  session_id: string | null;
  session_started: boolean;
  display_sources: Array<{
    concept_id: string;
    term: string;
    score: number;
    collection: string;
    label: string;
    images?: string[];
  }>;
  message_id: string;
  notice: string | null;
  suggested_concept: { concept_id: string; term: string } | null;
};

export async function streamChat(
  body: { message: string; concept_id?: string },
  userId: string,
  onToken: (delta: string) => void,
  onDone: (data: ChatDone) => void,
  signal?: AbortSignal,
) {
  const response = await fetch("/learning/messages/stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": userId,
    },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok || !response.body) {
    throw new Error(`chat stream failed: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });

    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const lines = block.split("\n");
      const event = lines.find((line) => line.startsWith("event: "))?.slice(7);
      const dataText = lines.find((line) => line.startsWith("data: "))?.slice(6);
      if (!event || !dataText) continue;

      const data = JSON.parse(dataText);
      if (event === "token") onToken(data.delta);
      if (event === "done") onDone(data as ChatDone);
      if (event === "error") throw new Error(data.message);
    }
    if (done) break;
  }
}
```

`token`의 `delta`를 순서대로 이어 붙여 답변을 표시한다. `done`을 받은 뒤 세션과 메시지 상태를
확정한다. 사용자가 취소하면 `AbortController.abort()`를 호출한다. 서버는 중간 연결 종료 시
메시지와 새 세션을 저장하지 않는다.

`done.notice`는 답변 아래 별도 안내 상자로 표시한다. 이는 LLM이 쓴 답변 문장이 아니라 서버가
`CHAT_TONE`에 맞게 만든 문구다. 다른 스테이지 개념, 현재 스테이지에서 이미 통과한 개념,
extra/excluded 용어, low band 질문을 성장·퀴즈 반영 여부와 함께 안내한다. 학습 세션 중 다른 개념을
물어도 현재 세션과 상태는 유지한 채 같은 규칙으로 표시한다.

화면 출처에는 `sources`가 아니라 **`display_sources`**를 사용한다. `sources`는 LLM에 전달한 전체
근거와 퀴즈 맥락 저장용이며, 화면 노출 임계값이 적용되지 않는다.

### 6.3 새로고침 시 대화 복원

- `GET /learning/sessions/{session_id}/messages`: 해당 세션의 관련·비관련 메시지를 모두 시간순으로 반환한다.
- `GET /learning/history?limit=50`: 현재 사용자의 세션 메시지와 free 메시지를 합친 최신 N개를 선택한 뒤
  오래된 것부터 반환한다.
- 각 항목의 `role`, `content`, `is_related`, `band`, `display_sources`, `created_at`으로 채팅 화면을
  복원한다. 화면 출처는 여기서도 `display_sources`만 사용한다.

### 6.4 학습 진행률

`GET /learning/progress`는 인증된 현재 사용자의 진행률만 반환한다. `current`는 현재 스테이지 요약이고,
`stages`에는 Stage 1~5 각각의 아래 값과 `unlocked`, `completed`가 들어간다.

```json
{
  "current": {
    "stage_id": "stage1",
    "name_ko": "사회경제현상과 소비생활",
    "total_count": 30,
    "passed_count": 3,
    "in_progress_count": 1,
    "not_started_count": 26,
    "remaining_count": 27,
    "percent": 10
  },
  "stages": []
}
```

`percent`는 `floor(passed_count / total_count * 100)`이므로 학습 중인 개념은 퍼센트에 포함하지 않는다.
Stage 5는 앞 단계와 겹치는 개념도 `(concept_id, stage5)`로 별도 집계해 총 70개다. `/learning/current.progress`에도
같은 현재 스테이지 요약이 있으므로 화면 상단 진행률 바와 `남은 개념 N개` 표시에 사용할 수 있다.

## 7. 검색 소스 추가 체크리스트

명세 6.5의 확장 절차다.

1. 새 문서를 청크 JSONL로 만들고 각 payload에 `concept_id`, `term`, `text`, `source`, `stages`를 넣는다.
   기존 Qdrant payload의 `doc_id`는 하위 호환으로 읽지만 새 데이터와 애플리케이션 코드는
   `concept_id`를 기준으로 한다.
2. 그래프·표 이미지가 있으면 공개 가능한 Storage URL을 `images: string[]`에 넣는다. 로컬 절대
   경로는 저장하지 않는다.
3. 데이터 적재 도구에서 `embed_and_upload.py --collection <새 컬렉션>`으로 Qdrant에 올린다.
4. 해당 소스용 골든셋으로 `eval_golden.py --collection <새 컬렉션>`을 실행해 dense/hybrid mode를
   결정한다.
5. `chatbot/config.py`의 `SEARCH_PROFILES`에 컬렉션, `mode`, `k`, `slots`, `label`,
   `concept_source`를 추가한다. 일반 보조 자료는 `concept_source=False`로 둔다.
6. hybrid 프로필을 쓰면 배포 환경에 희소 인코더도 제공되는지 확인한다.
7. 다중 소스 mock 테스트에서 자리 배분, label, images, low band 처리를 확인한다. band와 개념 감지,
   현재 개념 관련성은 `concept_source=True`인 Dense 소스를 기준으로 유지한다.

## 8. 명세 9장 완료 기준 점검

| # | 완료 기준 | 상태 | 근거·남은 작업 |
|---:|---|---|---|
| 1 | stage1 `not_started` 개념 5개 추천, 페이지네이션, 통과 제외 | 충족 | `/learning/concepts`와 개념 추천 테스트로 검증 |
| 2 | 분업/특화 키워드 시작, `in_progress` 변경, 출처 답변 | 충족 | mock 단위 테스트와 수동 서버 테스트로 검증 |
| 3 | 워킹푸어 자유 질문 감지와 명시적 학습 제안 | 충족 | 기본 설정에서 세션·상태를 바꾸지 않고 `suggested_concept`와 제안 notice를 반환하며, 설정을 켠 이전 자동 시작도 테스트 |
| 4 | 다른 스테이지·통과 개념 질문은 free 답변 | 충족 | 현재 단계 후보만 제안하며 다른 스테이지 개념은 상태를 바꾸지 않음 |
| 5 | 날씨 질문 low band 및 범위 밖 안내 | 충족 | low band에서 두 sources 배열이 비고 서버 생성 `notice`가 반환되는 테스트 존재 |
| 6 | 학습 중 다른 개념 질문 표시 및 상태 고정 | 충족 | 젠트리피케이션 질문의 `is_related=false`, 전체 맥락 포함, 상태 불변 검증 |
| 7 | 현재 개념명을 생략한 비교 질문도 관련 대화로 포함 | 충족 | 최근 1~2턴과 현재 개념을 포함한 LLM 판정으로 인플레이션/디플레이션 비교는 true, 독립적인 젠트리피케이션 질문은 false로 검증 |
| 8 | 다른 개념 질문에도 쉬운 설명 제공 | 충족 | 관련성은 저장 맥락만 제어하며 답변 프롬프트는 질문을 거절하지 않는다. |
| 9 | 학습 완료 후 `in_progress` 유지, 전체 세션 맥락·attempt 저장 | 충족 | 각 turn의 `is_related`, 전체 `mentioned_concepts`, free 제외, 완료 멱등성을 테스트 |
| 10 | quiz `failed` 후 relearn, attempt 2, 다른 키워드 409 | 충족 | 개념 상태 코드와 별개로 quiz_status `failed`를 유지하는 시나리오 테스트로 검증 |
| 11 | 재시작 후 대화와 학습 맥락 복원 | 충족 | 세션 메시지 및 전체 최근 기록 API가 free 메시지, 시간순, `display_sources`, 사용자 격리를 포함해 SQL 기록을 반환 |
| 12 | 다른 사용자 세션 접근 404 | 충족 | 세션·학습 맥락·퀴즈 결과 사용자 격리 테스트 존재 |
| 13 | 메시지 지연 시간 저장 | 충족 | assistant 행 `latency_ms` 저장 테스트 존재 |
| 14 | mock 이미지의 `sources[].images` 전달 | 충족 | Stage 5 이미지 payload 테스트로 검증 |
| 15 | 두 번째 검색 컬렉션 자리 배분 | 충족 | 다중 `SEARCH_PROFILES` mock 테스트로 검증 |
| 16 | 개발 훅 퀴즈 통과 후 다음 `not_started` 노출 | 충족 | quiz failed → attempt 2 → passed → 다음 5개 시나리오로 검증 |

현재 평가는 **16개 전부 충족**이다. Stage 5의 중복 개념도 `(concept_id, stage)` 상태 키로 독립 관리하며,
재학습·심화 프롬프트, 서버 생성 안내, 전체 세션 기반 `mentioned_concepts`, 스테이지별 진행률까지 회귀 테스트로 확인한다.
