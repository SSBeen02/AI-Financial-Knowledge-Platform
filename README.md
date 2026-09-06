# AI 기반 맞춤형 금융 지식 플랫폼
AI 융합캡스톤디자인2 프로젝트 

```
project-root/
├── README.md
├── docs/
│   ├── api-spec.md # BKT ↔ 게임(캐릭터/미니게임) 연동 API 스펙
│   └── concept-stat-mapping.md # 개념(concept) ↔ 캐릭터 스탯 매핑표
│
├── frontend/                     # 김선빈
│   └── src/
│       ├── features/
│       │   ├── character/        # 캐릭터 성장
│       │   ├── minigame/         # 미니게임
│       │   └── quiz/             # 퀴즈
│       ├── components/           # 공통 UI
│       ├── pages/                # 화면 단위
│       └── api/                  # 백엔드 호출 함수
│
├── backend-rag-bkt/              # 안유빈
│   ├── parsing/                  # 금융 문서 파싱
│   ├── embedding/                # 임베딩 생성
│   ├── bkt/
│   ├── quiz-bank/                # 난이도별 사전테스트 문항
│   └── api/
│
├── backend-finance/              # 박서현
│   ├── news-summary/             # 금융 기사 요약
│   ├── recommend/                # 청년/청소년 지원사업 추천
│   └── api/
│
└── .github/
    └── PULL_REQUEST_TEMPLATE.md
```
