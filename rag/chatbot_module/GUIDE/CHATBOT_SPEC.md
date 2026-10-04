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
1. 현재 스테이지의 **미학습** 개념을 5개씩 추천 (미통과 개념이 있으면 재학습 모드)
2. 키워드 선택 또는 **자유 질문에서 현재 스테이지 개념을 감지**해 학습 세션 시작, 개념 상태를 `미학습 → 미통과` 로 변경
3. 질문에 대한 RAG 답변 생성
4. 대화 기록 저장 (현재 개념과 관련 있는 대화인지 표시)
5. "학습 완료" 시 **개념 상태(미통과)와 학습 맥락**을 퀴즈 모듈에 전달할 수 있도록 저장·제공

**이 모듈이 하지 않는 일 (다른 담당)**
- 퀴즈 생성·채점·통과 판정 (개념당 3문제: OX 2 + 상황형 4지선다 1, 2문제 이상 정답 시 통과) → 퀴즈 담당이 4.5의 학습 맥락을 사용
- `미통과 → 통과` 또는 `미통과 유지` 결정 (퀴즈 모듈), 스테이지 개방, 학습노트, 캐릭터·엽전 (학습 관리·게임 모듈)
- 로그인 화면·토큰 발급 (Supabase Auth) → 공통 인증 검증 함수를 **주입받아 사용**만 한다 (4.7 참고)
- 사전테스트 (사전테스트 개념셋은 학습 개념셋과 별개)

## 2. 이미 준비된 자산 (수정 금지, 재사용)

| 자산 | 내용 |
|---|---|
| `rag_common.py` | Dense 인코더(`DenseEncoder`), 검색 함수(`search`), 스테이지 필터(`stage_filter`). **검색 로직은 수정하지 말고 import 해서 사용** |
| `stages.json` | 스테이지별 학습 개념 목록 (순서·소분류·doc_id·용어) |
| Qdrant Cloud | 컬렉션 `sisa_terms`, 포인트 3,029건 (시사경제용어사전) |

### 2.1 Qdrant 컬렉션 `sisa_terms`
- 벡터: `dense` (nlpai-lab/KURE-v1, 1024차원, Cosine), `sparse` (Kiwi+BM25, **사용하지 않음**)
- payload 필드

| 필드 | 예시 | 비고 |
|---|---|---|
| `doc_id` | `sisa_745` | 개념 식별자 |
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
    "concepts": [ { "order": 1, "subcategory": "경제 기본", "doc_id": "sisa_1281",
                    "term": "분업/특화", "term_full": "분업/특화", "other_stages": [] } ] } ] }
```

---

## 3. 사용자 흐름

### 3.1 개념 상태와 상태 변경 주체
| 상태 | 의미 | 바꾸는 주체 |
|---|---|---|
| `미학습` | 아직 학습을 시작하지 않음 | - |
| `미통과` | 학습을 시작했거나 퀴즈에서 떨어짐 (사용자당 **항상 0개 또는 1개**) | **챗봇** (`미학습 → 미통과`) |
| `통과` | 퀴즈 3문제 중 2문제 이상 정답 | **퀴즈** (`미통과 → 통과`, 또는 `미통과` 유지) |

- 스테이지는 사용자가 고르지 않고 시스템이 정한 순서대로 진행한다. Stage 5는 선택형 과정이다.
- `통과` 한 개념은 다시 추천하지 않는다.

### 3.2 학습 시작: 두 가지 경로
학습 중인 개념이 없을 때(미통과 0개), 아래 둘 중 하나로 학습이 시작된다.
1. **키워드 선택**: 하단에 현재 스테이지의 `미학습` 개념 5개가 버튼으로 노출된다. 누르면 입력창에 `{term}에 대해 알려줘` 가 자동 입력되고(**자동 전송 안 함**), 사용자가 전송하면 학습 시작.
2. **자유 질문**: 사용자가 직접 입력한 질문이 **현재 스테이지의 `미학습` 개념**에 해당하면(감지 규칙은 5.1) 그 개념으로 학습 시작.

학습이 시작되면 세션이 만들어지고, 개념 상태를 `미학습 → 미통과` 로 바꾼다.
- 자유 질문이 다른 스테이지 개념이거나, 이미 `통과` 한 개념이거나, 경제 용어가 아니면 **답변만** 하고 학습을 시작하지 않는다.

### 3.3 학습 중
- 추가 질문으로 개념을 더 학습한다.
  - 현재 개념과 **관련 있는 질문**: 답변 + 학습 맥락에 포함
  - **관련 없는 질문**(현재 스테이지의 다른 개념 포함): 답변만 제공, 학습 맥락에서 제외, 상태 변경 없음
- **"학습 완료" 버튼**을 누르면 세션이 종료되고, `미통과` 상태와 관련 대화만 모은 **학습 맥락**이 퀴즈로 전달된다.
- 퀴즈 결과로 `통과` 가 되면 현재 스테이지의 남은 `미학습` 키워드가 다시 노출된다.

### 3.4 재학습 모드 (퀴즈 후에도 미통과 1개)
- 미통과 개념을 먼저 해결하도록 **UI를 강제**한다.
  - 키워드 버튼 비활성화
  - 상단 안내: `현재 미통과인 {term} 개념 학습중입니다. 통과해야 다음 개념을 넘어갈 수 있습니다.`
- 이 상태에서 보내는 첫 메시지로 미통과 개념의 **새 세션**(재학습, `attempt` 증가)이 자동 시작된다. 입력창에는 `{term}에 대해 다시 알려줘` 를 자동 입력할 수 있다.
- 자유 질문이 현재 스테이지의 다른 개념이어도 **새 학습을 시작하지 않고 답변만** 한다.
- 학습 완료 시 다시 `미통과` 상태와 새 세션의 학습 맥락을 퀴즈로 전달 → 퀴즈가 `통과` 또는 `미통과 유지` 결정.

### 3.5 개념 고정 원칙 (중요)
- 세션은 **처음 학습을 시작한 개념 하나에 고정**된다.
- **DB 갱신은 처음 개념에만** 한다. 세션 도중 다른 개념이 언급되거나 질문돼도
  - 새 세션을 시작하지 않는다
  - 그 개념의 상태를 **절대 바꾸지 않는다** (`미학습`·`미통과`·`통과` 모두 그대로)
  - 퀴즈 결과(통과/미통과)도 **처음 개념에만** 반영된다 → 학습 맥락의 `concept.doc_id` 가 유일한 갱신 대상
  - 이유: 다른 개념은 한두 번 설명을 들었을 뿐 제대로 이해했는지 알 수 없고, 상태가 여러 개념에 퍼지면 꼬인다
- **설명은 항상 제대로 한다.** 다른 개념 질문이라도 "지금은 OO을 학습 중이라 답할 수 없다"며 거절하지 않고, 쉬운 설명을 똑같이 제공한다.
- 학습 맥락(퀴즈 재료)에는
  - 처음 개념과 **비교·연결하는 대화**(예: 인플레이션 학습 중 "디플레이션이랑 뭐가 달라?")는 포함한다 → 퀴즈에 다른 개념 내용이 섞여도 괜찮다
  - 다른 개념**만** 묻는 대화는 제외한다
  - 언급된 다른 개념은 `mentioned_concepts` 에 **참고용**으로만 기록한다 (상태 갱신 대상 아님)
- 새 개념을 정식으로 학습하려면 현재 개념을 통과한 뒤, 다음 학습에서 시작한다.

## 4. API 명세 (prefix: `/chat`)

> 모든 API는 공통 인증 의존성에서 받은 `user_id` 로 동작한다. 요청 본문으로 `user_id` 를 받지 않는다.
> 다른 사용자의 세션에 접근하면 **404** (존재 여부를 노출하지 않음).

### 4.1 개념 추천
`GET /chat/concepts?offset=0&limit=5`  (Stage 5 학습 시에만 `stage=stage5` 지정 가능)
- 현재 스테이지(학습 관리 모듈 제공)의 개념 중 **`미학습` 상태만** `order` 순으로 반환
- 응답
```json
{ "mode": "normal",
  "stage": { "id": "stage1", "name_ko": "사회경제현상과 소비생활" },
  "concepts": [ { "doc_id": "sisa_1281", "term": "분업/특화", "term_full": "분업/특화", "subcategory": "경제 기본", "order": 1 } ],
  "next_offset": 5, "has_more": true,
  "locked_concept": null, "notice": null }
```
- 미통과 개념이 있으면 `"mode": "relearn"`, `locked_concept` 에 해당 개념, `notice` 에 3.4의 안내 문구, `suggested_message` 에 `{term}에 대해 다시 알려줘` 를 넣는다. 이때 `concepts` 는 화면 표시용으로만 내려주고 프론트에서 비활성화한다.

### 4.2 메시지 전송 (단일 진입점)
`POST /chat/messages`
- 요청: `{ "message": "분업/특화에 대해 알려줘", "selected_doc_id": "sisa_1281", "stage": "stage5" }`
  - `selected_doc_id`: 키워드 버튼으로 입력된 경우에만 프론트가 함께 보낸다 (선택). 자유 질문이면 생략.
  - `stage`: `stage5` 키워드 버튼으로 선택한 경우에만 `"stage5"`를 보낸다. 다른 값은 허용하지 않는다.
- 서버 처리 순서
  1. **진행 중(active) 세션이 있으면** 그 세션에 메시지를 추가한다 (관련성 판정 5.1).
  2. **재학습 모드**(미통과 1개, active 세션 없음)면 미통과 개념으로 새 세션(`attempt+1`)을 시작한다.
  3. `selected_doc_id` 가 있으면: 현재 스테이지의 `미학습` 개념인지 검증 후 세션 시작. 아니면 409.
  4. 자유 질문이면: **개념 감지**(5.1) → 현재 스테이지 `미학습` 개념이 감지되면 세션 시작.
  5. 위에 해당하지 않으면 세션 없이 **답변만** 하고, 기록은 `free` 메시지로 저장한다 (퀴즈와 무관).
  - 세션을 새로 시작할 때 `ConceptStatusService.mark_failed()` 로 상태를 `미학습 → 미통과` 로 바꾼다.
- 응답
```json
{ "answer": "...", "session_id": "...또는 null", "session_started": true,
  "concept": { "doc_id": "sisa_1281", "term": "분업/특화", "stage": "stage1", "status": "미통과", "attempt": 1 },
  "is_related": true, "band": "high", "top_score": 0.71,
  "sources": [ { "doc_id": "sisa_1281", "term": "분업/특화", "score": 0.71 } ],
  "display_sources": [ { "doc_id": "sisa_1281", "term": "분업/특화", "score": 0.71 } ],
  "message_id": "..." }
```
- `sources`는 LLM에 전달한 전체 근거이며 기존처럼 메시지에 저장한다.
- `display_sources`는 화면 표시용이다. `band=low`이면 빈 배열이며, 그 외에는 세션의 현재 개념 문서가 검색됐으면 점수와 무관하게 포함하고 다른 문서는 `DISPLAY_SOURCE_MIN_SCORE` 이상만 포함한다.
- **스트리밍 버전**: `POST /chat/messages/stream` (SSE). 마지막 이벤트로 위 메타데이터(답변 본문 제외)를 보낸다. 같은 서비스 함수를 공유한다.
- 현재 상태 조회: `GET /chat/state` → `{ mode, active_session, locked_concept, notice }` (화면 진입·새로고침 시 사용)

### 4.3 세션 정보
`GET /chat/sessions/{session_id}` → 세션 상태, 개념, attempt

### 4.4 학습 완료
`POST /chat/sessions/{session_id}/complete`
- 세션 상태를 `completed` 로 바꾸고 학습 맥락(4.5와 같은 구조)을 생성·저장
- 개념 상태는 **바꾸지 않는다** (`미통과` 그대로 퀴즈로 넘김). 통과 여부는 퀴즈 모듈이 결정한다.
- 관련 대화가 하나도 없으면 400 (최소 1턴 필요)

### 4.5 학습 맥락 조회 (퀴즈 담당이 사용)
`GET /chat/sessions/{session_id}/learning-context`
```json
{ "session_id": "...", "user_id": "u1", "status": "completed",
  "concept": { "doc_id": "sisa_745", "term": "기회비용", "stage": "stage3",
               "status": "미통과", "attempt": 1,
               "definition": "<Qdrant payload의 설명 본문>" },
  "turns": [ { "question": "...", "answer": "...", "sources": ["sisa_745"], "created_at": "..." } ],
  "mentioned_concepts": [ { "doc_id": "sisa_960", "term": "디플레이션" } ],
  "completed_at": "..." }
```
- `turns` 에는 **`is_related = true` 인 대화만** 포함한다.
- 퀴즈 모듈은 **`concept.doc_id` 의 상태만** 갱신해야 한다. `mentioned_concepts` 는 문제 출제 참고용이며 상태 갱신에 쓰지 않는다 (3.5).
- 퀴즈 모듈은 사용자 ID, 개념 ID(`doc_id`), 학습 맥락을 연결해 퀴즈를 저장한다. 같은 백엔드 안에서 쓰기 쉽도록 **API와 별개로 Python 함수** `get_learning_context(session_id)` 도 `service.py` 에서 공개한다.
- 본인 목록: `GET /chat/learning-contexts?status=completed`

### 4.6 대화 기록 조회 (화면 복원용)
- `GET /chat/sessions/{session_id}/messages` — 세션의 전체 메시지 (관련 여부 무관)
- `GET /chat/history?limit=50` — 세션 밖 `free` 메시지를 포함한 최근 대화 (채팅창 복원용)

### 4.7 다른 모듈과의 연동 (인터페이스로 분리)

| 연동 대상 | 이 모듈에서의 형태 | 기본 구현 (통합 전) |
|---|---|---|
| 공통 인증 검증 (백엔드 공통) | FastAPI 의존성 `get_current_user_id()` 를 **주입받음** | 개발용: `X-User-Id` 헤더를 그대로 사용 (통합 시 공통 함수로 교체) |
| 개념 상태·현재 스테이지 (학습 관리) | `ConceptStatusService` 인터페이스: `get_current_stage(user_id)`, `get_statuses(user_id, stage)`, `get_failed_concept(user_id)`, `mark_failed(user_id, doc_id, stage=None)` (챗봇은 `미학습 → 미통과` 만 변경). `stage`는 Stage 5 명시 선택에만 사용한다. `note_quiz_result(user_id, doc_id, passed)` 는 기본 구현이 no-op | `DEV_USE_LOCAL_STATUS=true`일 때만 개발용 SQLite (`dev_concept_status`, `dev_user_stage`). stage1, 전부 미학습에서 시작. 재시작 후에도 유지 |
| 퀴즈 | 퀴즈 모듈이 4.5 API 또는 `get_learning_context()` 를 호출 | - |

- 통합 시 **구현체만 교체**하면 되도록, 라우터·서비스는 인터페이스에만 의존한다.
- 개념 상태를 실제로 어느 테이블에서 관리하는지는 학습 관리 담당과 확정 후 반영한다 (**미확정**).
- `service.report_quiz_result()` 는 `quiz_status` 만 갱신한 뒤 `note_quiz_result()` 를 호출한다. 서비스 코드는 개념 상태를 직접 바꾸지 않는다.
- 개발용 SQLite 구현만 `DEV_SIMULATE_QUIZ_STATUS=true` 이고 `passed=True` 이며 현재 상태가 `미통과`일 때 그 개념을 `통과`로 바꾼다. 설정이 꺼져 있거나 다른 구현체이면 개념 상태는 그대로다. 퀴즈 모듈이 없는 동안 통과 후 다음 키워드가 노출되는 흐름을 확인하기 위한 훅이다.

---

## 5. 답변 생성 로직

### 5.1 처리 순서 (메시지 1건)
1. 사용자 상태 확인: active 세션, 미통과 개념, 현재 스테이지 (4.2의 분기)
2. 사용자 질문으로 Dense 검색 (k=5)
3. **개념 감지** (학습 중인 개념이 없을 때만)
   - 후보: 현재 스테이지의 `미학습` 개념
   - 다음 중 하나면 감지: ① 질문에 후보의 `term` 또는 `aliases` 가 포함됨(공백 무시) ② 검색 1위가 후보이고 점수 ≥ `BAND_HIGH`
   - 후보가 여러 개면 검색 순위가 가장 높은 개념 선택
   - 감지 규칙과 기준값은 **설정값으로 분리** (실사용 후 조정 예정)
4. **현재 개념 문서**를 doc_id로 Qdrant에서 조회 (세션이 있으면 항상 컨텍스트에 포함)
5. **신뢰 구간(band) 판정** — 검색 최고 점수 기준

| 최고 점수 | band | 처리 |
|---|---|---|
| ≥ 0.50 | `high` | 검색 결과 상위 3개를 근거로 답변 |
| 0.45 ~ 0.50 | `mid` | 검색 결과를 주되, 질문과 관련 있을 때만 사용하도록 프롬프트에서 지시 |
| < 0.45 | `low` | 검색 결과를 쓰지 않고 LLM 자체 지식으로 답변 + "경제 학습 범위 밖 질문" 안내 |

   - 검색 상위 결과의 `stages` 가 `["excluded"]` 이면 답변 끝에 "경제 학습 범위 밖 용어" 안내를 붙인다.
   - 임계값(0.50, 0.45)은 **설정값**으로 분리한다.
6. **현재 개념과의 관련성(is_related) 판정** (세션이 있을 때)
   - `keyword`/`detected`로 세션을 시작한 첫 메시지는 항상 `true`
   - `relearn`으로 자동 시작한 첫 메시지는 일반 관련성 규칙으로 판정한다
   - 질문에 현재 개념의 `term`/`aliases` 가 포함되면 `true` (비교·연결 질문)
   - 질문이 **다른 개념만** 가리키면(다른 개념의 용어는 있고 현재 개념 용어는 없음) `false` (3.5)
   - 검색 상위 5개 안에 현재 개념 doc_id가 있으면 `true`
   - 아니면 경량 LLM 호출로 판정 ("이 질문이 '{term}' 학습과 관련 있는가? yes/no"), 판정 실패 시 `false`
   - 세션이 없는 `free` 메시지는 항상 `false`
7. LLM 답변 생성 (5.2 프롬프트)
8. 메시지 저장 (질문, 답변, session_id 또는 null, is_related, band, sources, 최고 점수, 지연 시간)

### 5.2 프롬프트 구성
- **system**
  - 역할: 경제 지식이 부족한 청년에게 경제 개념을 쉽게 설명하는 튜터
  - 쉬운 말, 생활 속 예시 1개, 3~6문장 내외
  - 제공된 근거(시사경제용어사전)에 있는 내용 위주로 설명하고, 근거에 없는 사실을 단정하지 않는다
  - 근거를 사용했으면 마지막에 "출처: 시사경제용어사전" 표기
  - 현재 학습 개념: `{term}` — 관련 없는 질문에도 답하되 현재 개념으로 억지로 연결하지 않는다
  - band 별 지시 (5.1 표)
- **context**: 현재 개념 정의 + 검색 근거(band에 따라) — 각 근거는 `[doc_id] term: text` 형식
- **history**: 같은 세션의 최근 6턴
- **user**: 현재 질문
- 프롬프트 템플릿은 `prompts.py` 한 곳에 모은다 (나중에 수정하기 쉽게).

---

## 6. 저장소 (대화 기록·학습 맥락)

- 팀의 일반 데이터 저장소는 **Supabase(PostgreSQL)** 이다. **SQLAlchemy** 로 구현해 `CHAT_DB_URL` 만 바꾸면
  로컬은 SQLite, 배포는 Supabase PostgreSQL에서 같은 코드로 동작하게 한다.
- 현재 SQLAlchemy 저장소는 시작 시 없는 `chat_sessions`, `chat_messages`, `learning_contexts`를 자동 생성한다.
  `create_all()`은 기존 테이블 변경을 수행하는 migration이 아니므로 운영 스키마 변경은 별도 migration/DDL로 관리한다.
- 개발용 `dev_concept_status`, `dev_user_stage`는 `DEV_USE_LOCAL_STATUS=true`일 때만 생성한다. 배포 기본값은
  `false`이며 실제 `ConceptStatusService`를 주입한다.
- `ChatStore` 인터페이스를 두고 서비스는 인터페이스에만 의존한다.
- 테이블 (모든 테이블에 `user_id` 인덱스)
  - `chat_sessions`: session_id, user_id, stage, doc_id, term, attempt, start_type(`keyword`/`detected`/`relearn`), status(`active`/`completed`), created_at, completed_at
  - `chat_messages`: message_id, session_id(free 메시지는 null), user_id, role, content, is_related, band, top_score, sources(JSON), latency_ms, created_at
  - `learning_contexts`: session_id, user_id, doc_id(**유일한 상태 갱신 대상**), payload(JSON, 4.5 구조), created_at
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
  router.py        # APIRouter (prefix="/chat") — 엔드포인트만
  service.py       # 세션·메시지·완료 처리 (비즈니스 로직)
  retrieval.py     # rag_common 래핑: SEARCH_PROFILES 순회 검색·결합, 개념 조회(doc_id), band 판정
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
| `BAND_HIGH` / `BAND_LOW` | `0.50` / `0.45` |
| `DISPLAY_SOURCE_MIN_SCORE` | `0.60` (현재 개념 외 화면 표시 출처의 최소 점수) |
| `STAGES_JSON_PATH` | `data/stages.json` |
| `CHAT_DB_URL` | 로컬 `sqlite:///chat.db` / 배포 Supabase PostgreSQL 연결 문자열 |
| `LLM_RELEVANCE_MODEL` | 미지정 시 `LLM_MODEL` 과 동일 |
| `DEV_USE_LOCAL_STATUS` | `true` / `false` (코드 기본값 `false`). 개발용 상태 테이블과 구현 사용 여부 |
| `DEV_SIMULATE_QUIZ_STATUS` | `true` / `false` (코드 기본값 `false`). 개발용 개념 상태 구현에서만, 퀴즈 통과 보고를 `통과`로 반영 |

**통합 방법 (README에 명시)**
```python
from chatbot.router import router as chat_router
app.include_router(chat_router)
```
- 시작 시 임베딩 모델·Qdrant 클라이언트를 로드하는 lifespan/startup 훅 사용법도 README에 적는다.

---

## 8. 작업 방식 (Cursor에게)

1. **먼저 구현 계획과 파일 구조를 제시하고 확인을 받은 뒤** 코드를 작성한다.
2. 아래 순서로 단계별 구현, 단계마다 테스트를 통과시킨 뒤 다음으로 넘어간다.
   1. `config`, `schemas`, `integrations`(인증·개념 상태 인터페이스 + 개발용 구현)
   2. `concepts` (추천 API: 일반/재학습 모드)
   3. `store` (SQLAlchemy) + 상태 조회(`/chat/state`)·세션 조회 API
   4. `retrieval` (doc_id 조회, 검색, band 판정)
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

- [ ] stage1 `미학습` 개념 5개 추천 → 다음 5개 페이지네이션, `통과` 개념은 나오지 않음
- [ ] 키워드로 "분업/특화에 대해 알려줘" 전송 → 세션 시작, 상태 `미학습 → 미통과`, 출처 표기된 쉬운 설명
- [ ] 키워드 없이 "워킹푸어가 뭐야?"(현재 스테이지 미학습 개념) → 개념 감지로 세션 시작 (`session_started=true`)
- [ ] 다른 스테이지 개념·통과한 개념 질문 → 답변만, 세션·상태 변화 없음
- [ ] "오늘 날씨 어때?" → 자체 지식 답변 + 범위 밖 안내, `band=low`
- [ ] 학습 중 다른 개념 질문(예: 분업/특화 학습 중 "젠트리피케이션이 뭐야?") → 답변만, `is_related=false`, 젠트리피케이션 상태는 `미학습` 그대로, 학습 맥락·퀴즈는 분업/특화 기준
- [ ] 학습 중 비교 질문(예: 인플레이션 학습 중 "디플레이션이랑 뭐가 달라?") → `is_related=true`, 학습 맥락에 포함, 디플레이션은 `mentioned_concepts` 에만 기록되고 상태 변화 없음
- [ ] 다른 개념 질문에도 거절 없이 쉬운 설명 제공
- [ ] 학습 완료 → 상태는 `미통과` 그대로, 학습 맥락에 `status`, `attempt`, 관련 대화만 포함
- [ ] 미통과 1개 상태(재학습 모드) → `/chat/state` 가 `relearn` 과 안내 문구 반환, 첫 메시지로 `attempt=2` 세션 시작, 다른 키워드 선택 시 409
- [ ] 새로고침·서버 재시작 후 대화와 학습 맥락 복원
- [ ] 다른 사용자의 세션 조회 시 404
- [ ] 메시지마다 응답 지연 시간(ms) 기록
- [ ] payload에 `images` 가 있는 mock 문서가 검색되면 `sources[].images` 로 전달됨, 없으면 필드 생략
- [ ] `SEARCH_PROFILES` 에 테스트용 두 번째 컬렉션을 등록하면 코드 수정 없이 두 소스 결과가 자리 배분으로 합쳐짐 (mock 테스트)
- [ ] 개발 모드(`DEV_SIMULATE_QUIZ_STATUS=true`)에서 퀴즈 통과 보고 → 해당 개념 `통과`, 남은 `미학습` 키워드 노출. 설정이 꺼져 있으면 개념 상태는 바뀌지 않음

---

## 10. 확정 사항 (구현 전 질문에 대한 답변, 위 내용과 충돌하면 이 절이 우선)

1. **LLM**: OpenAI API 사용. 모델명은 환경변수 `LLM_MODEL` 로 지정(경량 모델, 기본값은 현재 사용 가능한 OpenAI 경량 모델로 README에 명시). 관련성 판정은 `LLM_RELEVANCE_MODEL` (미지정 시 `LLM_MODEL` 과 동일). `llm.py` 는 제공사 교체가 가능한 어댑터 구조 유지.
2. **stages.json 경로**: 파일을 `data/stages.json` 으로 옮기고 설정 기본값도 그대로 둔다.
3. **별칭**: 요청마다 조회하지 않는다. **서버 시작 시 1회** stages.json의 모든 doc_id(고유 211개)에 대해 Qdrant payload(`term`, `aliases`, `text`)를 가져와 메모리에 캐시한다. Qdrant 포인트 ID는 `uuid5(NAMESPACE_URL, doc_id)` 이므로 ID로 직접 조회 가능 (또는 `doc_id` keyword 필터).
4. **메시지 저장**: user/assistant **두 행**으로 저장. 응답의 `message_id` 는 assistant 행. `is_related`, `band`, `top_score`, `sources`, `latency_ms` 는 assistant 행에 저장. 학습 맥락은 user→assistant 쌍으로 묶어 만든다.
5. **SSE 형식**: `event: token` / `data: {"delta": "..."}`, 마지막 `event: done` / `data: {4.2 응답 메타데이터 + message_id}`, 실패 시 `event: error` / `data: {"detail": "..."}`.
6. **개발용 개념 상태**: 메모리가 아니라 **SQLite 테이블**(`dev_concept_status`, 현재 스테이지는 `dev_user_stage`)에 저장해 재시작 후에도 유지. 조회·`mark_failed` 인터페이스는 그대로 두고, `note_quiz_result()` 만 기본 no-op으로 추가한다. 통과 시뮬레이트는 개발용 구현과 `DEV_SIMULATE_QUIZ_STATUS` 에만 있다.
7. **stage 쿼리**: `stage5` 외의 값이 오면 **400**. `stage5` 는 누구나 선택 가능하게 두고, 허용 조건은 팀 확정 후 반영 (**미확정**).
8. **definition**: Qdrant `text` 에서 `설명:` 이하만 넣는다 (용어명·도메인은 별도 필드에 이미 있음).
9. **mentioned_concepts**: 3번 캐시의 개념(stages.json 전체)의 `term`/`aliases` 가 **질문 문장에 포함**된 경우만 기록, 현재 개념은 제외. 검색 결과는 사용하지 않는다 (오탐 방지).
10. **퀴즈 대기 중 입력**: 학습 완료 후 퀴즈 결과가 나오기 전에는 재학습 세션을 열지 않는다.
    - `learning_contexts` 에 `quiz_status`(`pending`/`passed`/`failed`) 추가, 기본 `pending`
    - 퀴즈 모듈이 결과를 알릴 수 있도록 `service.report_quiz_result(session_id, passed: bool)` 함수와 내부용 API `POST /chat/sessions/{id}/quiz-result` 제공. 서비스는 `quiz_status` 만 기록하고 개념 상태는 직접 바꾸지 않은 채 `note_quiz_result()` 에 넘긴다. 개발용 SQLite 구현은 `DEV_SIMULATE_QUIZ_STATUS=true` 이고 `passed=True` 일 때만 `미통과 → 통과` 로 바꾼다.
    - `pending` 동안 `/chat/state` 의 `mode` 는 `quiz_pending`, 메시지는 **세션 없이 답변만**(free) 처리
    - `failed` 가 기록된 뒤에 보내는 첫 메시지부터 재학습 세션(`attempt+1`) 시작
11. **Stage 5 메시지 시작**: `POST /chat/messages` 요청에 선택 필드 `stage`를 추가한다. 허용 값은 `stage5`뿐이며, `stage="stage5"`와 `selected_doc_id`를 함께 보낸 경우에만 현재 스테이지와 무관하게 Stage 5 미학습 개념으로 세션을 시작할 수 있다. 자유 질문 자동 감지는 계속 현재 스테이지 개념만 대상으로 한다. 개발용 `mark_failed()`도 명시된 Stage 5 개념을 허용한다.
12. **재학습 첫 메시지 관련성**: 재학습 모드에서는 첫 메시지로 잠긴 개념의 새 세션을 자동 시작하지만, `is_related`는 일반 관련성 규칙으로 판정한다. "첫 메시지는 항상 true" 규칙은 `keyword`/`detected` 시작에만 적용한다.
13. **LLM 필수 설정**: `LLM_MODEL`은 코드 기본값을 두지 않으며, 미지정 시 시작 단계에서 명확한 설정 오류로 실패한다. 권장 모델과 확인 방법은 README에만 기록한다.
14. **추론 강도**: `LLM_REASONING_EFFORT`의 코드 기본값은 빈 값이며, 빈 값이면 OpenAI 요청에서 `reasoning` 파라미터를 생략한다. `.env.example`에는 `low` 예시와 모델 미지원 시 비우라는 주석을 둔다.
15. **low band 근거**: `band=low`이면 응답 `sources`는 빈 배열이다. `band`와 `top_score`는 유지하며, 검색 결과는 답변 근거로 사용하지 않는다.
16. **외부 호출 실패의 원자성**: 완성된 user/assistant 쌍만 저장한다. Qdrant 또는 LLM 호출 실패는 HTTP 502로 반환하고 메시지를 저장하지 않는다. 새 세션 생성과 `mark_failed()`는 LLM 답변 생성이 성공한 뒤에만 실행해 외부 호출 실패 시 세션·개념 상태가 바뀌지 않게 한다.
17. **화면 표시용 출처**: 메시지 응답에 `display_sources`를 추가한다. `sources`는 LLM에 전달한 전체 근거로 유지하고 저장 방식도 바꾸지 않는다. `band=low`이면 `display_sources=[]`이며, 그 외에는 현재 세션 개념 문서가 검색됐으면 항상 포함하고 다른 문서는 `DISPLAY_SOURCE_MIN_SCORE`(기본 `0.60`) 이상만 포함한다.
18. **임베딩 의존성 고정**: `rag_common.py`는 수정하지 않고, 새 환경에서도 현재 검증된 조합이 재현되도록 `sentence-transformers==6.1.0`으로 고정한다.
19. **퀴즈 결과 단일 기록**: `quiz-result`는 완료되어 학습 맥락의 `quiz_status`가 `pending`인 세션에만 허용한다. active 세션이나 이미 `passed`/`failed` 결과가 기록된 세션은 409로 거절하며 기존 결과를 덮어쓰지 않는다.
20. **SSE 원자성**: 비스트리밍과 스트리밍은 같은 메시지 준비·분기·검증·저장 함수를 공유한다. 스트리밍 중 LLM 오류가 나면 `error` 이벤트로 끝내고, 클라이언트가 중간에 연결을 끊으면 이벤트 생성을 중단한다. 두 경우 모두 메시지 저장, 세션 생성, `mark_failed()`를 수행하지 않는다. 모델 스트림이 끝까지 성공하고 연결이 유지된 경우에만 상태를 반영한 뒤 `done`을 보내며, `done` 메타데이터에는 `display_sources`를 포함한다.
21. **Supabase 배포 준비**: PostgreSQL은 psycopg 3 드라이버를 사용한다. 채팅 본 테이블은 현재 시작 시 없는 테이블만 자동 생성하지만 migration을 대신하지 않는다. 개발용 상태 테이블은 `DEV_USE_LOCAL_STATUS=true`일 때만 만든다. Supabase에서는 Session pooler 연결 문자열을 권장하고, 비밀번호 예약 문자를 URL 인코딩하며, 챗봇 사용자 데이터 테이블에 정책 없는 RLS를 켠다. `user_id`는 Supabase Auth 사용자 UUID를 사용한다.
