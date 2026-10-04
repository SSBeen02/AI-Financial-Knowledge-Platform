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
│       ├── character/            # 캐릭터 성장
│       │   
│       ├── components/           # 공통 UI
│       ├── pages/                # 화면 단위
│       └── api/                  # 백엔드 호출 함수
│
├── backend-rag-bkt/              # 안유빈
│   ├── parsing/                  # 금융 문서 파싱
│   ├── embedding/                # 임베딩 생성
│   ├── bkt/
│   └── api/
│
├── backend-finance/              # 박서현
│   ├── pre-test/                 # 사전테스트 문항 및 답안
│   ├── report/                   # 리포트 생성
│   ├── quiz/                     # 동적 퀴즈 관련
│   └── api/
│
└── .github/
    └── PULL_REQUEST_TEMPLATE.md
```
