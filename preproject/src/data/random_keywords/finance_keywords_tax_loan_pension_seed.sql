-- =========================================================
-- 금융 교육 챗봇 - 키워드 마스터 테이블 & Seed 데이터 (통합)
-- 분야: tax(세금), loan(대출), pension(연금)
-- 난이도: beginner(초급) / intermediate(중급) / advanced(고급)
-- =========================================================

-- 기존 finance_keywords 테이블의 category ENUM에 값 추가 필요
-- ALTER TABLE finance_keywords MODIFY category ENUM('credit','product','market','tax','loan','pension') NOT NULL;

-- =========================================================
-- 1. 세금 (tax) - 50개
-- 출처: 국세청 「2026 세금절약 가이드 I·II」
-- =========================================================
INSERT INTO finance_keywords (category, keyword, difficulty) VALUES
('tax', '소득세', 'beginner'),
('tax', '법인세', 'intermediate'),
('tax', '부가가치세', 'beginner'),
('tax', '상속세', 'intermediate'),
('tax', '증여세', 'intermediate'),
('tax', '양도소득세', 'intermediate'),
('tax', '종합부동산세', 'intermediate'),
('tax', '취득세', 'beginner'),
('tax', '재산세', 'beginner'),
('tax', '자동차세', 'beginner'),
('tax', '개별소비세', 'intermediate'),
('tax', '인지세', 'intermediate'),
('tax', '관세', 'intermediate'),
('tax', '절세', 'beginner'),
('tax', '탈세', 'beginner'),
('tax', '조세범 처벌법', 'advanced'),
('tax', '가산세', 'intermediate'),
('tax', '사업자등록', 'beginner'),
('tax', '간이과세자', 'intermediate'),
('tax', '일반과세자', 'intermediate'),
('tax', '세금계산서', 'beginner'),
('tax', '전자세금계산서', 'beginner'),
('tax', '현금영수증 발급의무화', 'beginner'),
('tax', '종합소득세 확정신고', 'intermediate'),
('tax', '원천징수', 'intermediate'),
('tax', '원천세 신고·납부', 'intermediate'),
('tax', '근로소득 연말정산', 'beginner'),
('tax', '소득공제', 'beginner'),
('tax', '세액공제', 'beginner'),
('tax', '신용카드 등 사용액 소득공제', 'beginner'),
('tax', '의료비 세액공제', 'beginner'),
('tax', '교육비 세액공제', 'beginner'),
('tax', '보험료 세액공제', 'beginner'),
('tax', '연금계좌 세액공제', 'intermediate'),
('tax', '주택자금 소득공제', 'intermediate'),
('tax', '월세액 세액공제', 'beginner'),
('tax', '퇴직소득세', 'intermediate'),
('tax', '근로장려금', 'beginner'),
('tax', '자녀장려금', 'beginner'),
('tax', '취업 후 학자금 상환제도(ICL)', 'intermediate'),
('tax', '1세대 1주택 비과세', 'intermediate'),
('tax', '장기보유특별공제', 'advanced'),
('tax', '간주임대료', 'advanced'),
('tax', '상속세 세금계산 구조', 'advanced'),
('tax', '배우자 상속공제', 'advanced'),
('tax', '가업상속공제', 'advanced'),
('tax', '동거주택 상속공제', 'advanced'),
('tax', '증여재산공제', 'intermediate'),
('tax', '부담부증여', 'advanced'),
('tax', '경정청구', 'intermediate'),
('tax', '납세자권리구제(불복청구)', 'advanced');

-- =========================================================
-- 2. 대출 (loan) - 50개
-- 출처: 한국은행 「2026 경제금융용어 800선」
-- =========================================================
INSERT INTO finance_keywords (category, keyword, difficulty) VALUES
('loan', '가산금리', 'beginner'),
('loan', '고정금리', 'beginner'),
('loan', '변동금리', 'beginner'),
('loan', '담보인정비율(LTV)', 'beginner'),
('loan', '모기지대출', 'beginner'),
('loan', '채무불이행', 'beginner'),
('loan', '예대금리차(예대마진)', 'beginner'),
('loan', '기준금리', 'beginner'),
('loan', '가계신용통계', 'beginner'),
('loan', '총부채상환비율(DTI)', 'intermediate'),
('loan', '총부채원리금상환비율(DSR)', 'intermediate'),
('loan', '역모기지론', 'intermediate'),
('loan', '집단대출', 'intermediate'),
('loan', '채무상환유예(Moratorium)', 'intermediate'),
('loan', '신용위험(신용리스크)', 'intermediate'),
('loan', '신용경색', 'intermediate'),
('loan', '신용평가제도', 'intermediate'),
('loan', '여신전문금융회사', 'intermediate'),
('loan', 'P2P대출', 'intermediate'),
('loan', '명목금리/실질금리', 'intermediate'),
('loan', '표면금리', 'intermediate'),
('loan', '장단기금리차', 'intermediate'),
('loan', '국가채무', 'intermediate'),
('loan', '정책모기지/주택 정책대출', 'intermediate'),
('loan', '스트레스 DSR', 'advanced'),
('loan', '지분형 모기지', 'advanced'),
('loan', '신용스프레드', 'advanced'),
('loan', '신용레버리지', 'advanced'),
('loan', '신용창조', 'advanced'),
('loan', '신용파생상품', 'advanced'),
('loan', '신용연계증권(CLN)', 'advanced'),
('loan', '신용환산율', 'advanced'),
('loan', '고정이하여신비율', 'advanced'),
('loan', '동일인 신용공여한도제(동일인 여신한도제)', 'advanced'),
('loan', '대출금 출자전환', 'advanced'),
('loan', '대출채권 분할매각', 'advanced'),
('loan', '금융중개지원대출제도', 'advanced'),
('loan', '일중당좌대출제도', 'advanced'),
('loan', '금리선물', 'advanced'),
('loan', '금리스왑', 'advanced'),
('loan', '금리자유화', 'advanced'),
('loan', '금리평가이론', 'advanced'),
('loan', '무위험지표금리(KOFR)', 'advanced'),
('loan', '고정금리부채권(SB)', 'advanced'),
('loan', '변동금리부채권(FRN)', 'advanced'),
('loan', '커버드본드(이중상환청구권부 채권)', 'advanced'),
('loan', '우발부채(채무)', 'advanced'),
('loan', '원금리스크', 'advanced'),
('loan', '유동성 함정', 'advanced'),
('loan', '사전담보제', 'advanced');

-- =========================================================
-- 3. 연금 (pension) - 50개
-- 출처: 「대학생을 위한 실용금융」 제9장(노후와 연금)
-- =========================================================
INSERT INTO finance_keywords (category, keyword, difficulty) VALUES
('pension', '초고령사회', 'beginner'),
('pension', '고령화사회', 'beginner'),
('pension', '고령사회', 'beginner'),
('pension', '고령인구 구성비', 'intermediate'),
('pension', '기대수명', 'beginner'),
('pension', '기대여명', 'intermediate'),
('pension', '건강수명', 'beginner'),
('pension', '행복수명', 'intermediate'),
('pension', '노인빈곤율', 'intermediate'),
('pension', '다층노후소득보장체계', 'intermediate'),
('pension', '3층 보장체계', 'intermediate'),
('pension', '0층 연금제도', 'advanced'),
('pension', '기초연금제도', 'beginner'),
('pension', '기초연금 선정기준액', 'intermediate'),
('pension', '퇴직연금제도', 'beginner'),
('pension', '확정급여형 퇴직연금(DB)', 'intermediate'),
('pension', '확정기여형 퇴직연금(DC)', 'intermediate'),
('pension', '개인형 퇴직연금(IRP)', 'intermediate'),
('pension', '개인연금제도', 'beginner'),
('pension', '주택연금제도(역모기지)', 'intermediate'),
('pension', '농지연금제도', 'advanced'),
('pension', '국민연금', 'beginner'),
('pension', '노령연금', 'beginner'),
('pension', '조기노령연금', 'intermediate'),
('pension', '국민연금 보험료율', 'intermediate'),
('pension', '사업장가입자', 'intermediate'),
('pension', '지역가입자', 'intermediate'),
('pension', '임의가입자', 'intermediate'),
('pension', '추후납입제도', 'advanced'),
('pension', '납부예외', 'advanced'),
('pension', '연금소득대체율', 'advanced'),
('pension', '연금저축', 'beginner'),
('pension', '연금저축신탁', 'intermediate'),
('pension', '연금저축보험', 'intermediate'),
('pension', '연금저축펀드', 'intermediate'),
('pension', '연금보험', 'beginner'),
('pension', '연금계좌 세액공제 한도', 'intermediate'),
('pension', '연금소득세', 'intermediate'),
('pension', '기타소득세(연금 중도해지)', 'advanced'),
('pension', '보험차익 비과세', 'advanced'),
('pension', '통합연금포털', 'beginner'),
('pension', '노후생활자금', 'beginner'),
('pension', '최소 생활비', 'beginner'),
('pension', '적정 생활비', 'beginner'),
('pension', '종신연금', 'intermediate'),
('pension', '확정기간형연금', 'intermediate'),
('pension', '연금계좌 이체제도', 'intermediate'),
('pension', '장기간병보험', 'intermediate'),
('pension', '치매간병보험', 'intermediate'),
('pension', '노인장기요양보험', 'intermediate'),
('pension', '연금 3층 구조', 'beginner');

-- =========================================================
-- 참고: 랜덤 추천 쿼리 예시
-- =========================================================
-- SELECT * FROM finance_keywords
-- WHERE category = 'tax' AND is_active = TRUE
-- ORDER BY RAND() LIMIT 2;

-- SELECT * FROM finance_keywords
-- WHERE category = 'loan' AND is_active = TRUE
-- ORDER BY RAND() LIMIT 2;

-- SELECT * FROM finance_keywords
-- WHERE category = 'pension' AND is_active = TRUE
-- ORDER BY RAND() LIMIT 2;
