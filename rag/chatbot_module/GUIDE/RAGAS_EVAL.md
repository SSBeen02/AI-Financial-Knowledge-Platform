# 골든셋 v4 답변 품질 평가

기존 Hit@k/MRR 검색 평가와 별개로, 골든셋 질문에 대해 현재 챗봇의 **대화 이력 없는 단일 자유 질문 답변**을 생성한다. 정답 문서가 있는 78문항은 RAGAS `Faithfulness`(검색 근거 충실도)와 `AnswerRelevancy`(질문 관련성)를 계산한다. `DB에 없음` 15문항은 RAGAS에 보내지 않고 `band=low`와 서버의 범위 밖 notice 반환 여부를 각각 집계한다. 이 두 RAGAS 지표에는 기대 답변 문장이 필요하지 않다.

## 입력과 실행 조건

- `RAG_골든셋_v4.xlsx`는 질문·유형·정답 문서 ID를 제공한다. 정답 ID는 보관만 하며 Hit@k를 다시 계산하지 않는다.
- 로컬 `qdrant_data/collection/sisa_terms/storage.sqlite`는 읽기 전용으로 열어 메모리 Qdrant에 복사한다. 검색은 기존 `Retriever`와 `DenseEncoder`를 사용한다.
- 기존 `.env`의 답변 모델·말투·지식 모드·temperature를 읽는다. 채점 모델은 `LLM_RELEVANCE_MODEL`(빈 값이면 `LLM_MODEL`)이고, 관련성 지표의 임베딩은 현재 Dense 모델이다. 답변 생성과 RAGAS 채점에는 각각 API 호출과 비용이 든다.
- `DB에 없음` notice는 기존 `_message_notice()`를 **새 사용자·Stage 1·학습 상태 없음**으로 호출한 결과다. 실제 사용자 상태에 따른 모든 notice 분기를 검증하는 테스트는 아니다.
- 학습 세션·메시지·개념 상태, 원본 SQLite, 골든셋을 저장하거나 수정하지 않는다. 답변에 붙는 출처 문구는 CSV에 남기되 RAGAS 채점에서는 제거한다.

평가 전용 의존성은 `python -m pip install -r requirements-ragas.txt`로 설치한다.

## 유형별 15문항 시험 실행

`--limit 15`는 유형을 순회하며 2~3문항씩 선택한다. 먼저 `collect`를 `--run` 없이 실행하면 선택 qid만 확인한다. 다음 명령의 `--run`이 실제 API 호출을 시작한다.

```powershell
python scripts/evaluate_ragas.py collect --golden 'C:\Users\Yubin\Desktop\4-1 프젝\캡디\전처리(임베딩)\RAG_골든셋_v4.xlsx' --sqlite 'C:\Users\Yubin\Desktop\4-1 프젝\캡디\전처리(임베딩)\qdrant_data\collection\sisa_terms\storage.sqlite' --limit 15
python scripts/evaluate_ragas.py collect --golden 'C:\Users\Yubin\Desktop\4-1 프젝\캡디\전처리(임베딩)\RAG_골든셋_v4.xlsx' --sqlite 'C:\Users\Yubin\Desktop\4-1 프젝\캡디\전처리(임베딩)\qdrant_data\collection\sisa_terms\storage.sqlite' --limit 15 --run
python scripts/evaluate_ragas.py score --limit 15 --run
```

`collect`는 답변과 검색 원문을 `eval_outputs/ragas_v4_samples.jsonl`에 기록한다. `score`는 문항별 점수 JSONL, `ragas_v4_summary.json`, 전체 `ragas_v4_results.csv`, 두 점수 중 하나라도 **0.7 미만**인 문항만 담은 `ragas_v4_below_0_7.csv`를 생성한다. 전체 CSV에도 `below_0_7` 열이 있다. `DB에 없음` 행의 두 RAGAS 점수는 빈 값이며 `low_band_pass`·`notice_pass`를 표시한다. `범위 밖 용어` 행은 `scope_notice_returned`에 실제 서버 notice 반환 여부를 표시하고, 요약의 `out_of_scope_terms.notice_return_rate`에 집계한다. 평가하지 않은 notice는 미반환으로 간주하지 않고 `notice_not_evaluated_count`에 센다.

두 명령 모두 `--qids Q001,Q016`, `--types '정확 용어'`(여러 번 지정 가능), `--limit N`으로 대상을 좁힐 수 있다. 일부 평가에서는 **collect와 score에 같은 필터**를 지정한다. 미지정 시 입력 전체가 대상이다. 중단 후 기존 JSONL을 이어 쓸 때는 `--resume`을 사용한다. 시험과 전체 실행은 출력 경로를 별도로 지정한다.

기존 수집 파일에서 notice를 기록하지 않은 `DB에 없음`·`범위 밖 용어` 문항은 같은 선택 옵션으로 `collect --run --resume`을 다시 호출하면 **답변 LLM 재호출 없이** notice만 보충한다. `score --run --resume`은 저장된 점수를 재사용하며 CSV와 요약을 다시 만든다.

한 문항의 `Faithfulness` 0점 원인을 볼 때는 다음 명령으로 **저장된 답변과 contexts**에서 RAGAS의 claim 추출·판정을 다시 실행한다. `--run`은 판정 LLM을 호출한다. 출력 JSON에는 claim, 각 판정의 이유·0/1, 파싱 성공 여부, 요청 수가 담긴다. LLM 재판정이므로 원래 채점 때의 중간 응답과 완전히 같다고 가정하지 않는다.

```powershell
python scripts/evaluate_ragas.py trace --qid Q028 --output eval_outputs/ragas_q028_trace.json --run
```

## 전체 93문항 실행

시험 결과를 검토하고 전체 실행을 승인한 뒤에 아래 명령을 사용한다. 시험 결과와 다른 파일에 저장하고, `--limit`이 없으므로 93문항 전체를 선택한다. `--run` 없이는 API를 호출하지 않는다.

```powershell
python scripts/evaluate_ragas.py collect --golden 'C:\Users\Yubin\Desktop\4-1 프젝\캡디\전처리(임베딩)\RAG_골든셋_v4.xlsx' --sqlite 'C:\Users\Yubin\Desktop\4-1 프젝\캡디\전처리(임베딩)\qdrant_data\collection\sisa_terms\storage.sqlite' --output eval_outputs/ragas_v4_all_samples.jsonl --run
python scripts/evaluate_ragas.py score --input eval_outputs/ragas_v4_all_samples.jsonl --output eval_outputs/ragas_v4_all_scores.jsonl --summary eval_outputs/ragas_v4_all_summary.json --csv eval_outputs/ragas_v4_all_results.csv --below-csv eval_outputs/ragas_v4_all_below_0_7.csv --run
```

요약 JSON에는 답변·채점·임베딩 모델, `CHAT_TONE`, `ANSWER_KNOWLEDGE_MODE`, `LLM_TEMPERATURE`, UTC 실행 시각, 골든셋 파일명 버전, 정답 있는 문항의 전체·유형별 평균과 수, `faithfulness_not_applicable`, 범위 밖 문항의 두 통과율을 기록한다. `api_requests`는 완료된 문항의 HTTP 요청 시도 수로 재시도도 포함한다. 오류로 중단된 문항의 호출은 집계되지 않는다. `elapsed_seconds`는 답변 수집과 **현재 채점 실행**의 시간을 기록한다. `--resume` 시 이전 채점 실행이 합쳐진 전체 벽시계 시간은 `null`이다.

검색 근거가 없는 정답 문항은 `Faithfulness`가 `null`이고 `AnswerRelevancy`만 채점한다. `dictionary_plus`가 허용하는 일반 지식 보충 때문에 충실도가 낮아질 수 있으며, 낮은 점수만으로 오답을 단정하지 않는다. 정답 자체와 비교하려면 검토된 기대 답변과 별도 정답성 평가가 필요하다. `eval_outputs/`에는 질문·답변·검색 원문이 들어가므로 팀 검토 전 커밋하지 않는다.

## 사전 원문 기대 답변과 정답성 재채점

설치된 RAGAS 0.4.3의 `FactualCorrectness(mode="recall")`을 사용한다. 정답 문서가 있는 78문항만 대상으로 하며, `DB에 없음` 15문항은 기존 band·notice 집계를 유지한다. 이 지표는 사전 원문에서 추출한 reference의 주장들이 저장된 답변에 반영되었는지 평가한다. 문장 일치 비교가 아니며 LLM 판정이므로 점수는 정답의 확정 판정이 아니다.

`references` 명령은 골든셋의 첫 `정답_doc_ids`를 로컬 Qdrant SQLite에서 찾아 payload `text`의 `설명:` 뒤 첫 1~2문장을 **원문 그대로** CSV에 저장한다. LLM 재작성과 답변 재생성은 없다. 첫 문장이 약어·유래·사례인 문항은 추출 문장을 검토한 뒤 점수를 해석한다. 특히 복합 문서의 첫 문장이 질문의 대상 용어와 다른 경우 해당 점수는 부적절할 수 있다.

```powershell
python scripts/evaluate_ragas.py references --golden 'C:\Users\Yubin\Desktop\4-1 프젝\캡디\전처리(임베딩)\RAG_골든셋_v4.xlsx' --sqlite 'C:\Users\Yubin\Desktop\4-1 프젝\캡디\전처리(임베딩)\qdrant_data\collection\sisa_terms\storage.sqlite'
python scripts/evaluate_ragas.py score-reference
python scripts/evaluate_ragas.py score-reference --run
```

두 번째 명령은 대상과 예상 호출 수만 보여준다. 현재 RAGAS 구현은 문항당 보통 4회의 판정 모델 요청을 사용하므로 78문항에 **약 312회**가 예상된다(재시도 제외). `--run`에서 기존 `ragas_v4_low049_samples.jsonl`의 답변을 그대로 재사용하고, 결과를 `ragas_v4_low049_factual_recall_scores.jsonl`과 `ragas_v4_low049_factual_recall_results.csv`에 저장한다. 기존 `ragas_v4_low049_summary.json`의 다른 항목은 보존하고 `factual_correctness_recall`에 전체·유형별 평균, 0.7 미만 qid, 실제 API 호출 수를 추가한다. 중단 후에는 `--resume --run`으로 미완료 문항부터 계속한다. 이 산출물은 검토 전 `eval_outputs/`에만 둔다.
