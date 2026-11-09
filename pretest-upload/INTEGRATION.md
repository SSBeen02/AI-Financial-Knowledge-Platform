# 사전테스트 연동 계약

「공유 API 및 DB 스키마 10/06 — 나의 경세학당 | 모듈별 책임과 시스템 연동 설계」 기준.
문서 갱신일: 2026-11-10. 사전테스트 담당: 박서현.

공유 설계의 사전테스트 계약과 현재 구현의 상세 규격을 정리한다. 공유 문서에 없는 추가 API와 통합 시 확인할 사항은 아래에서 구분한다. 이 문서 갱신은 공유 DB 적용이나 실제 연동 검증 완료를 뜻하지 않는다.

## 담당 범위와 책임 경계

- 박서현: 사전테스트 문항 제공·채점, 영역별 취약점 분석, 리포트 생성·저장 및 조회 API를 담당한다. 현재 문항은 JSON 문제은행에서 제공하고 진단마다 스냅샷을 저장한다. LLM은 설명만 생성한다.
- 김선빈: 리포트 화면 구성·시각화, 공통 인증·사용자 관리, 캐릭터 생성과 프론트엔드 통합을 담당한다. 그래프·설명은 리포트 조회 API로 받고 분석 원본은 수정하지 않는다.
- 사전테스트 결과는 취약 영역 리포트에만 사용한다. 개념 통과·학습 순서·난이도·진행률·스테이지·게임 데이터를 변경하지 않는다.
- 리포트 생성 중 캐릭터 이름 설정은 프론트엔드가 별도 `POST /characters`로 연결한다. 리포트 생성과 캐릭터 생성은 독립 처리하며 한쪽 실패로 다른 쪽 저장을 취소하지 않는다. 현재 단독 사전테스트 화면에는 캐릭터 이름 설정이 연결되어 있지 않다.
- 박서현 담당인 동적 퀴즈·학습노트·Stage 5는 별도 모듈이다. 공유 문서 6.2의 `create_quiz_set`·`report_quiz_result` 계약은 해당 모듈에 적용하며 사전테스트가 호출하지 않는다.

## 실행

Python 3.10 이상. `python -m pip install -r requirements.txt` 후 `.env.example`을 `.env`로 복사하고 `python -m uvicorn main:app --reload` 실행.
단독 개발: DEV_MODE=true, DIAGNOSTIC_REPOSITORY=memory, LLM_REPORT_MODE=local.
OpenAI 사전테스트 리포트: LLM_REPORT_MODE=openai와 서버 OPENAI_API_KEY를 설정한다. OPENAI_MODEL을 사용하며 beta.chat.completions.parse로 구조화된 서술을 받는다. 총평 1개와 영역별 분석을 병렬 생성한다. LLM 예산은 최대 28초이고 SDK 자동 재시도는 없다. 개념 퀴즈의 호출 정책과는 구분한다.
통합: DEV_MODE=false, DIAGNOSTIC_REPOSITORY=supabase, LLM_REPORT_MODE=openai. 비밀키는 브라우저·Git에 전달하지 않는다.

## 공통 서버 등록

routers.diagnostics.router와 routers.reports.router를 통합 FastAPI 앱에 include_router한다.
공유 설계대로 하나의 FastAPI 서버 안에서 내부 함수 호출을 기본으로 하며, 사전테스트만의 별도 운영 서버를 요구하지 않는다.
`app.dependency_overrides[dependencies.get_current_user_id] = 공통_인증_함수`로 검증된 Supabase Auth UUID 문자열을 제공한다. 요청 본문 user_id는 금지. 공통 인증이 없고 DEV_MODE=false면 401.
현재 개발 모드의 사용자 ID는 `test-user-123`이다. 이는 실제 Supabase Auth 사용자가 아니며, 현재 코드 자체가 JWT나 로그인 DB를 검증하지 않는다. 공통 인증 연결은 아직 확인이 필요하다.
main.py는 단독 개발 진입점이다. 통합 서버의 루트 화면, CORS, 인증, request_id 미들웨어, RequestValidationError 핸들러는 통합 담당자가 한 번 등록한다.
사전테스트 DiagnosticError 핸들러와 공통 code/message/request_id 규격을 통합 오류 처리에 연결한다. register_pretest_exception_handlers는 단독 앱용이다.
일반적인 database/services/schemas/dependencies 패키지 이름은 통합 저장소에 충돌이 없는지 확인하고 모듈 네임스페이스로 배치한다.

## API

- POST /diagnostics: 최초 생성은 201, 기존 응시 재사용은 200. 사용자당 하나의 응시만 시작하며 기존 pending은 이어서 응시하고 processing/completed/failed는 기존 리포트로 이동한다. 본문 없음. id(UUID), user_id, status, resumed, report_id, started_at, total_questions, questions 반환. 문항은 Stage1→4 순서다. questions의 id/domain/domain_label/category/difficulty/question/options만 공개한다. 정답·해설·개념명은 공개하지 않는다.
- POST /diagnostics/{id}/submit: `Idempotency-Key` 헤더 필수(1~128자, 공백만인 키 금지). 본문은 `{"answers":[{"question_id":"finance_investment_001","selected_answer":2}, ...]}`. 전체 문항을 한 번씩 제출하며 보기 번호는 1부터 시작한다. 본문에 키나 user_id를 넣지 않는다.
- 최초 접수: 202, id/report_id/user_id/status=processing/submitted_at/summary/domain_scores/question_results. 답안·채점 결과를 먼저 저장한 뒤 백그라운드에서 생성한다. 이 응답 후 프런트는 캐릭터 이름 설정 API를 독립적으로 호출할 수 있다.
- 같은 진단·키·답안 재요청: 기존 결과 반환. 처리 중 202, completed/failed는 200. 답안 순서는 무관. 다른 키나 답안은 409 IDEMPOTENCY_CONFLICT. 생성 작업은 다시 시작하지 않는다. 키는 진단별 범위다.
- GET /reports/{id}: 200. id=report_id=diagnostic_id. status는 pending/processing/completed/failed. 생성 전 필드는 생략 가능. 그래프는 domain_scores, 분석 문장은 llm_report. failed에도 채점 결과는 제공하며 error.code/message를 반환한다.
- POST /reports/{id}/retry: **현재 구현의 추가 API이며 공유 문서 10/06의 화면 API 목록에는 없다.** 본인 소유 failed 진단에 채점 결과가 있을 때만 processing으로 조건부 갱신하고 새 작업을 등록한다. 성공적으로 재접수하면 202, processing/completed 또는 경쟁 갱신 실패로 새 작업이 없으면 200으로 현재 결과를 반환한다. pending·채점 결과 없음은 422, 대상 없음·타인 소유는 404다. 프론트엔드 및 공유 API 문서에 이 규격을 추가 공유해야 한다.
- 생성 실패 후 같은 제출은 실패 결과를 반환한다. 설명만 다시 만들려면 위 retry API를, 답안부터 새로 응시하려면 POST /diagnostics를 사용한다.

공유 문서의 시작 응답에는 “진단 ID, 문항·보기, 답안”이라고 적혀 있다. 현재 시작 API는 정답을 노출하지 않는다. 이 문구가 정답을 의미하는지 빈 답안 구조를 의미하는지 팀 확인이 필요하며, 확인 전 정답·해설을 시작 응답에 추가하지 않는다.

필드명은 snake_case다. 통합 시 사용자 ID는 Supabase Auth UUID 문자열, 진단/리포트 ID는 UUID, 사전테스트 문항 ID는 문항 JSON의 문자열이다. concept는 표시용 개념명이며 sisa_* 개념 ID가 아니다. 사전테스트 문항을 공유 concepts와 연결된 개념 ID로 간주하지 않는다. stage_id·개념 통과·학습 진행률과 연결하지 않는다.
시간은 서버 UTC ISO 8601. 점수는 0~100, 취약 기준은 70점 미만. HTTP 오류 응답은 code/message/request_id다. GET /reports/{id}의 failed 결과에 포함하는 error는 현재 code/message만 가지므로 공통 HTTP 오류 응답과 구분한다.

## 저장·장애

공유 설계 3.1·3.2에 따라 사전테스트 답안·점수·리포트·생성 상태는 diagnostic_attempts에 함께 저장하고 박서현 모듈이 갱신한다. 다른 담당 모듈은 조회 API를 사용하며 이 테이블의 분석 내용을 직접 수정하지 않는다.
sql/diagnostic_attempts.sql은 팀 검토 후 공유 DB에 적용해야 한다. 현재 공유 DB의 컬럼과 비교해 questions_snapshot/submission_key/error/llm_report 등의 필요 여부를 확인한다. questions_snapshot은 응시 문항 고정, submission_key는 중복 제출 판별, error는 생성 실패 안내에 사용한다. 기존 pending 진단 중 문항 스냅샷이 없는 진단은 새로 시작해야 한다.
스크립트에는 기존 in_progress 값을 pending으로 바꾸고 상태 제약을 다시 설정하는 부분이 있다. 공유 DB에 바로 재실행하지 말고 기존 데이터·제약을 확인한 뒤 관련 담당자 검토를 받는다. 변경 스크립트는 Git에 남긴다.
user_id는 현재 text이며 Auth UUID 문자열을 저장한다. auth.users 외래키·uuid 타입 변경은 임시 기록 정리 및 팀 DB 합의 후 별도 수행한다.
questions_snapshot은 서버 내부 정답을 포함하므로 직접 클라이언트 조회를 허용하지 않는다. 서비스 역할 키와 RLS를 유지한다.
조회는 개별 점수·LLM 컬럼이 기준이며 report 컬럼은 이전 데이터 읽기 호환용이다.
BackgroundTasks는 프로세스 내 작업이다. 서버 종료·작업 유실로 processing이 남으면 제출 후 30초가 지난 조회에서 failed로 전환한다. 종료된 작업을 자동 재실행하지 않는다. 운영에서 자동 복구가 필요하면 영속 작업 큐를 연결한다.
메모리 저장소는 재시작 시 데이터가 사라지므로 통합 시 Supabase를 사용한다.

## 통합 전 확인과 완료 기준

- **Supabase 실연동 미검증:** 테이블·컬럼·상태 제약을 대조하고 테스트용 DB에서 시작·제출·완료·실패·재생성·중복 요청과 서버 재시작 후 조회를 검증한다. 저장소 구현이 있다는 사실과 실제 DB 검증 완료는 구분한다.
- **공통 인증 연결 필요:** 김선빈의 인증 함수에서 검증된 사용자 ID를 전달하도록 연결한 뒤 서로 다른 사용자로 조회·제출·재생성 접근 차단을 검증한다. 개발 임시 사용자 한 명으로는 사용자 간 격리를 검증할 수 없다.
- **DB 합의 필요:** user_id의 text/uuid 타입과 auth.users 외래키 정책을 확인한다. 공유 문서는 Auth 사용자 ID 공통 사용을 정하지만 사전테스트 테이블의 최종 컬럼 타입·외래키까지 확정하지는 않는다.
- **프론트엔드 연결 필요:** domain_scores와 llm_report, 생성 상태·실패 안내, 독립적인 캐릭터 이름 설정, 추가 retry API를 김선빈과 연결한다. 현재 index.html은 단독 검증용 화면이다.
- **문서 확인 필요:** 시작 응답의 “답안” 의미와 retry API 추가를 공유 문서에 반영한다. 필드 삭제·타입·상태값 변경은 관련 담당자와 사전 공유한다.

공유 설계의 작업 완료 기준은 화면 표시뿐 아니라 API 연결, 저장·복원, 실패·중복 요청 검증까지 포함한다. 개발·테스트 데이터와 시연 데이터를 구분하고 운영에서는 개발 인증을 사용하지 않는다.

## 사전테스트 리포트 생성 시간·문체 (2026-10-06)

리포트 처리 타임아웃 기준은 30초이며 LLM 생성 예산은 최대 28초다. 제출 후 이미 경과한 시간을 고려해 남은 예산을 전달한다. 이는 성공 완료를 보장하는 SLA가 아니다. DB·큐 대기·외부 API 지연·다중 사용자 부하에 따라 failed가 발생할 수 있다.

OpenAI 분석은 총평과 네 영역을 동시에 수행한다. 모델은 설명만 생성하며 점수·등급·문항 ID·영역별 결과·우선순위는 기존 채점 결과에서 조립한다. 프로세스당 동시 OpenAI 요청은 최대 12개다. SDK 자동 재시도는 없고 시간 초과는 REPORT_GENERATION_TIMEOUT, 기타 생성 오류는 REPORT_GENERATION_FAILED로 처리한다. processing → completed/failed 흐름을 유지하고 실패해도 채점 결과를 보존한다. 기존 채점·리포트 필드는 유지한다. 2026-11-10에 최초 응시 재사용·재생성 제한용 필드와 DB 함수가 추가되었으므로 아래 마이그레이션을 먼저 적용한다.

리포트는 친절하고 현대적인 하오체로 작성한다. 학습 권장은 주제별 3~5문장 단일 문단이며 혼동 지점·개념 구분 기준·이후 학습 방향과 문제 접근 전략을 자연스럽게 연결한다. 태그·불렛·과도한 강조와 기계적 문구 반복은 피한다.

2026-10-06 실제 OpenAI API로 각 사례 10회씩 총 30회 순차 측정했다. 평균은 만점 7.717초, 부분 오답 14.174초, 전부 오답 15.621초이며 최댓값은 각각 9.524초, 16.271초, 17.776초다. 실패·30초 초과·채점 불일치는 0건이었다. 로컬 메모리 저장소에서 서비스 제출부터 저장·조회까지 측정했으며 HTTP 전송·브라우저 폴링·Supabase 지연·동시 사용자 부하는 포함하지 않았다. 동일 응답 반복에 대한 제한된 표본이며 향후 성능·품질 보장이 아니다.

배포 후 로그의 report_llm_task(API/대기 시간·토큰), report_llm_total(생성 합계), report_service_total(서비스 시간)을 관찰한다. report_llm_request/response에는 모델에 보낸 교육용 입력·프롬프트와 구조화 응답을 기록한다. API 키·인증 토큰·사용자 식별자는 이 로그에 넣지 않는다. 채점·선택 정보가 포함되므로 서버 로그의 접근 권한과 보관 기간을 제한한다. 사용자별 지연과 성공률은 운영 환경에서 별도 검증한다.

## 사전테스트 화면 및 실패 리포트 재생성

수준 진단과 오답 분석의 summary 첫 문장에는 서버 domain_scores 기준 최저점 스테이지를 포함한다. 표시 순서는 Stage1 사회경제·소비생활, Stage2 금융·투자, Stage3 거시경제·통화·재정, Stage4 국제경제·산업·기술이다. 이는 리포트 표시용 영역 매핑이며 학습 스테이지 배정·진행률을 변경하지 않는다. 실제 점수로 최저점을 비교하고 표시 점수는 정수 반올림한다. 동점이면 해당 스테이지 모두 표시하며, 모두 만점이면 오답이 없다고 표현한다. 신규 생성 결과에 저장되며 과거 리포트도 GET 조회 시 같은 표시를 적용한다(과거 DB 원문을 다시 쓰지 않음). 프론트는 level_diagnosis.summary와 wrong_answer_analysis.summary를 그대로 표시하면 된다.

테스트 화면은 한 문항씩 표시하며 이전·다음 이동 시 선택한 답안을 유지합니다. 모든 문항에 응답한 뒤 결과 보기로 제출합니다.

POST /reports/{id}/retry는 본인 소유의 failed 리포트만 processing으로 전환하고 202를 반환합니다. 기존 채점 결과를 유지하며 LLM 리포트만 다시 생성합니다. processing/completed 상태에서는 재생성을 중복 실행하지 않고 현재 결과를 200으로 반환합니다. pending 상태에서는 재생성을 허용하지 않습니다. 오류 정보는 failed 상태에서만 응답합니다.


## 2026-11-10 미구현 요구사항 보완

- 최초 1회 응시: `POST /diagnostics`는 사용자별 기존 응시를 재사용한다. 브라우저에서 버튼을 다시 누르거나 서버가 여러 개여도 Supabase RPC의 사용자별 트랜잭션 잠금으로 중복 생성을 막는다. 기존 데이터는 삭제하지 않으며 이전 중복 데이터가 있으면 제출된 응시를 우선하고, 그 안에서 가장 오래된 응시를 사용한다. 제출 이력이 있는데 예전 pending 응시로 다시 시험을 치르는 우회를 막는다. `create_attempt` 직접 호출은 응시 시작 API가 아니다.
- DB 적용 순서: 최초 설치 시 `sql/diagnostic_attempts.sql` 다음 `sql/002_single_attempt_retry.sql`을 실행한다. 기존 DB에는 두 번째 파일을 적용한다. RPC가 없으면 저장 오류(503)로 종료하며 중복 응시를 생성하는 우회 동작을 하지 않는다. 사용자가 증분 SQL을 적용한 후 실제 Supabase 기능 검증 47개를 통과했다.
- 재생성 제한: 최초 생성과 별도로 응시당 최대 3회. `failed`에서 실제 재접수된 경우만 `retry_count`를 1 증가한다. 동시·중복 요청은 작업을 추가하지 않는다. 소진 후 `429 REPORT_RETRY_LIMIT_EXCEEDED`를 반환하고 채점 결과는 유지한다. `GET /reports/{id}`의 `retry_count`, `retry_limit`으로 화면 버튼을 제어한다.
- `submitted_at`은 최초 제출 시각을 유지한다. 재생성의 30초 시간 검사는 별도 `report_started_at`을 기준으로 한다. 이전 생성의 늦은 결과·실패는 `retry_count` 조건부 갱신으로 새 생성에 덮어쓰지 않는다.
- 투자 권유 금지 규칙을 모든 리포트 프롬프트에 추가하고, 출력에서 상품 가입·매매 권유 및 수익 보장 표현을 검사한다. 검출 시 `failed`로 처리하고 설명을 저장하지 않으며 채점은 유지한다. 규칙 검사는 모든 우회 표현을 완전히 판별하는 보장은 아니다.
- 응답 최상위 `disclaimer`는 서버가 고정한 `AI 작성, 투자 조언 아님`이다. 프론트는 리포트 표시 시 항상 고지를 표시해야 한다. 개발 화면에도 적용했다.
- 실제 로그인 토큰 검증·HTTPS·배포 화면 연결은 1.3 (9)의 공통 서버 책임을 유지한다. `DEV_MODE=true`는 단독 개발 전용이며 운영에서는 false와 공통 인증 의존성 연결이 필수다.
- 규칙 등급·3개 분석 섹션·학습 상태 자동 갱신 제외·30초 타임아웃/28초 LLM 예산·SDK 자동 재시도 없음은 변경하지 않았다.

## 현재 코드 재검증 (2026-11-10)

자동 시험 62개, 실제 Supabase 기능 검사 47개 통과. 최종 OpenAI·Supabase 호출은 사례별 3회 총 9회이며 모두 completed, 채점·오답 ID·저장 일치 검사 통과. 생성·저장 평균은 만점 8.267초, 부분 오답 16.123초, 전부 오답 18.879초. 30초 미만 관측은 성공 보장 기준이 아니다. 보완 전 첫 9회와 최종 9회 통계를 합치지 않는다.

총평의 입력 누락 단정을 방지하도록 작업 범위를 안내하고, 로컬 대체 리포트의 하오체를 보완했다. 대표 3건 전체 본문과 9건의 선별 검사에서 투자 실행 권유는 발견하지 못했다. 일부 OpenAI 명사 종결의 어색함은 남아 있으며 사람·독립 모델 검수가 아니다. 개발 화면의 답안 새로고침 복원·미응답 제출 방지·기존 결과 재조회·고지 표시를 확인했다. 실제 로그인과 최신 배포 화면 연결은 별도 통합시험이다. 상세 자료는 verification/current-code-retest-20261110/검증결과.md와 리포트미리보기.html을 참조한다.
