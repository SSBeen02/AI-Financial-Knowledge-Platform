# 인수인계: 배포 응답 지연 개선 (2026-11-25, Claude → Codex)

## 배경 (배포 로그 실측, Cloudtype 0.2 vCPU 공유, OMP/MKL_NUM_THREADS=1 적용 후)
- 첫 SSE 토큰 7.6~15.2초. 70~80%가 쿼리 임베딩 완료 전 구간(같은 질문도 5.1~11.5초로 변동).
- 컬렉션별 Qdrant 조회 0.3~0.66초. 재배포 직후 첫 요청에서 FSS 구간 15.9초 1회(재현 안 됨).

## 작업 목록과 상태 (Claude 작업 완료분)
| # | 작업 | 상태 | 위치 |
|---|---|---|---|
| 1 | 쿼리 임베딩 LRU 캐시(단일 `encode([query])`만, 512개, 결과 복사본 반환) | 완료 | `chatbot/embedding_cache.py`, `chatbot/deps.py:get_dense_encoder` |
| 2 | 시작 시 워밍업(검색 1회, LLM·DB 없음, 실패해도 기동, 끝나면 캐시 비움, `CHATBOT_WARMUP=false`로 끔) + CPU/스레드 로그 | 완료 | `chatbot/deps.py:warm_up_retrieval`, `run_integration.py` lifespan |
| 3 | 컬렉션 병렬 검색(임베딩·Kiwi는 호출 스레드에서 1회 선계산, 결과는 원래 순서로 병합) | 완료 | `chatbot/retrieval.py:Retriever.search`, `_RequestSparse` |
| 4 | 첫 덩어리 조기 방출(30자 이상이면 60자 안 공백에서 분할, 출처·고지 줄·열린 링크·열린 `**`는 제외) | 완료 | `chatbot/answer_format.py` |
| 5 | 타이밍: `embedding_cache_hit/miss`, `sparse_encode_complete` 추가(기존 마크 유지) | 완료 | 위 파일들 |
| 6 | pytest 426 passed, 1 skipped (Linux Python 3.12, 외부 연결 없음) | 완료 | `tests/test_latency_improvements.py` 신규, `tests/test_retrieval.py` 기대값 수정(embedding_reused 2→3) |

## 남은 일 (Codex/사용자)
1. 로컬 서버 실행 → 로그에 `chatbot_runtime ...`, `chatbot_warmup done elapsed_s=...` 확인.
2. `scripts/run_manual_check.py` 전체 PASS 확인(계정 manual-check-user).
3. 같은 질문 2회 연속 → 두 번째 요청에 `embedding_cache_hit`, elapsed_ms 단축 확인. 첫 글자 표시·답변 끝 출처 줄 정상 확인.
4. 사용자가 커밋·push(test-rag) → 배포 재측정(같은 질문 3회 + 다른 질문 1회).
5. 배포 기동이 너무 길어 실패하면 환경변수 `CHATBOT_WARMUP=false`로 끄고 알릴 것.

## 알려진 위험
- 시작 시간이 워밍업만큼 늘어남(0.2 vCPU에서 약 10~20초 추측). Cloudtype 기동 제한 시간은 확인 안 됨.
- Qdrant 클라이언트를 여러 스레드가 동시에 사용(httpx 동기 클라이언트, 일반적으로 안전하다고 알려져 있으나 실서버 확인 필요).
- 캐시는 프로세스 메모리(최대 약 2MB), 재배포·재시작 시 비워짐.

## 규칙
- 모델·검색 결과·API 스키마·DB 변경 금지. 커밋/push 금지(사용자가 직접).
- rag/chatbot_module/.git 사용·삭제 금지. git은 저장소 루트 기준.
- 토큰·인증값을 코드/문서/출력에 쓰지 말 것. 수동 점검 계정은 manual-check-user만.
