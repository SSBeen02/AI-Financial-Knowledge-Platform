# 실제 GitHub 연결 폴더 이전 결과

- 적용일: 2026-11-09
- 저장소: C:\Github\AI-Financial-Knowledge-Platform
- 브랜치: quiz-database. 기존 HEAD bfb0d90 유지.
- main 전체 병합, 커밋, 푸시 수행 안 함.
- 퀴즈 질문 하오체·O/X 단독 보기·상황형 현대식 보기·생성 상태 안내·동적 재출제 중복 차단·위조 신원 거부를 적용함.
- 기존 사전테스트·학습노트 파일 135개의 내용 해시가 이전 과정에서 유지됨. 퀴즈 모델·DB 초기화·main 진입점은 수정하지 않음.
- 이 폴더 자체에서 퀴즈 unittest 39개 통과. 개발용 요청은 테스트에서만 DEV_MODE=true, 운영 신원 거부 검사는 DEV_MODE=false로 수행.
- 실제 HTML의 headless Chrome 화면 검사 5개 통과. API 응답은 대역 사용.
- 실제 유료 AI·운영 PostgreSQL·실제 로그인 및 최종 프론트 연동을 이번 이전 검사에서 수행한 것은 아님.
- 새 문항의 의미상 중복을 100% 보장하지 않으며, 제공 문항의 문자열 동일·근접 변형을 검사함.
- 원본 파일 백업과 이전 명세: 바탕화면 나의 경세학당/doc_qa/actual-repo-quiz-before-transfer.zip 및 actual-repo-quiz-transfer.json.