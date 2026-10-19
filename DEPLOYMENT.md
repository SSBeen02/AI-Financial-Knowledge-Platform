# Cloudtype 통합 서버 배포

팀 공유용 운영 문서. 담당: 서버·배포는 통합 담당자, 챗봇·학습 관리는 안유빈, 퀴즈·채점은 박서현. 이 문서는 설정 방법이며 실제 Cloudtype 적용 완료 기록은 아니다.

## 서버 구성과 요청 흐름

Figma Make 프론트 → Cloudtype FastAPI → Supabase Auth / PostgreSQL / Qdrant / LLM 순으로 연결한다.

| 구성 | 역할 | 담당 |
| --- | --- | --- |
| `run_integration.py` | 초기화, 라우터, 인증 주입, CORS, 오류 처리 | 서버 통합 |
| `server_auth.py` | Supabase 사용자 토큰 검증 | 서버 공통 |
| `rag/chatbot_module/` | 검색·대화·학습 상태·진행률·게임 이벤트 확정 | 안유빈 |
| `quiz-upload/` | 퀴즈 생성·조회·채점·결과 콜백 | 박서현 |

학습 완료 요청은 챗봇의 동기 작업 스레드에서 실제 `TeamQuizService`로 전달된다. 어댑터는 동일 프로세스의 실행 중인 이벤트 루프에서 비동기 퀴즈 서비스를 호출한다. 채점·생성 실패 결과는 학습 관리 provider로 돌아간다. 퀴즈 채점은 박서현 모듈, 최종 개념 상태·진행률 변경은 안유빈 모듈이 맡는다. 이 구조는 워커 1개·레플리카 1개 기준이다.

## Cloudtype 설정

배포 디렉터리는 **저장소 루트**다. `main_dev:app`은 챗봇 단독 개발 진입점이며 운영 통합은 `run_integration:app`을 사용한다.

루트 `requirements.txt`는 두 모듈의 의존성을 직접 나열한 독립 설치 목록이다. 설치 단계에서 하위 소스 폴더가 아직 복사되지 않아도 동작하도록 `-r rag/...` 등의 하위 파일 참조를 사용하지 않는다. 모듈 requirements가 변경되면 루트 목록의 버전·extras도 함께 맞춘다. `Could not open requirements file: rag/chatbot_module/requirements.txt`가 나오면 이 수정이 포함된 최신 main 커밋으로 빌드하는지 확인한다. 배포 경로는 계속 빈칸이다.

설치 명령:

```sh
pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && pip install --no-cache-dir -r requirements.txt
```

시작 명령:

```sh
python -m uvicorn run_integration:app --host 0.0.0.0 --port 8000 --workers 1
```

- 포트 8000, 레플리카 1개, 메모리 2.5~3GB(권장 3GB). KURE 초기 다운로드·로딩에는 시간이 필요하다. 0.5GB로는 팀원 권장 요구량을 충족하지 않는다.
- Health Check: `/health`. 정상 응답은 `{"status":"ok"}`. 실제 서버에서는 lifespan 초기화 완료 후 요청을 받는다. 지속적인 외부 DB/LLM 상태 검사나 생성 품질 보증은 아니다.
- `.env.example`의 이름을 기준으로 Cloudtype 환경변수/시크릿을 등록한다. 이 통합 진입점은 로컬·중첩 `.env`를 자동으로 읽지 않는다.
- CORS는 origin을 쉼표로 나눈다. 게시 origin에 필요한 Figma 미리보기 origin을 추가할 수 있다. 경로·마지막 슬래시는 넣지 않는다.
- `SUPABASE_PUBLISHABLE_KEY`는 Supabase 프로젝트의 publishable key다. 기존 anon key는 `SUPABASE_ANON_KEY`로도 설정할 수 있다. 인증에 service_role 키는 필요하지 않다.
- Supabase Auth `/auth/v1/user`에 Bearer 토큰을 전달해 서버에서 검증하고 반환된 UUID를 두 모듈이 공유한다. 요청마다 인증 서버 왕복이 있으므로 인증 서버 장애·지연은 503으로 나타날 수 있다.
- 프론트는 `Authorization: Bearer <로그인 access_token>`을 모든 학습·퀴즈 요청에 넣는다. X-User-Id는 운영 인증이 아니다. 선택 concept_id와 완료 요청 Idempotency-Key도 유지한다.
- 챗봇 DB URL은 psycopg, 퀴즈는 asyncpg 형식이다. 비밀번호 URL 인코딩 및 드라이버별 SSL 옵션을 적용한다. 개발 SQLite 기본값으로 배포하지 않는다.
- 챗봇 migrations 001~004 및 퀴즈 sql/quiz_001_tables.sql 적용 여부를 먼저 확인한다. `DB_AUTO_CREATE=false`에서 퀴즈는 테이블·컬럼 존재만 검사한다(타입·제약·RLS 정책 검증은 별도).
- 게임 보상 API 및 사전테스트 라우터는 이번 통합 진입점에 포함되지 않는다. 챗봇·퀴즈 연결만 제공한다.

배포 검증 순서: `/health` → 무토큰 요청 401 → 로그인 토큰으로 `/learning/current` → concept_id를 포함한 학습 메시지 → 완료(Idempotency-Key) → 실제 퀴즈 조회·제출 → 통과 또는 재학습 상태 확인. 새로고침 복원·타 사용자 접근 거절도 확인한다. 실제 퀴즈 생성에는 API 비용이 발생한다.

현재 로컬 변경을 GitHub에 반영한 뒤 Cloudtype에서 위 설정으로 배포해야 서비스에 적용된다. 이 문서 생성만으로 원격 배포나 프론트 API 주소가 변경되지는 않는다.

## 환경변수와 키 관리

| 변수 | 용도 / 주의 |
| --- | --- |
| `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL` | 챗봇 LLM. 현재 인수인계는 Upstage이며 퀴즈 OpenAI 키와 별개 |
| `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION`, `DENSE_MODEL` | 검색 서버와 임베딩 모델 |
| `STAGES_JSON_PATH` | 기본 `data/stages.json`. 상대 경로는 `rag/chatbot_module` 기준 |
| `CHAT_DB_URL` | 동기 PostgreSQL 접속: `postgresql+psycopg://...` |
| `QUIZ_DATABASE_URL` | 비동기 PostgreSQL 접속: `postgresql+asyncpg://...` |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | 퀴즈 생성. 모델 기본값은 퀴즈 설정을 따름 |
| `SUPABASE_URL` | 프론트 로그인과 같은 Supabase 프로젝트의 HTTPS origin |
| `SUPABASE_PUBLISHABLE_KEY` | 인증 서버 호출용 publishable key. 대체 이름 `SUPABASE_ANON_KEY` |
| `CORS_ALLOW_ORIGINS` | 게시 사이트 등 고정 origin의 쉼표 구분 목록. 통합 서버는 `https://app-<영숫자>.makeproxy-c.figma.site` 형태의 Figma Make Preview origin도 허용 |
| `DB_AUTO_CREATE`, `DEV_ENABLE_TOOLS`, `DEV_MODE`, `DEV_SIMULATE_QUIZ_GENERATION_FAILURE` | 운영에서는 전부 `false` |

키·DB 비밀번호는 Cloudtype 시크릿으로 등록하고 문서·이슈·커밋·프론트에 쓰지 않는다. DB URL 두 개는 같은 DB를 가리킬 수 있으나 드라이버와 SSL 옵션은 서로 다르다. Supabase 프로젝트를 바꿀 때 프론트 로그인 프로젝트와 서버 인증·DB가 서로 맞는지 확인한다.

## 배포 및 롤백 순서

1. GitHub에서 `ui-game`의 작업 단위 커밋을 검토하고 `main`으로 병합한다. Cloudtype이 자동 배포에 연결돼 있다면 main 변경이 곧 배포를 유발할 수 있으므로 환경변수·메모리·실행 명령을 먼저 준비한다.
2. 적용 대상 커밋과 Cloudtype 배포 브랜치·서브 디렉터리를 확인한다. 챗봇 하위 디렉터리를 계속 사용하면 통합 진입점과 퀴즈 경로를 찾지 못한다.
3. DB 마이그레이션 적용 상태를 확인한다. 공유 DB에 이미 적용된 SQL을 무조건 재실행하지 않는다. 이번 통합 코드 변경에는 새 마이그레이션 SQL이 없다.
4. 환경변수·메모리·단일 워커/레플리카 설정을 반영하고 배포한다. 키 이름만 기록하고 값은 로그로 남기지 않는다.
5. `/health`와 아래 인수 테스트를 실행한다. KURE를 처음 받을 때는 다운로드/로딩 시간을 고려해 Cloudtype 시작 제한을 확인한다.
6. 실패하면 로그의 오류 종류를 확인하고 이전 정상 배포를 복원한다. 이전 배포의 실행 명령·환경변수·DB 호환성도 함께 확인한다. 데이터베이스를 초기화하거나 자동 생성 플래그를 켜서 우회하지 않는다.

## 장애 확인표

| 현상 | 먼저 확인할 내용 |
| --- | --- |
| 시작 시 환경변수 오류 | 이름 오타, 빈 값, 개발 플래그, PostgreSQL 드라이버 형식 |
| import 오류 / 파일 없음 | 저장소 루트 배포 여부, requirements 설치, stages 경로 |
| 메모리 부족 종료 | 0.5GB 선택 여부, 중복 워커·레플리카, 모델 로딩 로그 |
| migration 오류 | 대상 DB의 테이블·필수 컬럼 존재. 형식·제약·RLS 검토는 별도 |
| 브라우저 CORS 오류 | 실제 요청 origin, 프리플라이트, 게시/미리보기 주소 차이 |
| 401 | 프론트 Bearer access token, 만료, 로그인 프로젝트 일치 여부 |
| 503 인증 오류 | Supabase Auth 네트워크·응답 및 publishable key 설정 |
| 퀴즈 생성 실패 / 재학습 불일치 | OpenAI 설정, 실제 어댑터 등록, 결과/실패 콜백, 단일 워커 유지 |

## 인수 테스트와 현재 확인 범위

- 로그인한 두 계정으로 자기 기록 접근과 타 사용자 접근 거절을 각각 확인한다. 무토큰·위조·만료 토큰은 거절돼야 한다.
- 게시 프론트에서 키워드를 선택하고 문구를 수정해도 `concept_id`를 보존하는지 확인한다.
- 학습 완료에 `Idempotency-Key`를 보내고 같은 요청을 반복해 중복 퀴즈·상태 변경이 없는지 확인한다.
- 통과·실패·생성 실패·재요청·새로고침 복원 흐름을 확인한다. 테스트 계정의 학습 기록은 실제로 바뀌며 LLM 호출 비용이 생긴다.
- 로컬 검증: 통합 테스트 9개, 챗봇 설정 테스트 16개, 기존 퀴즈 테스트 23개(+3 subtests) 통과. 기존 퀴즈 테스트는 `DEV_MODE=true`, `DB_AUTO_CREATE=true`의 개발 조건이다.
- 실제 Supabase의 퀴즈 필수 컬럼 및 학습 세션 `stage_id` 존재는 읽기 전용 조회로 확인했다. 실제 로그인 토큰·KURE·Qdrant·LLM을 사용하는 배포 후 전체 흐름은 별도 검증 대상이다.
- 서버 버전, 배포 커밋, 적용 시각, `/health`, 인수 테스트 결과를 배포 시마다 팀 기록에 남긴다.

## 로컬 회귀 테스트 재현

테스트용 Python 환경에 requirements를 설치하고 아래를 각각 별도 프로세스로 실행한다. 아래 PowerShell 예시의 개발 플래그를 Cloudtype 운영 설정에 복사하지 않는다.

```powershell
python -m pytest tests/test_server_integration.py -q

$env:PYTHONPATH = "$PWD/rag/chatbot_module"
python -m pytest rag/chatbot_module/tests/test_config.py -q

$env:PYTHONPATH = "$PWD/quiz-upload;$PWD/rag/chatbot_module"
$env:DEV_MODE = 'true'
$env:DB_AUTO_CREATE = 'true'
python -m pytest quiz-upload/tests/test_team_quiz_adapter.py quiz-upload/tests/test_quizzes.py -q
Remove-Item Env:DEV_MODE
Remove-Item Env:DB_AUTO_CREATE
Remove-Item Env:PYTHONPATH
```
