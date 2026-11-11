# 세 검색 소스 RAGAS 재측정 결과

이 문서는 `BAND_LOW=0.45` 실행 기록이다. 최종 채택한 0.49 재측정 결과는
`GUIDE/RAGAS_THREE_SOURCE_BAND049_RESULT.md`를 참고한다.

실행일: 2026-11-11 (KST)  
골든셋: `RAG_골든셋_v4.xlsx` 전체 93문항  
검색: 실제 Qdrant의 시사용어사전(3,029개), 금융감독원 교재(502개), 한국은행 용어집(790개)  
답변·판정 모델: Upstage `solar-pro4`; 답변 모드 `dictionary_plus`, `CHAT_TONE=hao`, temperature 0.7  
임베딩: KURE-v1; 판정 모델 temperature 0

## 이번 실행 결과

- 정답 문서가 있는 78문항: RAGAS Faithfulness 평균 **0.8816**, AnswerRelevancy 평균 **0.7791**.
- 둘 중 하나라도 0.7 미만인 문항: **33/78**.
- 정답 문서가 답변 근거에 포함된 문항: **76/78**.
- `DB에 없음` 15문항의 low band·notice 동시 통과: **11/15**. `범위 밖 용어` notice: **6/6**.
- 전체 93문항에 반환된 근거 슬롯 수: 시사용어 **246**, 금융감독원 교재 **101**, 한국은행 **164**. 교재 근거는 정답 문항 53/78개에, 한국은행 근거는 78/78개에 반환됐다. 슬롯 수는 고유 문서 수나 답변의 실제 인용 횟수가 아니다.
- 실제 외부 API 요청: 답변 **93회**, RAGAS 판정 **390회**. 수집·채점 93행 모두 완료.

실제 답변 예시(Q001 첫 문장): “기회비용은 어떤 선택을 할 때 그로 인해 포기해야 하는 다른 선택의 가치 중 가장 큰 것을 말하오.” 이 문항의 검색 근거에는 세 컬렉션이 모두 포함됐다.

## 이전 평가와 비교

2026-11-06의 `dictionary_plus` **시사용어사전 단독 로컬 평가**는 Faithfulness **0.7815**, AnswerRelevancy **0.7724**, 0.7 미만 **41/78**, 정답 문서 포함 **76/78**, `DB에 없음` 동시 통과 **11/15**였다. 이번 세 출처 실행은 각각 **+0.1001**, **+0.0067**, **−8문항**이며 정답 문서 포함과 `DB에 없음` 통과 수는 같다.

동일 qid의 점수 방향은 Faithfulness 상승 42개·하락 17개·동일 19개, AnswerRelevancy 상승 39개·하락 37개·동일 2개다. 이전 실행과 날짜·검색 백엔드·생성 답변이 다르고 LLM 생성이 확률적이므로, 이 비교만으로 세 문서 추가가 점수 변화를 일으켰다고 단정하지 않는다. 두 지표는 검색 근거 충실도와 질문 관련성이다. 사실 정확성이나 사전 정의의 필수 요소 포함률을 직접 측정한 결과는 아니다.

낮은 점수의 예로 Q074는 Faithfulness **0.1429**, AnswerRelevancy **0.0**이다. 자동 점수를 오답 확정으로 해석하지 말고 문항의 답변·검색 근거를 별도 검토한다.

## 파일과 재실행

- 원시 답변·검색 원문: `eval_outputs/08_three_source_ragas/full_samples.jsonl`
- 문항별 판정: `eval_outputs/08_three_source_ragas/full_scores.jsonl`
- 전체 요약: `eval_outputs/08_three_source_ragas/full_summary.json`
- 전체 CSV와 0.7 미만 CSV: 같은 폴더의 `full_results.csv`, `full_below_0_7.csv`
- 평가 코드 및 재실행 명령: `scripts/evaluate_ragas.py`, `GUIDE/RAGAS_EVAL.md`

`eval_outputs/`는 질문·답변·검색 원문이 있어 Git에서 무시한다. 팀에 공유할 때 필요한 파일만 검토해 전달한다.
