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
- 기본 API prefix: `/chat`

`/docs`에서 요청을 시험할 때는 다음 순서로 진행한다.

1. 원하는 `/chat/...` API를 펼치고 **Try it out**을 누른다.
2. `X-User-Id` 헤더 입력란에 `local-user-1`처럼 테스트 사용자 ID를 넣는다.
3. 메시지 API라면 요청 본문을 입력한 뒤 **Execute**를 누른다.

예를 들어 `POST /chat/messages`의 본문은 다음과 같다.

```json
{
  "message": "분업/특화에 대해 알려줘",
  "selected_doc_id": "sisa_1281"
}
```

Stage 5 버튼으로 고른 개념만 `"stage": "stage5"`를 `selected_doc_id`와 함께 보낸다.

### 1.4 테스트

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
| `BAND_HIGH` | 선택 | `0.50` | high band 최소 Dense 점수 |
| `BAND_LOW` | 선택 | `0.45` | mid band 최소 Dense 점수. 이 값 미만은 low다. |
| `DISPLAY_SOURCE_MIN_SCORE` | 선택 | `0.60` | 현재 세션 개념 외 문서를 `display_sources`에 노출할 최소 점수 |
| `STAGES_JSON_PATH` | 선택 | `data/stages.json` | 스테이지·학습 개념 정의 파일 |
| `CHAT_DB_URL` | 선택 | `sqlite:///chat.db` | SQLAlchemy DB URL. 배포에서는 Supabase PostgreSQL URL로 교체한다. |
| `DEV_USE_LOCAL_STATUS` | 선택 | `false` | 개발용 `ConceptStatusService`와 `dev_` 테이블 사용 여부. 로컬 단독 실행에서만 `true`, **배포에서는 `false`**로 둔다. |
| `DEV_SIMULATE_QUIZ_STATUS` | 선택 | `false` | 개발 구현에서 passed 결과를 실제 `통과` 상태로 시뮬레이션한다. **배포에서는 반드시 `false`**로 둔다. |

`LLM_MODEL`에는 계정에서 실제 사용할 수 있는 모델을 지정한다. 모델 지원 여부는
[OpenAI 모델 카탈로그](https://developers.openai.com/api/docs/models)에서 확인한다.

## 3. 백엔드 통합 가이드

### 3.1 라우터 등록

기존 FastAPI 앱에 다음 한 줄을 추가한다.

```python
from chatbot.router import router as chat_router

app.include_router(chat_router)
```

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

   실제 구현은 `get_current_stage`, `get_statuses`, `get_failed_concept`, `mark_failed`,
   `note_quiz_result` 계약을 지켜야 한다.

3. **DB**: `CHAT_DB_URL`을 Supabase PostgreSQL 연결 문자열로 바꾼다. SQLAlchemy psycopg 형식은
   보통 `postgresql+psycopg://...`이다. 비밀번호와 SSL 옵션은 배포 환경의 secret으로 관리한다.

4. **개발 구현 해제**: 배포 환경에서는 `DEV_USE_LOCAL_STATUS=false`,
   `DEV_SIMULATE_QUIZ_STATUS=false`로 두고 실제 학습 관리 구현을 주입한다. 운영에서
   `미통과 → 통과` 처리는 퀴즈·학습 관리 모듈만 수행한다.

### 3.4 테이블 생성 방식

현재 `SqlChatStore`는 생성될 때 SQLAlchemy의 `Base.metadata.create_all()`을 호출한다. 따라서
`CHAT_DB_URL`이 가리키는 DB에 `chat_sessions`, `chat_messages`, `learning_contexts`가 없으면 서버
시작 중 자동 생성한다. 이미 있는 테이블의 컬럼 변경·삭제는 수행하지 않으므로 `create_all()`은
마이그레이션 도구가 아니다. 배포 전에는 별도 migration/DDL로 스키마를 관리하고, 최초 생성 역할에
필요한 DB 권한이 있는지 확인하는 방식을 권장한다.

개발용 `dev_concept_status`, `dev_user_stage`는 `DEV_USE_LOCAL_STATUS=true`일 때만 생성한다. 기본값은
`false`이며, 이 상태에서 기본 개발 구현을 실수로 사용하면 시작 단계에서 명확한 오류가 난다. 배포에서는
플래그를 켜지 말고 실제 `ConceptStatusService`를 주입한다.

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
5. 현재 코드는 첫 연결 때 채팅 테이블을 자동 생성하지만 기존 스키마를 변경하지는 않는다. 운영에서는
   자동 생성에 의존하기보다 검토한 migration/DDL을 먼저 적용하는 편이 안전하다.
6. 브라우저의 Supabase Data API에서 채팅 데이터가 직접 노출되지 않도록 모듈의 사용자 데이터 테이블
   모두에 RLS를 켜고 정책은 만들지 않는다. 권한도 함께 회수하면 `anon`과 `authenticated` 역할은 아무
   행에도 접근할 수 없다. 서버 전용 DB URL은 백엔드 secret으로만 보관한다.

   ```sql
   alter table public.chat_sessions enable row level security;
   alter table public.chat_messages enable row level security;
   alter table public.learning_contexts enable row level security;

   revoke all on table public.chat_sessions from anon, authenticated;
   revoke all on table public.chat_messages from anon, authenticated;
   revoke all on table public.learning_contexts from anon, authenticated;
   ```

   정책 없는 RLS의 동작과 역할별 권한은
   [Supabase RLS 문서](https://supabase.com/docs/guides/database/postgres/row-level-security)를 참고한다.
   서버 연결에 쓰는 DB 소유자/서버 역할은 RLS를 우회할 수 있으므로, 사용자 격리는 지금처럼 모든 저장소
   조회 조건에 `user_id`를 포함해 유지해야 한다.

## 5. 퀴즈 모듈 연동 가이드

### 5.1 학습 완료와 맥락 조회

사용자가 학습 완료 버튼을 누르면 먼저 다음 API를 호출한다.

```http
POST /chat/sessions/{session_id}/complete
X-User-Id: {user_id}
```

완료된 맥락은 다음 REST API로 다시 조회할 수 있다.

```http
GET /chat/sessions/{session_id}/learning-context
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
    "doc_id": "sisa_1281",
    "term": "분업/특화",
    "stage": "stage1",
    "status": "미통과",
    "attempt": 1,
    "definition": "..."
  },
  "turns": [
    {
      "question": "...",
      "answer": "...",
      "sources": [
        {"doc_id": "sisa_1281", "collection": "sisa_terms", "label": "시사경제용어사전"}
      ],
      "created_at": "..."
    }
  ],
  "mentioned_concepts": [
    {"doc_id": "sisa_2309", "term": "젠트리피케이션"}
  ],
  "completed_at": "..."
}
```

`turns`에는 `is_related=true`인 대화만 들어간다. 퀴즈와 상태 갱신의 유일한 대상은
`concept.doc_id`다. `mentioned_concepts`는 문제 구성 참고용이며 상태를 변경하면 안 된다.

### 5.2 퀴즈 결과 보고

3문제 채점과 최종 passed 여부가 결정된 직후 한 번 호출한다.

```http
POST /chat/sessions/{session_id}/quiz-result
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

화면 진입과 새로고침 때 `GET /chat/state`를 호출한다.

| `mode` | 화면 처리 |
|---|---|
| `normal` | `active_session`이 없으면 `/chat/concepts`의 키워드 버튼을 활성화한다. active 세션이 있으면 다른 개념으로 전환하지 않도록 버튼을 비활성화한다. |
| `relearn` | `locked_concept` 안내와 `notice`를 표시하고 다른 키워드 버튼을 비활성화한다. 첫 메시지가 attempt가 증가한 재학습 세션을 연다. |
| `quiz_pending` | 퀴즈 결과 대기 안내를 표시하고 모든 키워드 버튼을 비활성화한다. 이때 보낸 메시지는 free 대화로 처리된다. |

키워드 목록은 `GET /chat/concepts?offset=0&limit=5`로 읽는다. 키워드를 클릭하면 자동 전송하지
말고 입력창에 `{term}에 대해 알려줘`를 채운다. 사용자가 전송할 때 다음처럼 `selected_doc_id`를
함께 보낸다.

```json
{
  "message": "분업/특화에 대해 알려줘",
  "selected_doc_id": "sisa_1281"
}
```

Stage 5 선택 버튼이라면 `"stage": "stage5"`도 함께 보낸다. 자유 질문에는
`selected_doc_id`와 `stage`를 넣지 않는다.

### 6.2 POST SSE 스트리밍

브라우저 `EventSource`는 POST 요청 본문을 지원하지 않으므로 `fetch()`와 `ReadableStream`으로
SSE를 파싱한다. 다음은 최소 TypeScript 예시다.

```ts
type ChatDone = {
  session_id: string | null;
  session_started: boolean;
  display_sources: Array<{
    doc_id: string;
    term: string;
    score: number;
    collection: string;
    label: string;
    images?: string[];
  }>;
  message_id: string;
};

export async function streamChat(
  body: { message: string; selected_doc_id?: string; stage?: "stage5" },
  userId: string,
  onToken: (delta: string) => void,
  onDone: (data: ChatDone) => void,
  signal?: AbortSignal,
) {
  const response = await fetch("/chat/messages/stream", {
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
      if (event === "error") throw new Error(data.detail);
    }
    if (done) break;
  }
}
```

`token`의 `delta`를 순서대로 이어 붙여 답변을 표시한다. `done`을 받은 뒤 세션과 메시지 상태를
확정한다. 사용자가 취소하면 `AbortController.abort()`를 호출한다. 서버는 중간 연결 종료 시
메시지와 새 세션을 저장하지 않는다.

화면 출처에는 `sources`가 아니라 **`display_sources`**를 사용한다. `sources`는 LLM에 전달한 전체
근거와 퀴즈 맥락 저장용이며, 화면 노출 임계값이 적용되지 않는다.

## 7. 검색 소스 추가 체크리스트

명세 6.5의 확장 절차다.

1. 새 문서를 청크 JSONL로 만들고 각 payload에 `doc_id`, `term`, `text`, `source`, `stages`를 넣는다.
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
| 1 | stage1 미학습 5개 추천, 페이지네이션, 통과 제외 | 충족 | `/chat/concepts`와 개념 추천 테스트로 검증 |
| 2 | 분업/특화 키워드 시작, 미통과 변경, 출처 답변 | 충족 | mock 단위 테스트와 실제 OpenAI 호출로 검증 |
| 3 | 워킹푸어 자유 질문 자동 감지 | 충족 | 비스트리밍·실제 SSE 호출에서 `sisa_1963` 세션 시작 확인 |
| 4 | 다른 스테이지·통과 개념 질문은 free 답변 | 충족 | 현재 스테이지 미학습 후보로만 자동 감지하며 Stage 5 미자동 감지 테스트 존재 |
| 5 | 날씨 질문 low band 및 범위 밖 안내 | 충족 | low band에서 두 sources 배열이 비는 테스트 존재 |
| 6 | 학습 중 다른 개념 질문 제외 및 상태 고정 | 충족 | 젠트리피케이션 질문의 `is_related=false`와 상태 불변 검증 |
| 7 | 현재 개념명을 생략한 비교 질문도 관련 대화로 포함 | 미충족 | 다른 개념 용어만 명시되면 현재 관련성 검색보다 먼저 false 처리된다. 관련성 규칙 보완과 회귀 테스트가 필요하다. |
| 8 | 다른 개념 질문에도 쉬운 설명 제공 | 충족 | 관련성은 저장 맥락만 제어하며 답변 프롬프트는 질문을 거절하지 않는다. |
| 9 | 학습 완료 후 미통과 유지, 관련 맥락·attempt 저장 | 충족 | 6단계 통합 시나리오 테스트로 검증 |
| 10 | failed 후 relearn, attempt 2, 다른 키워드 409 | 충족 | 상태·메시지 시나리오 테스트로 검증 |
| 11 | 재시작 후 대화와 학습 맥락 복원 | 부분 | SQL 저장과 학습 맥락 재조회는 가능하지만 화면 복원용 `GET /chat/sessions/{id}/messages`, `GET /chat/history`는 아직 없다. |
| 12 | 다른 사용자 세션 접근 404 | 충족 | 세션·학습 맥락·퀴즈 결과 사용자 격리 테스트 존재 |
| 13 | 메시지 지연 시간 저장 | 충족 | assistant 행 `latency_ms` 저장 테스트 존재 |
| 14 | mock 이미지의 `sources[].images` 전달 | 충족 | Stage 5 이미지 payload 테스트로 검증 |
| 15 | 두 번째 검색 컬렉션 자리 배분 | 충족 | 다중 `SEARCH_PROFILES` mock 테스트로 검증 |
| 16 | 개발 훅 퀴즈 통과 후 다음 미학습 노출 | 충족 | failed → attempt 2 → passed → 다음 5개 시나리오로 검증 |

현재 평가는 **충족 14개, 부분 1개, 미충족 1개**다. 단계 1~8의 예정 구현 범위는 완료됐지만,
명세 9장의 완전 충족을 위해서는 표의 7번과 11번 후속 구현이 필요하다.
