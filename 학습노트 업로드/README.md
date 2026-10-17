# 경세학당 — 학습노트

학습노트·퀴즈 연동 기능의 GitHub 업로드용 소스다. 실행과 회귀 검증에 필요한 공통 FastAPI 서버 및 사전테스트 의존성도 포함한다.

## 현재 기능

- Stage 1~5 선택, 기본값 Stage 1. 전체 스테이지 선택은 제공하지 않는다.
- 개념별 목록과 문항 전환 탭. 제출된 문항만 표시한다.
- 전체 풀이·오답노트·정답 기록의 목록과 탭에 같은 필터 적용.
- 다시 풀기는 해당 문항의 퀴즈 화면으로 이동하며 결과는 복습 기록에만 저장한다.
- 최초 답안·채점·통과 결과를 유지한다. 해설은 하오체로 통일한다.
- 개념 다시 학습 버튼과 전용 API는 제공하지 않는다.

## 로컬 실행

Python 3.10 이상에서 가상환경을 준비하고 실행한다.

```bash
python -m pip install -r requirements.txt
python -m uvicorn quiz_preview:app --host 127.0.0.1 --port 8012
```

학습노트: http://127.0.0.1:8012/learning-notes

미리보기는 외부 AI 호출 없이 예시 문제와 임시 SQLite를 사용한다. 서버가 종료되면 미리보기 기록도 사라진다.

## 일반 서버 및 Supabase

.env.example을 참고하여 개인 .env를 만들고 QUIZ_DATABASE_URL을 설정한다. .env는 Git에 올리지 않는다.

```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

일반 서버의 학습노트 경로도 /learning-notes다. 단독 개발은 DEV_MODE=true를 사용한다. 운영은 공통 인증의 검증된 사용자 ID를 연결해야 하며 개발 모드를 사용하지 않는다. 실제 로그인 연동은 통합 담당 범위다.

SQL은 sql/에 보관한다. 검증에 사용한 공유 Supabase에는 quiz_reviews와 추가 인덱스를 적용했다. 새 환경에 적용할 때에는 기존 구조를 확인하고 사용한다. 서버는 SQLite가 기본이며 PostgreSQL 사용 시 postgresql+asyncpg 형식의 연결 URL이 필요하다.

## API와 검증

API 사용법은 LEARNING_NOTES_HANDOFF.md를 확인한다.
실제 Supabase 함수·DB 검증 결과는 verification/학습노트_Supabase_검증.md에 있다. 로그인·HTTP 통합 및 RLS 역할별 검증 완료를 뜻하지 않는다.

```bash
python -m unittest discover -s tests -q
```

이 업로드 폴더에는 .env, 실제 DB, 가상환경, 캐시, 스크린샷, 과거 백업을 포함하지 않았다.
