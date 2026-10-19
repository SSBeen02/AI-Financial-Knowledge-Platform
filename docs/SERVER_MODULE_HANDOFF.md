# 서버 통합 변경 인수인계

2026-10-19 기준. 안유빈 담당 챗봇·학습 관리와 박서현 담당 퀴즈를 Cloudtype 단일 프로세스에서 연결하기 위한 변경이다. 실제 배포 완료를 뜻하지 않는다. 운영 절차는 [DEPLOYMENT.md](../DEPLOYMENT.md)를 사용한다.

## 안유빈 담당 변경

| 파일 | 수정 내용 | 영향 |
| --- | --- | --- |
| `rag/chatbot_module/chatbot/config.py` | `get_settings()`가 `PYTHON_DOTENV_DISABLED=1/true`일 때 `Settings(_env_file=None)` 사용 | 통합 실행에서 중첩/로컬 dotenv 대신 프로세스 설정만 사용. 플래그가 없으면 기존 dotenv 동작 유지 |
| `rag/chatbot_module/GUIDE/CHATBOT_SPEC.md` | 상단에 통합 배포 진입점, 인증 주입, dotenv 처리, 운영 문서 참조 추가 | 검색·학습 계약 변경 없이 운영 설정 방식 명시 |

모듈 외부 `run_integration.py`에서 챗봇 인증 의존성을 공통 Supabase 검증 함수로 override한다. 실제 학습 상태 서비스와 저장소 provider를 `register_quiz_integration()`에 연결한다. 검색 알고리즘·개념 상태 전이·LLM 프롬프트는 이번 작업에서 수정하지 않았다.

확인 요청: 운영 인증 토큰으로 학습 시작·완료·재학습, 콜백으로 상태 및 진행률 반영, 단독 개발 실행의 기존 설정 호환성. 현재 `main_dev:app`을 운영 통합 진입점으로 사용하지 않는다.

## 박서현 담당 변경

| 파일 | 수정 내용 | 영향 |
| --- | --- | --- |
| `quiz-upload/app/db.py` | `inspect` 추가. `init_quiz_models()`에서 DB_AUTO_CREATE를 확인하고 false면 테이블·필수 컬럼 존재 검사 | 운영 자동 DDL 차단. 누락 시 migration 안내 오류로 시작/요청 실패 |

플래그 미설정 기본은 SQLite에서 true, PostgreSQL에서 false다. 명시적으로 true인 단독 실행은 기존 create_all을 사용할 수 있지만 통합 운영 진입점은 true를 거절한다. 스키마 검사는 타입·인덱스·제약·RLS 정책까지 비교하지 않는다.

모듈 외부에서 퀴즈 공통 인증 provider를 override하며 기존 `TeamQuizService`와 결과/실패 콜백을 사용한다. 생성 프롬프트·채점 기준·제출 멱등성·고정 문제는 수정하지 않았다.

확인 요청: 실제 PostgreSQL 접속과 SSL 옵션, 퀴즈 생성·채점·실패 콜백, 재요청 세션 연결 및 타 사용자 조회·제출 거절. 기존 퀴즈 테스트는 개발 모드 전제이며 운영 무인증 요청은 401이 정상이다.

## 공통 서버 신규 파일

| 파일 | 내용 |
| --- | --- |
| `run_integration.py` | 실제 저장소 import 경로와 stages 경로 해석, 프로세스 설정 검증, 두 라우터 등록, lifespan에서 DB·모델·캐시·어댑터 초기화 및 퀴즈 DB 종료, 오류 핸들러·CORS·/health |
| `server_auth.py` | Supabase Auth 사용자 조회로 Bearer 토큰 검증. 반환 UUID 사용. 무인증/거절 응답 401, 네트워크·인증 서버 이상 응답 503 |
| `requirements.txt` | 챗봇·퀴즈 requirements 모두 포함 |
| `.env.example` | 실제 키 없는 운영 변수 템플릿 |
| `.gitignore` | dotenv·DB·캐시·테스트 패키지·가상환경 제외. `.env.example`은 포함 |
| `tests/test_server_integration.py` | 인증 실패·검증된 ID·인증 네트워크 실패, 라우터·CORS, 초기화/종료, 자동 DDL 차단 등 회귀 검사 |
| `DEPLOYMENT.md` | 팀 공유용 운영·배포·롤백·장애 확인·검증 절차 |
| `docs/SERVER_MODULE_HANDOFF.md` | 담당자별 변경 및 확인 요청(이 문서) |

## 검증과 남은 작업

통합 9개 + 챗봇 설정 16개 + 기존 퀴즈 23개(+3 subtests) 통과. 기존 퀴즈 회귀는 DEV_MODE=true 및 DB_AUTO_CREATE=true로 실행했다. Supabase는 스키마 읽기만 수행했다.

배포 뒤 실제 로그인 토큰, Qdrant/KURE, 유료 LLM으로 학습→완료→퀴즈→결과 반영을 검증해야 한다. 이번 진입점에는 게임 보상·사전테스트 API가 포함되지 않는다. 프론트 API 주소와 access token 전달 연결도 별도로 확인한다.
