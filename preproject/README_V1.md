# FinEdu README V1

> 청소년·사회초년생을 위한 금융 교육 웹사이트 (2026.08.11 기준)

---

## 프로젝트 소개

**FinEdu**는 금융 문맹 탈출을 돕는 금융 교육 플랫폼입니다.  
기초 개념 학습, 사전테스트를 통한 역량 진단, AI 기반 탐색(예정), 학습노트(예정) 기능을 제공합니다.

---

## 기술 스택

| 분류 | 기술 |
|------|------|
| Frontend | Next.js 15 (App Router), React 19, TypeScript |
| Styling | Tailwind CSS |
| Backend / Auth / DB | Supabase |
| 차트 | Recharts |
| 아이콘 | Lucide React |

---

## 주요 기능 (V1)

### 1. 랜딩 페이지 (`/`)
- Hero 섹션, 특징 카드 3개, 추천 강의 맛보기
- **시작하기** 버튼 — 로그인/사전테스트/메인 페이지로 상태별 자동 라우팅

### 2. 인증 (`/login`, `/signup`)
- Supabase Auth (이메일·비밀번호)
- 회원가입 시 `profiles` 테이블 저장
- 헤더 로그인 상태 표시 (프로필 / 로그아웃)
- 한글 에러 메시지

### 3. 사전테스트 (`/pre-test`)
- 7개 카테고리 JSON 퀴즈 (대출, 세금, 상품이해, 시장분석, 신용관리, 연금 등)
- 카테고리별 5문제, 난이도 균형 랜덤 출제 (총 35문제)
- 1문제씩 진행, 프로그레스 바
- 결과 `pre_test_results` 테이블 저장
- Recharts 카테고리별 정답률 차트

### 4. 마이페이지 (`/mypage`)
- 사이드바 레이아웃
- **내 금융 역량** — 최근 사전테스트 결과 + 차트
- **비밀번호 변경** — `supabase.auth.updateUser()`

### 5. 메인 허브 (`/main`)
- 금융지식 탐색하기 → `/explore` (스켈레톤)
- 학습노트 관리하기 → `/notes` (스켈레톤)

### 6. Header 네비게이션
- 로고 | 메인 페이지 | 사전테스트(미완료만) | 마이페이지 | 로그인/프로필

---

## 페이지 목록

| 경로 | 설명 | 로그인 |
|------|------|--------|
| `/` | 랜딩 페이지 | - |
| `/login` | 로그인 | - |
| `/signup` | 회원가입 | - |
| `/pre-test` | 사전테스트 | ✅ |
| `/main` | 학습 허브 | ✅ |
| `/explore` | 금융지식 탐색 (준비 중) | - |
| `/notes` | 학습노트 (준비 중) | - |
| `/mypage` | 마이페이지 | ✅ |
| `/courses` | 교육 목록 (준비 중) | - |

---

## 프로젝트 구조

```
FinEdu/
├── src/
│   ├── app/                    # App Router 페이지
│   │   ├── page.tsx            # 랜딩
│   │   ├── main/               # 학습 허브
│   │   ├── pre-test/           # 사전테스트
│   │   ├── explore/            # 탐색 (스켈레톤)
│   │   ├── notes/              # 노트 (스켈레톤)
│   │   ├── mypage/             # 마이페이지
│   │   ├── login/ signup/
│   │   └── auth/callback/
│   ├── actions/                # Server Actions
│   ├── components/             # UI 컴포넌트
│   ├── data/pretest/           # 퀴즈 JSON (7개 카테고리)
│   ├── lib/                    # 유틸, pretest 로직
│   └── utils/supabase/         # Supabase 클라이언트
├── supabase/migrations/        # DB SQL
│   ├── 001_profiles.sql
│   └── 002_pre_test_results.sql
├── start-dev.ps1               # Windows 개발 서버 실행 스크립트
├── .env.local.example
└── README_V1.md                # 이 문서
```

---

## 로컬 실행 방법

### 1. 환경 변수

`.env.local.example` → `.env.local` 복사 후 Supabase 값 입력:

```env
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_anon_key
```

### 2. Supabase DB 설정

Supabase Dashboard → **SQL Editor**에서 순서대로 실행:

1. `supabase/migrations/001_profiles.sql`
2. `supabase/migrations/002_pre_test_results.sql`

### 3. 패키지 설치 & 서버 실행

**Windows (Node.js가 PATH에 없을 때):**

```powershell
cd C:\Users\Yubin\Projects\FinEdu
.\start-dev.ps1
```

**일반:**

```bash
npm install
npm run dev
```

브라우저: **http://localhost:3000**

> `npm run dev`는 브라우저를 자동으로 열지 않습니다. 주소를 직접 입력하세요.

---

## GitHub 푸시 방법

### 1. GitHub에서 새 저장소 생성
- https://github.com/new
- Repository name: `FinEdu` (또는 원하는 이름)
- **README, .gitignore 추가하지 않기** (로컬에 이미 있음)

### 2. 로컬에서 푸시

```powershell
cd C:\Users\Yubin\Projects\FinEdu
git remote add origin https://github.com/YOUR_USERNAME/FinEdu.git
git branch -M main
git push -u origin main
```

`YOUR_USERNAME`을 본인 GitHub 아이디로 바꾸세요.

---

## DB 스키마 요약

### profiles
- `id` (uuid, auth.users FK)
- `full_name`, `email`
- `created_at`, `updated_at`

### pre_test_results
- `id`, `user_id`
- `total_score` (맞춘 개수)
- `details` (JSONB — 카테고리, 난이도, 정오답 등)
- `created_at`

---

## V1 이후 예정 기능

- [ ] `/explore` — AI Q&A + 즉시 퀴즈
- [ ] `/notes` — 학습노트·오답 아카이브
- [ ] LLM 기반 금융 역량 보고서 (`details` JSONB 활용)
- [ ] `/courses` — 단계별 커리큘럼

---

## 라이선스

Private / Educational use (팀 내부 프로젝트)

---

**FinEdu V1 — 2026.08.11**
