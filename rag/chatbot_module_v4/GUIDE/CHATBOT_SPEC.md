# 「나의 경세학당」 RAG 챗봇 모듈 구현 명세

> 이 문서는 Cursor(AI 코딩 도구)에게 챗봇 모듈 구현을 요청하기 위한 명세다.
> 구현 전 반드시 끝까지 읽고, **8. 작업 방식**의 순서를 따른다.

---

## 1. 배경과 범위

- 서비스: 「나의 경세학당」 — 조선시대 학당 콘셉트의 AI 맞춤형 경제학습 서비스 (React + TypeScript / FastAPI / Supabase / Qdrant)
- 대상: 만 19~26세 사회 진출 준비자·사회초년생
- 전체 학습 흐름: 로그인 → 사전테스트 → 분석 리포트 → 캐릭터 설정 → 스테이지 순차 진행 → **RAG 챗봇 학습** → 학습 완료 버튼 → 퀴즈 3문제 → 통과 판정 → 학습노트 갱신 → 캐릭터 성장
- 이 모듈: **RAG 챗봇** (선택한 경제 개념을 대화형으로 학습)
- 다른 팀원이 나중에 이 모듈을 전체 백엔드에 합친다. 따라서 **독립된 FastAPI `APIRouter`** 로 만들고, 앱 전역 설정에 의존하지 않는다.

**이 모듈이 하는 일**
1. 현재 스테이지의 **`not_started`** 개념을 5개씩 추천 (`in_progress` 개념이 있으면 재학습 모드)
2. 키워드·제안 버튼 등 `concept_id`가 포함된 명시적 선택으로 학습 세션을 시작하고 개념 상태를 `not_started → in_progress`로 변경
3. 질문에 대한 RAG 답변 생성
4. 대화 기록 저장 (현재 개념과 관련 있는 대화인지 표시)
5. "학습 완료" 시 **개념 상태(`in_progress`)와 학습 맥락**을 퀴즈 모듈에 전달할 수 있도록 저장·제공
6. 개념 통과·스테이지 완료 이벤트를 `learning_events`에 기록하고 게임 모듈에 제공

**이 모듈이 하지 않는 일 (다른 담당)**
- 퀴즈 생성·채점·통과 판정 (개념당 3문제: OX 2 + 상황형 4지선다 1, 2문제 이상 정답 시 통과) → 퀴즈 담당이 4.5의 학습 맥락을 사용
- 퀴즈 채점·통과 판정과 학습노트 (퀴즈 모듈), 캐릭터 승급·보상 판정 (게임 모듈·김선빈)
- 로그인 화면·토큰 발급 (Supabase Auth) → 공통 인증 검증 함수를 **주입받아 사용**만 한다 (4.7 참고)
- 사전테스트 (사전테스트 개념셋은 학습 개념셋과 별개)

## 2. 이미 준비된 자산 (수정 금지, 재사용)

| 자산 | 내용 |
|---|---|
| `rag_common.py` | Dense 인코더(`DenseEncoder`), 검색 함수(`search`), 스테이지 필터(`stage_filter`). **검색 로직은 수정하지 말고 import 해서 사용** |
| `stages.json` | 스테이지별 학습 개념 목록 (순서·소분류·concept_id·용어) |
| Qdrant Cloud | 컬렉션 `sisa_terms`, 포인트 3,029건 (시사경제용어사전) |

### 2.1 Qdrant 컬렉션 `sisa_terms`
- 벡터: `dense` (nlpai-lab/KURE-v1, 1024차원, Cosine), `sparse` (Kiwi+BM25, **사용하지 않음**)
- payload 필드

| 필드 | 예시 | 비고 |
|---|---|---|
| `concept_id` | `sisa_745` | 애플리케이션 기준 개념 식별자. 새 payload는 이 이름을 사용 |
| `doc_id` | `sisa_745` | 기존 적재 데이터 하위 호환 필드. 읽기·필터 fallback만 유지 |
| `term` / `term_full` | `기회비용` / `기회비용` | 짧은 이름 / 원래 표기 |
| `aliases` | `["Opportunity Cost"]` | |
| `domain_ko` | `거시경제와 통화·재정정책` | |
| `stages` | `["stage3","stage5"]` / `["extra"]` / `["excluded"]` | 리스트, 필터용 |
| `source` | `시사경제용어사전` | 답변 출처 표기에 사용 |
| `text` | `용어: …\n도메인: …\n설명: …` | LLM에 전달할 본문 |

### 2.2 검색 규칙 (평가로 확정됨, 변경 금지)
- **Dense 단독 검색**: `search(client, query, dense, None, mode="dense", k=5)` — sparse 인자는 `None`
- 하이브리드(RRF), 리랭커는 사용하지 않는다 (골든셋 평가에서 성능 하락).
- 임베딩 모델은 서버 시작 시 **한 번만 로드**한다 (요청마다 로드 금지).

### 2.3 stages.json 구조
```json
{ "stages": [ { "id": "stage1", "name_ko": "사회경제현상과 소비생활", "concept_count": 30,
    "subcategories": ["경제 기본", "..."],
    "concepts": [ { "order": 1, "subcategory": "경제 기본", "concept_id": "sisa_1281",
                    "term": "분업/특화", "term_full": "분업/특화", "other_stages": [] } ] } ] }
```

---

## 3. 사용자 흐름

### 3.1 개념 상태와 상태 변경 주체
| 상태 | 의미 | 바꾸는 주체 |
|---|---|---|
| `not_started` | 아직 학습을 시작하지 않음 | - |
| `in_progress` | 학습을 시작했거나 퀴즈에서 떨어짐 (사용자당 **항상 0개 또는 1개**) | **챗봇** (`not_started → in_progress`) |
| `passed` | 퀴즈가 통과로 판정한 상태 | **학습 관리** (퀴즈의 passed 입력을 받아 `in_progress → passed`) |

저장·API·모듈 연동에는 위 영문 코드를 사용한다. 화면 표시 문자열은
`not_started=미학습`, `in_progress=학습중`, `passed=통과`로 확정한다. 퀴즈 결과의 `quiz_status="failed"`는 개념
상태 코드가 아니므로 그대로 유지한다.

- 스테이지는 사용자가 고르지 않고 시스템이 정한 순서대로 진행한다. Stage 5는 Stage 1~4를 모두
  마친 뒤 열리며, 겹치는 개념을 포함한 70개 전부를 심화 버전으로 다시 학습한다.
- 개념 상태는 `(concept_id, stage)` 쌍으로 관리한다. 같은 `concept_id`가 앞 스테이지에서 통과했어도
  Stage 5에서는 별도의 `not_started` 상태로 시작한다.
- `passed` 개념은 다시 추천하지 않는다.
- 현재 스테이지를 별도 필드로 저장하지 않는다. Stage 1부터 순서대로 보아 `not_started` 또는
  `in_progress`가 하나라도 남은 가장 낮은 스테이지가 현재 스테이지다. Stage 1~4가 모두 `passed`면
  Stage 5이며, Stage 5까지 모두 통과한 완료 상태에서도 Stage 5를 유지한다.

### 3.2 학습 시작: 명시적 개념 선택
학습 중인 개념이 없을 때 키워드 버튼이나 학습 제안 버튼에서 `concept_id`를 포함해 보낸 요청만
학습을 시작한다.
1. **키워드 선택**: 하단에 현재 스테이지의 `not_started` 개념 5개가 버튼으로 노출된다. 누르면
   입력창에 `{term}에 대해 알려줘`가 자동 입력되고(자동 전송 안 함), 사용자가 전송하면 시작한다.
2. **자유 질문의 학습 제안**: 자유 질문에서 현재 스테이지의 `not_started` 개념을 감지해도 답변만
   `free`로 저장하며 상태와 세션은 바꾸지 않는다. 응답의 `suggested_concept {concept_id, term}`과
   notice로 제안하고, 사용자가 `{term} 학습 시작하기` 버튼을 누르면 `concept_id`가 포함된 새 요청으로
   시작한다.
3. **재학습**: 잠긴 개념의 `concept_id`를 포함한 요청으로만 attempt가 증가한 새 세션을 시작한다.

학습이 시작되면 세션이 만들어지고 개념 상태를 `not_started → in_progress`로 바꾼다. 자유 질문이
다른 스테이지 개념, 이미 `passed`인 개념, 경제 범위 밖 용어인 경우에도 답변만 하고 시작하지 않는다.
`FREE_QUESTION_AUTO_START=true`일 때만 이전 자동 시작 동작을 사용할 수 있으며 기본값은 `false`다.

### 3.3 학습 중
- 추가 질문으로 개념을 더 학습한다.
  - 현재 개념과 **관련 있는 질문**: 답변 + 학습 맥락에 `is_related=true`로 포함
  - **관련 없는 질문**(현재 스테이지의 다른 개념 포함): 답변 + 학습 맥락에 `is_related=false`로 포함, 상태 변경 없음
- **"학습 완료" 버튼**을 누르면 세션이 종료되고, `in_progress` 상태와 세션의 모든 대화를 담은 **학습 맥락**이 퀴즈로 전달된다. 퀴즈는 `is_related`로 핵심 대화와 곁가지 대화를 구분한다.
- 퀴즈 결과로 `passed`가 되면 현재 스테이지의 남은 `not_started` 키워드가 다시 노출된다.

### 3.4 재학습 모드 (퀴즈 후에도 `in_progress` 1개)
- 학습 중 개념을 먼저 해결하도록 **UI를 강제**한다.
  - 키워드 버튼 비활성화
  - 상단 안내(기본 하오체): `지금 {term} 개념을 학습 중이오. 이 개념을 통과해야 다음 개념으로 넘어갈 수 있소.`
- 입력창에는 `{term}에 대해 다시 알려줘`를 자동 입력할 수 있고 잠긴 `concept_id`를 함께 보내야
  **새 세션**(재학습, `attempt` 증가)이 시작된다.
- 자유 질문이 현재 스테이지의 다른 개념이어도 **새 학습을 시작하지 않고 답변만** 한다.
- 학습 완료 시 다시 `in_progress` 상태와 새 세션의 학습 맥락을 퀴즈로 전달 → 퀴즈가 `passed` 또는 `in_progress` 유지 결정.

### 3.5 개념 고정 원칙 (중요)
- 세션은 **처음 학습을 시작한 개념 하나에 고정**된다.
- **DB 갱신은 처음 개념에만** 한다. 세션 도중 다른 개념이 언급되거나 질문돼도
  - 새 세션을 시작하지 않는다
  - 그 개념의 상태를 **절대 바꾸지 않는다** (`not_started`·`in_progress`·`passed` 모두 그대로)
  - 퀴즈 결과도 **처음 개념에만** 반영된다 → 학습 맥락의
    `(concept.concept_id, concept.stage)`가 유일한 갱신 대상
  - 이유: 다른 개념은 한두 번 설명을 들었을 뿐 제대로 이해했는지 알 수 없고, 상태가 여러 개념에 퍼지면 꼬인다
- **설명은 항상 제대로 한다.** 다른 개념 질문이라도 "지금은 OO을 학습 중이라 답할 수 없다"며 거절하지 않고, 쉬운 설명을 똑같이 제공한다.
- 학습 맥락(퀴즈 재료)에는 세션의 모든 완성된 대화쌍을 포함하고 각 turn에 `is_related`를 기록한다.
  비교·연결 대화는 `true`, 다른 개념만 묻는 곁가지 대화는 `false`다. 세션 전체 질문에서 언급된
  다른 개념은 `mentioned_concepts`에 참고용으로 기록하되, 퀴즈 출제 중심과 유일한 상태 갱신 대상은
  처음 학습한 `(concept.concept_id, concept.stage)`다. 세션 밖 free 메시지는 학습 맥락에 넣지 않는다.
- 새 개념을 정식으로 학습하려면 현재 개념을 통과한 뒤, 다음 학습에서 시작한다.

## 4. API 명세 (prefix: `/learning`)

> 모든 API는 공통 인증 의존성에서 받은 `user_id` 로 동작한다. 요청 본문으로 `user_id` 를 받지 않는다.
> 다른 사용자의 세션에 접근하면 **404** (존재 여부를 노출하지 않음).
> 모든 JSON 오류는 `{ "code": "...", "message": "...", "request_id": "..." }` 형식이며 모든
> 응답 헤더에 `X-Request-ID`를 포함한다. 시간은 UTC ISO 8601로 반환한다. 로그에는 요청 본문,
> 인증 토큰, 비밀번호를 남기지 않는다.

### 4.1 개념 추천
`GET /learning/concepts?offset=0&limit=5`
- 현재 스테이지(학습 관리 모듈 제공)의 개념 중 **`not_started` 상태만** `order` 순으로 반환
- 응답
```json
{ "mode": "normal",
  "stage": { "id": "stage1", "name_ko": "사회경제현상과 소비생활" },
  "concepts": [ { "concept_id": "sisa_1281", "term": "분업/특화", "term_full": "분업/특화", "subcategory": "경제 기본", "order": 1 } ],
  "next_offset": 5, "has_more": true,
  "locked_concept": null, "notice": null }
```
- `in_progress` 개념이 있으면 `"mode": "relearn"`, `locked_concept`에 해당 개념, `notice`에 3.4의 안내 문구, `suggested_message`에 `{term}에 대해 다시 알려줘`를 넣는다. 이때 `concepts`는 화면 표시용으로만 내려주고 프론트에서 비활성화한다.

### 4.2 메시지 전송 (단일 진입점)
`POST /learning/messages`
- 요청: `{ "message": "분업/특화에 대해 알려줘", "concept_id": "sisa_1281" }`
  - `concept_id`: 키워드 버튼으로 입력된 경우에만 프론트가 함께 보낸다 (선택). 자유 질문이면 생략.
  - 클라이언트는 `stage`를 보내지 않는다. 모든 분기와 검증은 `get_current_stage()` 결과를 사용한다.
- 서버 처리 순서
  1. **진행 중(active) 세션이 있으면** 그 세션에 메시지를 추가한다 (관련성 판정 5.1).
  2. **재학습 모드**(`in_progress` 1개, active 세션 없음)에서 잠긴 `concept_id`가 오면 새 세션(`attempt+1`)을 시작한다. 다른 ID는 409, ID가 없는 자유 질문은 free 답변이다.
  3. `concept_id`가 있으면 현재 스테이지의 `not_started` 개념인지 검증 후 세션 시작한다. 아니면 409다.
  4. 자유 질문이면 개념을 감지하되 기본 설정에서는 세션을 시작하지 않고 `suggested_concept`와
     학습 제안 notice를 반환한다. `FREE_QUESTION_AUTO_START=true`일 때만 감지 시작한다.
  5. 위에 해당하지 않으면 세션 없이 **답변만** 하고 기록은 `free` 메시지로 저장한다 (퀴즈와 무관).
  - 세션을 새로 시작할 때 `ConceptStatusService.mark_in_progress()`로 상태를 `not_started → in_progress`로 바꾼다.
- 응답
```json
{ "answer": "...", "session_id": "...또는 null", "session_started": true,
  "concept": { "concept_id": "sisa_1281", "term": "분업/특화", "stage": "stage1", "status": "in_progress", "attempt": 1 },
  "is_related": true, "band": "high", "top_score": 0.71,
  "sources": [ { "concept_id": "sisa_1281", "term": "분업/특화", "score": 0.71 } ],
  "display_sources": [ { "concept_id": "sisa_1281", "term": "분업/특화", "score": 0.71 } ],
  "message_id": "...", "notice": null, "suggested_concept": null }
```
- `sources`는 LLM에 전달한 전체 근거이며 기존처럼 메시지에 저장한다.
- `display_sources`는 화면 표시용이다. `band=low`이면 빈 배열이며, 그 외에는 세션의 현재 개념 문서가 검색됐으면 점수와 무관하게 포함하고 다른 문서는 `DISPLAY_SOURCE_MIN_SCORE` 이상만 포함한다.
- **스트리밍 버전**: `POST /learning/messages/stream` (SSE). 마지막 이벤트로 위 메타데이터(답변 본문 제외)를 보낸다. 같은 서비스 함수를 공유한다.
- `notice`는 LLM 본문이 아니라 서버가 정한 화면 안내다. 검색 1위 extra/excluded는 그 용어의 term 또는
  aliases가 질문에 실제 포함될 때만 분류한다. 다른 스테이지 개념은 아직 통과하지 않은 가장 가까운
  다음 스테이지, 현재 스테이지 통과 개념은 복습, extra/excluded는 성장·퀴즈 미반영, low band는 사전
  근거 없는 답변임을 안내한다. 세션 중 다른 개념을 질문해도 같은 규칙을 적용하며 세션·상태는 유지한다.
- 현재 상태 조회: `GET /learning/current` → `{ mode, active_session, locked_concept, notice,
  complete_hint, learning_guide, status_labels, progress, quick_prompts }` (화면 진입·새로고침 시 사용). active 세션이
  없으면 `complete_hint`로 학습 시작 안내를 반환하며 `learning_guide`는 명시적 선택 규칙을 안내한다.

### 4.3 세션 정보
`GET /learning/sessions/{session_id}` → 세션 상태, 개념, attempt

### 4.4 학습 완료
`POST /learning/sessions/{session_id}/complete`
- 필수 헤더: `Idempotency-Key`. 같은 사용자와 같은 키의 재요청은 최초 응답을 그대로 반환한다.
- 세션 상태를 `completed` 로 바꾸고 학습 맥락(4.5와 같은 구조)을 생성·저장
- 개념 상태는 **바꾸지 않는다** (`in_progress` 그대로 퀴즈로 넘김). 통과 여부는 퀴즈 모듈이 결정한다.
- 관련 대화가 하나도 없으면 400 (최소 1턴 필요)
- 완료·맥락 저장·멱등 키 저장은 하나의 DB 트랜잭션에서 처리한다.
- `QuizService.create_quiz_set(...)`을 호출하고 응답 최상위에
  `"quiz": {"quiz_set_id": "...", "status": "pending|processing|completed|failed"}`를 포함한다.

### 4.5 학습 맥락 조회 (퀴즈 담당이 사용)
`GET /learning/sessions/{session_id}/learning-context`
```json
{ "session_id": "...", "user_id": "u1", "status": "completed",
  "concept": { "concept_id": "sisa_745", "term": "기회비용", "stage": "stage3",
               "status": "in_progress", "attempt": 1,
               "definition": "<Qdrant payload의 설명 본문>" },
  "turns": [ { "question": "...", "answer": "...", "is_related": true, "sources": ["sisa_745"], "created_at": "..." } ],
  "mentioned_concepts": [ { "concept_id": "sisa_960", "term": "디플레이션" } ],
  "reference_chunk_ids": ["sisa_745"],
  "completed_at": "..." }
```
- `turns`에는 세션의 관련·비관련 대화를 모두 포함하고 각 turn의 `is_related`로 핵심과 곁가지를 구분한다.
  세션 밖 free 메시지는 포함하지 않으며, 관련 대화가 하나도 없으면 완료 요청은 400이다.
- 퀴즈 모듈은 **`(concept.concept_id, concept.stage)`의 상태만** 갱신해야 한다. `mentioned_concepts`는
  세션의 모든 질문에서 수집하는 문제 구성 참고용이며 상태 갱신에 쓰지 않는다. 출제 중심은 처음 학습
  개념이고 `is_related`로 핵심 대화와 곁가지 대화를 구분한다 (3.5).
- `concept.status`는 학습 완료 시점의 스냅샷이다. 현재 상태는 학습 관리 모듈의 조회 결과가 기준이다.
- 퀴즈 모듈은 사용자 ID, 개념 ID(`concept_id`), 학습 맥락을 연결해 퀴즈를 저장한다. 같은 백엔드 안에서 쓰기 쉽도록 **API와 별개로 Python 함수** `get_learning_context(session_id)` 도 `service.py` 에서 공개한다.
- 본인 목록: `GET /learning/learning-contexts?status=completed`

### 4.6 대화 기록 조회 (화면 복원용)
- `GET /learning/sessions/{session_id}/messages` — 본인 세션의 전체 메시지 (관련 여부 무관), 타 사용자는 404
- `GET /learning/history?limit=50` — 세션 메시지와 `free` 메시지를 포함한 최신 N개를 고른 뒤 시간순 반환
- 각 메시지는 `role`, `content`, `is_related`, `band`, `display_sources`, `created_at`을 포함한다.

### 4.7 다른 모듈과의 연동 (인터페이스로 분리)

| 연동 대상 | 이 모듈에서의 형태 | 기본 구현 (통합 전) |
|---|---|---|
| 공통 인증 검증 (백엔드 공통) | FastAPI 의존성 `get_current_user_id()` 를 **주입받음** | 개발용: `X-User-Id` 헤더를 그대로 사용 (통합 시 공통 함수로 교체) |
| 개념 상태·현재 스테이지 (학습 관리) | SQL 기반 `ConceptStatusService`: 상태·진행률 조회, `mark_in_progress`, 확정 퀴즈 결과 반영, 이벤트 큐. 상태 키는 `(user_id, concept_id, stage)` | `CHAT_DB_URL`의 실제 테이블. `DEV_ENABLE_TOOLS`는 개발 라우트 등록만 제어 |
| 퀴즈 | 퀴즈 모듈이 4.5 API 또는 `get_learning_context()` 를 호출 | - |

- 통합 시 **구현체만 교체**하면 되도록, 라우터·서비스는 인터페이스에만 의존한다.
- `report_quiz_result(submission_id, session_id, concept_id, stage_id, correct_count, passed)`가 퀴즈→학습 관리 진입점이다. passed 판정은 퀴즈가 하고 상태·진행률·이벤트 반영은 학습 관리가 같은 트랜잭션에서 수행한다.
- 게임 모듈은 `get_unprocessed_events()`와 `mark_event_processed()`, 퀴즈 학습노트는 `get_concept_status()`를 사용하며 테이블을 직접 읽지 않는다.
- 이 모듈의 학습 관리 구현이 개념 통과·스테이지 완료를 감지해 `learning_events`를 발행한다.
  캐릭터 승급·보상 판정과 지급은 게임 모듈(김선빈)이 담당한다.

### 4.8 학습 진행률
`GET /learning/progress`는 현재 사용자의 `(concept_id, stage)` 상태만 집계한다.
- `current`: 현재 스테이지의 `stage_id`, `name_ko`, `total_count`, `passed_count`,
  `in_progress_count`, `not_started_count`, `remaining_count`, `percent`
- `stages`: Stage 1~5의 같은 필드와 `unlocked`, `completed`
- `percent = floor(passed_count / total_count * 100)`. 학습 중 개념은 퍼센트에 포함하지 않으며
  `remaining_count = total_count - passed_count`다.
- Stage 5의 겹치는 개념도 Stage 5 상태로 따로 세어 총 70개이며, `/learning/current.progress`에도 현재
  스테이지 요약을 포함한다.

---

## 5. 답변 생성 로직

### 5.1 처리 순서 (메시지 1건)
1. 사용자 상태 확인: active 세션, `in_progress` 개념, 현재 스테이지 (4.2의 분기)
2. 사용자 질문으로 Dense 검색 (k=5)
3. **개념 감지** (학습 중인 개념이 없을 때만)
   - 후보: 현재 스테이지의 `not_started` 개념
   - 다음 중 하나면 감지: ① 질문에 후보의 `term` 또는 `aliases` 가 포함됨(공백 무시) ② 검색 1위가 후보이고 점수 ≥ `BAND_HIGH`
   - 후보가 여러 개면 검색 순위가 가장 높은 개념 선택
   - 감지 규칙과 기준값은 **설정값으로 분리** (실사용 후 조정 예정)
4. **현재 개념 문서**를 concept_id로 Qdrant에서 조회 (세션이 있으면 항상 컨텍스트에 포함)
5. **신뢰 구간(band) 판정** — 검색 최고 점수 기준

| 최고 점수 | band | 처리 |
|---|---|---|
| ≥ 0.50 | `high` | 검색 결과 상위 3개를 근거로 답변 |
| 0.45 ~ 0.50 | `mid` | 검색 결과를 주되, 질문과 관련 있을 때만 사용하도록 프롬프트에서 지시 |
| < 0.45 | `low` | 검색 결과를 쓰지 않고 LLM 자체 지식으로 답변하고 서버 생성 `notice`로 범위 밖 안내 |

   - 검색 1위 extra/excluded 용어의 term/aliases가 질문에 포함되면 서버 생성 `notice`로 안내한다.
     excluded와 low 안내는 LLM 답변 본문에 넣지 않는다.
   - 임계값(0.50, 0.45)은 **설정값**으로 분리한다.
6. **현재 개념과의 관련성(is_related) 판정** (세션이 있을 때)
   - `keyword`/`detected`로 세션을 시작한 첫 메시지는 항상 `true`
   - `relearn`으로 시작한 첫 메시지는 일반 관련성 규칙으로 판정한다
   - 질문에 현재 개념의 `term`/`aliases` 가 포함되면 `true` (비교·연결 질문)
   - 질문에 다른 개념 용어만 있고 현재 개념 용어가 없으면 바로 `false`로 정하지 않는다. 현재 개념명과
     최근 1~2턴을 함께 주어 LLM yes/no 판정을 수행한다. 비교·연결이면 `true`, 독립 설명이면 `false`
   - 검색 상위 5개 안에 현재 개념 concept_id가 있으면 `true`
   - 아니면 경량 LLM 호출로 판정 ("이 질문이 '{term}' 학습과 관련 있는가? yes/no"), 판정 실패 시 `false`
   - 세션이 없는 `free` 메시지는 항상 `false`
7. LLM 답변 생성 (5.2 프롬프트)
8. 메시지 저장 (질문, 답변, session_id 또는 null, is_related, band, sources, 최고 점수, 지연 시간)

### 5.2 프롬프트 구성
- **system**
  - 역할: 경제 지식이 부족한 청년에게 경제 개념을 쉽게 설명하는 튜터
  - `CHAT_TONE=hao`면 조선시대 학당의 친절한 훈장이 설명하는 읽기 쉬운 하오체(`~이오`, `~하오`).
    어려운 옛말은 피하고 경제 용어·숫자·제도 이름은 현대어 그대로 두며 현대 생활 예시를 허용한다
  - `CHAT_TONE=modern`이면 현대 해요체(`~예요`, `~해요`). 한 답변 안에서 다른 종결형과 섞지 않는다
  - 범위 밖 안내와 재학습·퀴즈 대기 notice에도 같은 설정을 적용한다
  - 쉬운 말, 생활 속 예시 1개, 3~6문장 내외
  - 사실·숫자·정의는 제공된 사전 근거를 따르되 설명 방식과 문장 구성은 자유롭게 한다
  - 사전 문장을 그대로 옮기지 않고 `핵심 의미 → 왜 중요한지 → 학습자의 생활과의 연결` 순서로 재구성한다
  - 세부 숫자·유래·인물 이름은 사용자가 요구했거나 이해에 꼭 필요한 경우에만 포함한다
  - 일반적인 배경 지식은 이해를 돕는 범위에서 사용할 수 있으나 사전과 다른 사실·숫자를 지어내지 않는다
  - 근거를 사용했으면 마지막에 "출처: 시사경제용어사전" 표기
  - 현재 학습 개념: `{term}` — 관련 없는 질문에도 답하되 현재 개념으로 억지로 연결하지 않는다
  - 같은 세션에서 이미 설명한 내용은 한 문장 이하로 짧게 언급하고, 원인·영향·비슷한 개념과의 차이·적용 상황 등 새로운 각도로 설명한다. 같은 숫자·유래·예시는 반복하지 않는다
  - `attempt >= 2`면 이전 시도의 최근 대화를 참고해 다른 설명 순서·비유·예시를 사용한다
  - Stage 5면 기초 정의는 안다고 보고 TESAT·매경TEST 출제 포인트와 관련 개념 연결을 중심으로 설명한다
  - band 별 지시 (5.1 표)
- **context**: 현재 개념 정의 + 검색 근거(band에 따라) — 각 근거는 `[concept_id] term: text` 형식
- **history**: 같은 세션의 최근 6턴
- **user**: 현재 질문
- 프롬프트 템플릿은 `prompts.py` 한 곳에 모은다 (나중에 수정하기 쉽게).

---

## 6. 저장소 (대화 기록·학습 맥락)

- 팀의 일반 데이터 저장소는 **Supabase(PostgreSQL)** 이다. **SQLAlchemy** 로 구현해 `CHAT_DB_URL` 만 바꾸면
  로컬은 SQLite, 배포는 Supabase PostgreSQL에서 같은 코드로 동작하게 한다.
- `DB_AUTO_CREATE=true`인 로컬 환경에서만 SQLAlchemy 저장소가 시작 시 대화·학습 관리 테이블을
  자동 생성하고 `stages.json`을 멱등 시드한다. 코드 기본값은 `false`이며, 이때 스키마·시드를 변경하지
  않고 누락 시 migration 적용 안내와 함께 시작에 실패한다. 공유 Supabase는 검토된 001→002→003 SQL로 관리한다.
- 실제 상태는 `stages`, `concepts`, `user_concept_progress`, `user_stage_progress`, `learning_events`에
  저장한다. 이전 `dev_concept_status` 데이터는 보존 이전 후 제거한다. 현재 스테이지는 별도 저장하지 않는다.
- `ChatStore` 인터페이스를 두고 서비스는 인터페이스에만 의존한다.
- 테이블 (모든 테이블에 `user_id` 인덱스)
  - `learning_sessions`: session_id, user_id, stage, concept_id, term, attempt, start_type(`keyword`/`detected`/`relearn`/`quiz_retry`), status(`active`/`completed`), created_at, completed_at
  - `learning_messages`: message_id, session_id(free 메시지는 null), user_id, role, content, is_related, band, top_score, sources(JSON), display_sources(JSON), latency_ms, created_at
  - `learning_contexts`: session_id, user_id, concept_id, payload(JSON, 4.5 구조와 stage 포함), created_at. 유일한 상태 갱신 대상은 `(concept_id, stage)`
  - `learning_completion_requests`: user_id, session_id, idempotency_key, response_payload, created_at.
    같은 사용자의 완료 멱등 키를 유일하게 보장한다.
- 기존 로컬 SQLite의 `chat_sessions`/`chat_messages`는 시작 시 새 테이블명으로 보존 변경하고,
  `doc_id` 컬럼·JSON 키와 한국어 상태값도 각각 `concept_id`와 영문 상태 코드로 변환한다.
- DB는 사용자당 active `learning_sessions` 하나와 `user_concept_progress`의 `in_progress` 하나를
  각각 부분 유일 인덱스로 보장한다. 서비스 검증과 함께 여러 창의 동시 시작을 차단한다.
- 메모리 캐시만 쓰지 않는다. **새로고침·서버 재시작 후에도 대화 복원과 학습 맥락 조회가 가능해야 한다.**
- 모든 조회·수정은 **요청한 `user_id` 의 데이터로만** 제한한다 (각 모듈 담당의 사용자별 접근 제한 책임).

## 6.5 검색 소스 확장 구조 (지금 구현해 둘 것)

나중에 한국은행 용어집, 금감원 교재(PDF) 등을 **코드 수정 없이 설정 추가만으로** 붙일 수 있게 만든다.

- 검색 소스는 **컬렉션 단위**로 관리하고, 소스별 검색 설정을 `config.py` 의 `SEARCH_PROFILES` 한 곳에 둔다.
```python
SEARCH_PROFILES = {
    # 컬렉션명: 검색 설정
    "sisa_terms": {"mode": "dense", "k": 5, "slots": 3, "label": "시사경제용어사전",
                   "concept_source": True},   # 개념 감지·학습 개념은 이 소스에서만
    # 추후 예: "textbook_chunks": {"mode": "hybrid", "k": 5, "slots": 2, "label": "대학생을 위한 실용 금융", "concept_source": False},
}
```
- `retrieval.py` 는 `SEARCH_PROFILES` 를 순회하며 각 컬렉션을 **자기 mode로** 검색한다 (`rag_common.search` 재사용).
- 여러 소스 결과 합치기: 점수 범위가 mode마다 다르므로 점수를 직접 비교하지 않는다. 기본은 **자리 배분**(소스별 `slots` 개수만큼).
- **범위 밖 판별(band)** 은 `concept_source=True` 인 소스의 **Dense 최고 점수**로만 계산한다 (기준값 0.50/0.45가 이 기준으로 검증됨). 다른 소스가 hybrid여도 판별 기준은 바뀌지 않는다.
- **개념 감지·현재 개념 조회·관련성 판정**은 `concept_source=True` 소스만 사용한다.
- 응답의 `sources` 와 학습 맥락의 근거에는 **컬렉션명과 label** 을 함께 기록한다 (출처 표기·퀴즈 참고용).
- 현재는 `sisa_terms` 하나만 등록한다. 소스가 1개일 때도 같은 코드 경로로 동작해야 한다.

**소스 추가 시 작업 (README에 체크리스트로 적을 것)**
1. (데이터) 새 문서를 청크 JSONL로 만들고 `embed_and_upload.py --collection <새 컬렉션>` 으로 적재
2. (평가) 해당 소스용 골든셋으로 `eval_golden.py --collection <새 컬렉션>` 을 돌려 mode 결정
3. (챗봇) `SEARCH_PROFILES` 에 한 줄 추가 → 코드 수정 없음

**이미지 확장 대비 (지금은 구현하지 않음, 구조만 열어둘 것)**
- PDF 파싱 결과의 이미지는 데이터 단계에서 처리한다 (챗봇 코드 범위 아님)
  - 로컬 경로(`C:\Users\...`)는 DB에 절대 넣지 않는다 (다른 환경에서 열 수 없고 사용자명이 노출됨)
  - 장식용 이미지는 삭제, 그래프·표 등 내용 있는 이미지는 설명·OCR 텍스트를 청크 본문에 `[그림 설명] …` 형태로 삽입
  - 화면에 보여줄 이미지는 Supabase Storage에 업로드하고, URL을 payload의 `images` 필드(리스트)에 저장 (임베딩 텍스트에는 넣지 않음)
- 챗봇 쪽에서 지금 지킬 것
  - 응답 `sources` 항목 스키마에 **선택 필드 `images: list[str] | None = None`** 를 미리 정의해 둔다 (현재는 항상 비어 있음)
  - payload에 `images` 가 있으면 그대로 `sources` 에 실어 보내고, 없으면 생략한다
  - 이렇게 하면 나중에 이미지가 있는 소스를 추가해도 백엔드 코드 수정 없이 프론트 표시만 추가하면 된다

## 7. 구조와 설정

```
chatbot/
  __init__.py
  router.py        # APIRouter (prefix="/learning") — 엔드포인트만
  service.py       # 세션·메시지·완료 처리 (비즈니스 로직)
  retrieval.py     # rag_common 래핑: SEARCH_PROFILES 순회 검색·결합, 개념 조회(concept_id), band 판정
  relevance.py     # is_related 판정
  llm.py           # LLM 어댑터 (generate, stream) — 제공사 교체 가능하게
  prompts.py       # 프롬프트 템플릿
  store.py         # ChatStore 인터페이스 + SQLAlchemy 구현 (SQLite/PostgreSQL)
  integrations.py  # get_current_user_id, ConceptStatusService 인터페이스 + 개발용 구현
  concepts.py      # stages.json 로딩·추천
  schemas.py       # Pydantic 요청/응답 모델
  config.py        # 환경변수 설정 (pydantic-settings)
  deps.py          # 모델·클라이언트 싱글턴, FastAPI dependency
tests/
main_dev.py        # 단독 실행용 FastAPI 앱 (router만 include) — 통합 시 삭제 가능
README_chatbot.md  # 통합 방법, 환경변수, API 예시
```

**환경변수** (`.env`, 깃에 올리지 않음)
| 이름 | 예시 |
|---|---|
| `QDRANT_URL` | `https://xxxx.aws.cloud.qdrant.io:6333` |
| `QDRANT_API_KEY` | (비밀) |
| `QDRANT_COLLECTION` | `sisa_terms` |
| `DENSE_MODEL` | `nlpai-lab/KURE-v1` |
| `LLM_PROVIDER` / `LLM_MODEL` / `LLM_API_KEY` | (사용할 LLM에 맞게) |
| `LLM_REASONING_EFFORT` | 빈 값이면 파라미터 생략. 모델이 지원할 때만 `low` 등 지정 |
| `LLM_MAX_OUTPUT_TOKENS` | 답변 최대 출력 토큰 수 |
| `LLM_TEMPERATURE` | 기본 `0.7`, 범위 0~2. 답변 생성 모델이 지원할 때만 전달하고 추론 강도가 `none`이 아니면 생략 |
| `CHAT_TONE` | `hao`(기본, 학당 훈장 하오체) / `modern`(현대 해요체) |
| `ANSWER_KNOWLEDGE_MODE` | `dictionary_only`(기본) / `dictionary_plus` / `free` |
| `FREE_QUESTION_AUTO_START` | 기본 `false`. 자유 질문 자동 시작 호환 설정 |
| `BAND_HIGH` / `BAND_LOW` | `0.50` / `0.45` |
| `DISPLAY_SOURCE_MIN_SCORE` | `0.60` (현재 개념 외 화면 표시 출처의 최소 점수) |
| `STAGES_JSON_PATH` | `data/stages.json` |
| `CHAT_DB_URL` | 로컬 `sqlite:///chat.db` / 배포 Supabase PostgreSQL 연결 문자열 |
| `DB_AUTO_CREATE` | 코드 기본값 `false`. 로컬 예시는 `true`, 공유 Supabase는 `false` |
| `LLM_RELEVANCE_MODEL` | 미지정 시 `LLM_MODEL` 과 동일 |
| `DEV_ENABLE_TOOLS` | `true` / `false` (코드 기본값 `false`). 개발 API와 `/dev/chat` 등록 여부 |
| `DEV_SIMULATE_QUIZ_GENERATION_FAILURE` | `true` / `false` (코드 기본값 `false`). 개발 QuizService 생성 실패 시뮬레이션 |

**통합 방법 (README에 명시)**
```python
from chatbot.router import router as chat_router
from chatbot.errors import install_learning_error_handlers
app.include_router(chat_router)
install_learning_error_handlers(app)
```
- 시작 시 임베딩 모델·Qdrant 클라이언트를 로드하는 lifespan/startup 훅 사용법도 README에 적는다.

---

## 8. 작업 방식 (Cursor에게)

1. **먼저 구현 계획과 파일 구조를 제시하고 확인을 받은 뒤** 코드를 작성한다.
2. 아래 순서로 단계별 구현, 단계마다 테스트를 통과시킨 뒤 다음으로 넘어간다.
   1. `config`, `schemas`, `integrations`(인증·개념 상태 인터페이스 + 개발용 구현)
   2. `concepts` (추천 API: 일반/재학습 모드)
   3. `store` (SQLAlchemy) + 상태 조회(`/learning/current`)·세션 조회 API
   4. `retrieval` (concept_id 조회, 검색, band 판정)
   5. `llm`, `prompts`, `relevance`, 개념 감지 + 메시지 API (비스트리밍, 4.2의 분기 전체)
   6. 학습 완료·학습 맥락 API (+ `get_learning_context()` 함수)
   7. 스트리밍(SSE) API
   8. README, 통합 방법
3. **테스트**: Qdrant·LLM은 mock으로 단위 테스트, 실제 연결은 별도 통합 테스트(환경변수 있을 때만 실행).
4. **반드시 지킬 것**
   - `rag_common.py` 의 검색 로직 수정 금지
   - API 키를 코드·로그에 남기지 않기
   - 임베딩 모델은 프로세스당 한 번만 로드
   - 모르는 부분(LLM 제공사 등)은 임의로 정하지 말고 질문하거나 설정값으로 분리

---

## 9. 완료 기준

- [ ] stage1 `not_started` 개념 5개 추천 → 다음 5개 페이지네이션, `passed` 개념은 나오지 않음
- [ ] 키워드로 "분업/특화에 대해 알려줘" 전송 → 세션 시작, 상태 `not_started → in_progress`, 출처 표기된 쉬운 설명
- [ ] 키워드 없이 "워킹푸어가 뭐야?"(현재 스테이지 `not_started` 개념) → 세션과 상태는 그대로이고 `suggested_concept`와 학습 시작 notice 반환
- [ ] 다른 스테이지 개념·통과한 개념 질문 → 답변만, 세션·상태 변화 없음
- [ ] "오늘 날씨 어때?" → 자체 지식 답변 + 범위 밖 안내, `band=low`
- [ ] 학습 중 다른 개념 질문(예: 분업/특화 학습 중 "젠트리피케이션이 뭐야?") → 답변, `is_related=false`로 학습 맥락에 보존, 젠트리피케이션 상태는 `not_started` 그대로, 퀴즈·상태 갱신은 분업/특화 기준
- [ ] 학습 중 비교 질문(예: 인플레이션 학습 중 "디플레이션이랑 뭐가 달라?") → `is_related=true`, 학습 맥락에 포함, 디플레이션은 `mentioned_concepts` 참고 정보로 기록되고 상태 변화 없음
- [ ] 다른 개념 질문에도 거절 없이 쉬운 설명 제공
- [ ] 학습 완료 → 상태는 `in_progress` 그대로, 학습 맥락에 `status`, `attempt`, 세션 전체 대화와 각 turn의 `is_related` 포함. 같은 `Idempotency-Key` 재요청은 최초 결과 재반환
- [ ] `in_progress` 1개 상태(재학습 모드) → `/learning/current`가 `relearn`과 안내 문구 반환, 잠긴 `concept_id` 요청으로 `attempt=2` 세션 시작, 다른 키워드 선택 시 409
- [ ] 새로고침·서버 재시작 후 대화와 학습 맥락 복원
- [ ] 다른 사용자의 세션 조회 시 404
- [ ] 메시지마다 응답 지연 시간(ms) 기록
- [ ] payload에 `images` 가 있는 mock 문서가 검색되면 `sources[].images` 로 전달됨, 없으면 필드 생략
- [ ] `SEARCH_PROFILES` 에 테스트용 두 번째 컬렉션을 등록하면 코드 수정 없이 두 소스 결과가 자리 배분으로 합쳐짐 (mock 테스트)
- [ ] 퀴즈 통과 보고 → 해당 개념 `passed`, 이벤트 1회 기록, 남은 `not_started` 키워드 노출

---

## 10. 확정 사항 (구현 전 질문에 대한 답변, 위 내용과 충돌하면 이 절이 우선)

1. **LLM**: OpenAI API 사용. 모델명은 환경변수 `LLM_MODEL` 로 지정(경량 모델, 기본값은 현재 사용 가능한 OpenAI 경량 모델로 README에 명시). 관련성 판정은 `LLM_RELEVANCE_MODEL` (미지정 시 `LLM_MODEL` 과 동일). `llm.py` 는 제공사 교체가 가능한 어댑터 구조 유지.
2. **stages.json 경로**: 파일을 `data/stages.json` 으로 옮기고 설정 기본값도 그대로 둔다.
3. **별칭**: 요청마다 조회하지 않는다. **서버 시작 시 1회** stages.json의 모든 concept_id(고유 211개)에 대해 Qdrant payload(`term`, `aliases`, `text`)를 가져와 메모리에 캐시한다. Qdrant 포인트 ID는 `uuid5(NAMESPACE_URL, concept_id)`이므로 ID로 직접 조회 가능하다. 코드는 `concept_id`를 기준으로 하되 기존 Qdrant payload의 `doc_id` 읽기·필터 fallback을 유지한다.
4. **메시지 저장**: user/assistant **두 행**으로 저장. 응답의 `message_id` 는 assistant 행. `is_related`, `band`, `top_score`, `sources`, `latency_ms` 는 assistant 행에 저장. 학습 맥락은 user→assistant 쌍으로 묶어 만든다.
5. **SSE 형식**: `event: token` / `data: {"delta": "..."}`, 마지막 `event: done` / `data: {4.2 응답 메타데이터 + message_id}`, 실패 시 `event: error` / `data: {"code": "external_service_error", "message": "...", "request_id": "..."}`.
6. **실제 개념 상태**: `user_concept_progress(user_id, concept_id, stage_id)`를 사용하고 사용자당 `in_progress` 하나를 DB 부분 유일 제약으로 보장한다. 이전 SQLite `dev_concept_status`는 가능한 범위에서 보존 이전한 뒤 제거한다. 현재 스테이지는 상태로 계산한다.
7. **stage 입력 제거**: `GET /learning/concepts` 쿼리와 `POST /learning/messages` 본문에서 `stage`를 제거한다. 서버는 항상 `ConceptStatusService.get_current_stage()`가 반환한 스테이지로 추천·검증·학습을 수행한다.
8. **definition**: Qdrant `text` 에서 `설명:` 이하만 넣는다 (용어명·도메인은 별도 필드에 이미 있음).
9. **mentioned_concepts**: 세션의 모든 대화 질문에서 3번 캐시의 개념(stages.json 전체)의 `term`/`aliases`가 포함된 경우 기록한다. 현재 개념은 제외하고 검색 결과는 사용하지 않는다. 이는 참고 정보이며 출제·상태 갱신의 중심은 처음 학습 개념이다.
10. **퀴즈 대기 중 입력**: 학습 완료 후 퀴즈 결과가 나오기 전에는 재학습 세션을 열지 않는다.
    - `learning_contexts` 에 `quiz_status`(`pending`/`passed`/`failed`) 추가, 기본 `pending`
    - `report_quiz_result(submission_id, session_id, concept_id, stage_id, correct_count, passed)`와 `POST /learning/sessions/{id}/quiz-result`를 제공한다. 학습 관리는 같은 트랜잭션에서 퀴즈 상태, 개념 상태, 진행률, 이벤트를 반영한다.
    - `pending` 동안 `/learning/current`의 `mode`는 `quiz_pending`, 메시지는 **세션 없이 답변만**(free) 처리
    - `failed`가 기록된 뒤 잠긴 `concept_id`가 포함된 요청으로 재학습 세션(`attempt+1`) 시작
11. **Stage 5 학습**: Stage 1~4가 모두 통과되면 상태 기반 계산 결과가 Stage 5가 된다. 겹치는 개념을 포함한 70개 전체를 심화 버전으로 다시 학습하며 상태, `in_progress` 잠금, 최신 퀴즈, attempt는 모두 `(concept_id, stage)` 기준이다. Stage 5까지 모두 통과해도 현재 스테이지 값은 Stage 5를 유지한다. Stage 5 프롬프트는 기초를 안다고 보고 TESAT·매경TEST 출제 포인트와 관련 개념 연결을 강조한다. 학습 관리는 Stage 5 완료 이벤트를 기록하고 캐릭터 승급·보상 판정은 게임 모듈이 담당한다.
12. **재학습 첫 메시지 관련성**: 재학습 모드에서는 잠긴 `concept_id`가 포함된 첫 요청으로 새 세션을 시작하지만, `is_related`는 일반 관련성 규칙으로 판정한다. "첫 메시지는 항상 true" 규칙은 `keyword`/`detected` 시작에만 적용한다.
13. **LLM 필수 설정**: `LLM_MODEL`은 코드 기본값을 두지 않으며, 미지정 시 시작 단계에서 명확한 설정 오류로 실패한다. 권장 모델과 확인 방법은 README에만 기록한다.
14. **추론 강도**: `LLM_REASONING_EFFORT`의 코드 기본값은 빈 값이며, 빈 값이면 OpenAI 요청에서 `reasoning` 파라미터를 생략한다. `.env.example`에는 `low` 예시와 모델 미지원 시 비우라는 주석을 둔다.
15. **low band 근거**: `band=low`이면 응답 `sources`는 빈 배열이다. `band`와 `top_score`는 유지하며, 검색 결과는 답변 근거로 사용하지 않는다.
16. **외부 호출 실패의 원자성**: 완성된 user/assistant 쌍만 저장한다. Qdrant 또는 LLM 호출 실패는 HTTP 502로 반환하고 메시지를 저장하지 않는다. 새 세션 생성과 `mark_in_progress()`는 LLM 답변 생성이 성공한 뒤에만 실행해 외부 호출 실패 시 세션·개념 상태가 바뀌지 않게 한다.
17. **화면 표시용 출처**: 메시지 응답에 `display_sources`를 추가한다. `sources`는 LLM에 전달한 전체 근거로 유지하고, 화면 복원을 위해 `display_sources`도 별도 저장한다. `band=low`이면 `display_sources=[]`이며, 그 외에는 현재 세션 개념 문서가 검색됐으면 항상 포함하고 다른 문서는 `DISPLAY_SOURCE_MIN_SCORE`(기본 `0.60`) 이상만 포함한다.
18. **임베딩 의존성 고정**: `rag_common.py`는 수정하지 않고, 새 환경에서도 현재 검증된 조합이 재현되도록 `sentence-transformers==6.1.0`으로 고정한다.
19. **퀴즈 결과 단일 기록**: `quiz-result`는 완료되어 학습 맥락의 `quiz_status`가 `pending`인 세션에만 허용한다. active 세션이나 이미 `passed`/`failed` 결과가 기록된 세션은 409로 거절하며 기존 결과를 덮어쓰지 않는다.
20. **SSE 원자성**: 비스트리밍과 스트리밍은 같은 메시지 준비·분기·검증·저장 함수를 공유한다. 스트리밍 중 LLM 오류가 나면 `error` 이벤트로 끝내고, 클라이언트가 중간에 연결을 끊으면 이벤트 생성을 중단한다. 두 경우 모두 메시지 저장, 세션 생성, `mark_in_progress()`를 수행하지 않는다. 모델 스트림이 끝까지 성공하고 연결이 유지된 경우에만 상태를 반영한 뒤 `done`을 보내며, `done` 메타데이터에는 `display_sources`를 포함한다.
21. **Supabase 배포 준비**: PostgreSQL은 psycopg 3 드라이버를 사용한다. `DB_AUTO_CREATE` 코드 기본값은 `false`이며, 이때 테이블이나 `stages`/`concepts` 시드가 없으면 migration SQL을 먼저 적용하라는 오류로 시작에 실패한다. 로컬 예시만 `true`로 두어 `create_all`과 시드를 허용한다. 공유 Supabase는 팀 검토 후 `001_learning_management.sql` → `002_enable_rls.sql` → `003_seed_stages_concepts.sql` 순으로 적용한다. 002는 이 모듈의 모든 테이블에 정책 없는 RLS를 켠다. Session pooler 연결 문자열을 권장하고 비밀번호 예약 문자를 URL 인코딩하며, `user_id`는 Supabase Auth 사용자 UUID를 사용한다.
22. **대화 기록 복원**: 세션 메시지 API는 본인의 관련·비관련 메시지 전체를 반환하고 타 사용자 요청은 404다. 최근 기록 API는 세션과 free 메시지를 합친 최신 N개를 시간순으로 반환한다. 각 항목은 화면 복원용 `display_sources`를 포함한다.
23. **비교 질문 관련성**: 다른 개념명만 포함된 질문도 현재 개념명과 최근 1~2턴을 함께 넣어 LLM으로 판정한다. 비교·대조·인과·연결 질문은 관련, 독립 설명 질문은 비관련이다. 판정과 무관하게 다른 개념 상태는 바꾸지 않는다.
24. **설명 다양화**: 같은 세션에서는 이전 답변의 예시를 반복하지 않는다. `attempt >= 2`면 이전 시도의 최근 대화를 프롬프트에 포함하고 다른 설명 방식과 예시를 요구한다.
25. **학습 상태 스냅샷**: 학습 맥락의 `concept.status`는 완료 시점 스냅샷이다. 현재 상태는 학습 관리 모듈을 기준으로 하며 퀴즈 상태 갱신 대상은 `(concept.concept_id, concept.stage)` 하나뿐이다.
26. **개발용 수동 테스트 도구**: `DEV_ENABLE_TOOLS=true`인 `main_dev.py` 앱에서만 `/learning/dev/*`와 `/dev/chat`을 등록한다. `POST /learning/dev/stage`는 지정 단계 이전 스테이지를 모두 통과 처리하고, `POST /learning/dev/pass-all`은 현재 스테이지 전체를 통과 처리한다. 상태 조회와 사용자별 로컬 개념 상태·세션·메시지·학습 맥락 초기화도 제공한다. 초기화는 다른 사용자의 데이터를 건드리지 않으며 전부 `not_started`가 되어 현재 스테이지가 Stage 1로 계산된다. `DEV_ENABLE_TOOLS=false`이면 엔드포인트가 403을 반환하는 방식이 아니라 라우트 자체가 없어야 한다.
27. **현재 스테이지 계산**: `ConceptStatusService.get_current_stage()`는 `get_statuses()`를 이용해 `not_started` 또는 `in_progress`가 남은 가장 낮은 스테이지를 반환하는 기본 구현을 가진다. 순서는 Stage 1→2→3→4→5이며, Stage 1~4가 모두 `passed`면 Stage 5, Stage 5까지 모두 `passed`여도 Stage 5다.
28. **서비스 말투**: `CHAT_TONE`은 `hao`(기본) 또는 `modern`이다. `hao`는 친절한 학당 훈장의 읽기 쉬운 하오체를 사용하되 경제 용어·숫자·제도 이름과 현대 생활 예시는 현대 표현을 유지한다. `modern`은 해요체를 사용한다. 모든 답변과 범위 밖·재학습·퀴즈 대기 안내는 선택한 말투를 일관되게 사용한다.
29. **설명 재구성**: 사실·숫자·정의는 사전 근거를 따르되 사전 문장을 그대로 옮기지 않는다. 핵심 의미, 중요성, 학습자 생활과의 연결 순서로 자유롭게 설명하며 세부 숫자·유래·인물은 질문이 요구할 때만 쓴다. 일반 배경 지식은 허용하되 근거와 다른 사실·숫자를 만들지 않는다. 같은 세션의 기존 설명은 짧게 언급하고 원인·영향·유사 개념과의 차이·적용 상황 가운데 새로운 각도를 택하며 숫자·유래·예시를 반복하지 않는다.
30. **temperature**: `LLM_TEMPERATURE`의 코드 기본값은 `0.7`이고 허용 범위는 0~2다. 답변 생성에만 적용하며 관련성 yes/no 판정에는 적용하지 않는다. 모델이 지원하지 않거나 `LLM_REASONING_EFFORT`가 `none`이 아니면 OpenAI 요청에서 파라미터를 생략한다. GPT-5 이상 추론 모델은 `reasoning.effort=none`을 명시한 경우에만 전달하고 `o1`/`o3`/`o4` 계열에는 전달하지 않는다.
31. **학습 맥락 전체 대화**: 완료 맥락의 `turns`에는 해당 세션의 완성된 user/assistant 쌍을 관련 여부와 무관하게 모두 넣고 각 turn에 `is_related`를 표시한다. `mentioned_concepts`도 세션 전체 질문에서 수집한다. free 메시지는 제외하며 관련 turn이 하나도 없으면 완료 400을 유지한다. 상태 갱신 대상은 처음 개념의 `(concept_id, stage)` 하나뿐이다.
32. **메시지 안내 분리**: 비스트리밍 응답과 SSE `done`에 nullable `notice`를 둔다. 다른 스테이지·이미 통과·extra·excluded·low band 안내는 서버가 `CHAT_TONE`에 맞게 생성하며 LLM 본문에 넣지 않는다. extra/excluded는 검색 1위의 term 또는 aliases가 질문에 실제 포함된 경우만 적용한다. 세션 중 다른 개념 질문에도 적용하되 세션과 상태는 바꾸지 않는다. `/learning/current.complete_hint`는 active 세션이 없을 때 학습 시작 안내를 제공한다.
33. **학습 진행률**: `GET /learning/progress`와 `/learning/current.progress`를 제공한다. 스테이지별 `passed`·`in_progress`·`not_started` 수를 `(concept_id, stage)`로 집계하고 퍼센트는 `passed` 수만 사용해 소수점 이하를 버린다. Stage 5는 겹치는 개념을 포함한 70개를 별도로 센다.
34. **상태 코드와 표시 문구**: 개념 상태의 DB·API·테스트 값은 `not_started`/`in_progress`/`passed`다. 화면 문구는 `미학습`/`학습중`/`통과`로 확정하며 `/learning/current.status_labels`에 같은 값을 반환한다. `quiz_status="failed"`는 그대로 유지한다.
35. **ID와 경로 통일**: 애플리케이션·DB·stages.json은 `concept_id`를 사용하고 메시지 요청도 `concept_id`를 받는다. API prefix는 `/learning`이며 상태는 `/learning/current`, 목록 연동은 `/learning/learning-contexts`, 퀴즈 결과는 `/learning/sessions/{id}/quiz-result`다. 기존 `/chat/*`는 제공하지 않는다.
36. **명시적 학습 시작**: `FREE_QUESTION_AUTO_START=false`가 기본이며 자유 질문은 현재 단계 개념을 감지해도 세션·상태를 바꾸지 않는다. 대신 서버 notice와 `suggested_concept`를 반환하고 프론트가 학습 시작 버튼을 표시한다. 키워드·제안·재학습 모두 `concept_id`가 포함된 요청에서만 시작한다. 상태 응답은 `learning_guide`를 제공한다.
37. **학습 완료 멱등성**: 완료 API는 `Idempotency-Key` 헤더를 필수로 받고 같은 키에 최초 학습 맥락과 `quiz {quiz_set_id,status}` 응답을 재반환한다. 완료 시 QuizService로 퀴즈 생성을 요청한다.
38. **오류·시간·로그 계약**: HTTP JSON 오류와 SSE 오류는 `{code, message, request_id}`를 사용하고 모든 HTTP 응답에 `X-Request-ID`를 포함한다. 모든 시간은 UTC ISO 8601이며 로그에는 토큰·비밀번호·요청 본문을 남기지 않는다.
39. **동시 학습 차단**: DB는 사용자당 active 학습 세션 하나와 `in_progress` 개념 하나를 각각 부분 유일 제약으로 보장한다. 애플리케이션 검증만으로 동시 창 경쟁을 처리하지 않는다.
40. **학습 관리 테이블**: `stages`, `concepts`, `user_concept_progress`, `user_stage_progress`, `learning_events`를 실제 SQLAlchemy 모델과 migration SQL로 관리한다. `quiz_result_receipts`, `quiz_retry_requests`는 학습 관리 내부 멱등 테이블이며 다른 모듈은 사용하지 않는다.
41. **스테이지 진행**: `user_stage_progress.status`는 `in_progress`/`completed`다. 행이 없으면 잠김이지만 Stage 1은 행 없이도 열려 있고 첫 학습 시작 시 행을 만든다. 이전 단계 completed가 다음 단계를 열며 Stage 5 완료의 next_stage_id는 null이다.
42. **퀴즈 생성**: 완료 시 `QuizService.create_quiz_set(user_id, session_id, concept_id, stage_id, learning_context, reference_chunk_ids)`를 호출한다. 같은 session_id는 기존 세트를 반환하고 완료 응답에 `quiz` 객체를 포함한다.
43. **퀴즈 생성 실패·재요청**: 생성 실패는 `quiz_status=generation_failed`, 개념 `in_progress`, mode `quiz_generation_failed`다. `/learning/sessions/{id}/quiz-retry`는 Idempotency-Key를 받고 같은 맥락·concept·stage·attempt의 새 `quiz_retry` 완료 세션으로 재요청하며 메시지는 복사하지 않는다.
44. **이벤트 연동**: 이 모듈은 passed 결과를 `concept_passed`, 마지막 개념이면 `stage_completed` 이벤트까지 상태 변경과 같은 트랜잭션에 기록한다. 게임 모듈(김선빈)은 `get_unprocessed_events()`와 `mark_event_processed()`를 사용해 승급·보상을 판정한다.
45. **개발 플래그**: `DEV_ENABLE_TOOLS`는 개발 API와 `/dev/chat` 등록만 제어한다. 이전 `DEV_USE_LOCAL_STATUS`가 남으면 이름 변경 경고를 기록한다. `DEV_SIMULATE_QUIZ_GENERATION_FAILURE`는 개발 QuizService 실패 시뮬레이션이다.
46. **학습 중 화면**: active 세션 또는 `in_progress` 개념이 있으면 다른 키워드를 비활성화하고 `/learning/current.quick_prompts`를 입력 보조로 제공한다. 개념 칩 클릭은 첫 prompt를 입력할 뿐 자동 전송하지 않는다.
47. **답변 지식 범위**: `ANSWER_KNOWLEDGE_MODE`는 `dictionary_only`(기본, 기존 사전 중심 프롬프트), `dictionary_plus`(핵심 정의·사실은 사전과 일치시키고 배경·이유·생활 사례·관련 개념은 일반 경제 지식으로 보충), `free`(사전은 참고하되 퀴즈 기준 핵심 정의와 충돌하지 않게 자유 설명)다. 후자의 두 모드는 단순 질문은 3~5문장, 상세·이유·예시 요청은 더 길게 답한다. 근거 없는 구체적 숫자·날짜·최신 통계·특정 기업·인물 사례는 만들지 않는다.
48. **지식 모드별 출처**: `dictionary_plus`는 `핵심 정의 출처: 시사경제용어사전`을 표시하고 일반 지식 보충이 있으면 `CHAT_TONE`에 맞는 보충 안내를 붙인다. `free`는 사전을 실제로 인용하거나 근거로 사용한 경우에만 출처를 표시한다. `dictionary_only`의 기존 출처 동작은 유지한다.
