-- =========================================================
-- 금융 교육 챗봇 - 키워드 마스터 테이블 & Seed 데이터
-- 분야: credit(신용관리), product(상품이해), market(시장분석)
-- 난이도: beginner(초급) / intermediate(중급) / advanced(고급)
-- =========================================================

CREATE TABLE IF NOT EXISTS finance_keywords (
    id INT PRIMARY KEY AUTO_INCREMENT,
    category ENUM('credit', 'product', 'market') NOT NULL,
    keyword VARCHAR(100) NOT NULL,
    difficulty ENUM('beginner', 'intermediate', 'advanced') NOT NULL DEFAULT 'beginner',
    description VARCHAR(255) NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE INDEX idx_finance_keywords_category ON finance_keywords (category);
CREATE INDEX idx_finance_keywords_category_active ON finance_keywords (category, is_active);

-- =========================================================
-- 1. 신용관리 (credit) - 50개
-- =========================================================
INSERT INTO finance_keywords (category, keyword, difficulty) VALUES
('credit', '신용점수', 'beginner'),
('credit', '신용등급', 'beginner'),
('credit', '신용조회', 'beginner'),
('credit', '신용카드 발급 조건', 'beginner'),
('credit', '체크카드 vs 신용카드', 'beginner'),
('credit', '연체', 'beginner'),
('credit', '연체이자', 'beginner'),
('credit', '신용회복위원회', 'intermediate'),
('credit', '개인회생', 'advanced'),
('credit', '개인파산', 'advanced'),
('credit', '대출한도', 'intermediate'),
('credit', 'DSR(총부채원리금상환비율)', 'advanced'),
('credit', 'DTI(총부채상환비율)', 'advanced'),
('credit', 'LTV(담보인정비율)', 'advanced'),
('credit', '신용대출', 'beginner'),
('credit', '담보대출', 'intermediate'),
('credit', '학자금대출', 'beginner'),
('credit', '마이너스통장', 'intermediate'),
('credit', '카드론', 'intermediate'),
('credit', '현금서비스', 'intermediate'),
('credit', '리볼빙', 'advanced'),
('credit', '채무불이행', 'intermediate'),
('credit', '금융질서문란자(블랙리스트)', 'advanced'),
('credit', '신용정보회사', 'intermediate'),
('credit', '신용카드 한도', 'beginner'),
('credit', '할부거래', 'beginner'),
('credit', '선불카드', 'beginner'),
('credit', '후불교통카드', 'beginner'),
('credit', '카드 이용대금 명세서', 'beginner'),
('credit', '최소결제금액', 'intermediate'),
('credit', '신용카드 실적', 'intermediate'),
('credit', '신용카드 혜택 비교', 'beginner'),
('credit', '연회비', 'beginner'),
('credit', '카드 포인트 활용', 'beginner'),
('credit', '신용점수 올리는 법', 'beginner'),
('credit', '소액생계비대출', 'intermediate'),
('credit', '청년전용 대출상품', 'beginner'),
('credit', '보증인', 'intermediate'),
('credit', '공동명의', 'intermediate'),
('credit', '급여압류', 'advanced'),
('credit', '신용카드 해지 시 유의사항', 'intermediate'),
('credit', '신용정보 조회 기록', 'intermediate'),
('credit', '대출 이자율 비교', 'intermediate'),
('credit', '고정금리', 'beginner'),
('credit', '변동금리', 'beginner'),
('credit', '원리금균등상환', 'intermediate'),
('credit', '원금균등상환', 'intermediate'),
('credit', '만기일시상환', 'intermediate'),
('credit', '카드 부정사용 대처법', 'beginner'),
('credit', '개인정보보호', 'beginner');

-- =========================================================
-- 2. 상품이해 (product) - 50개
-- =========================================================
INSERT INTO finance_keywords (category, keyword, difficulty) VALUES
('product', '예금', 'beginner'),
('product', '적금', 'beginner'),
('product', '정기예금', 'beginner'),
('product', '정기적금', 'beginner'),
('product', '자유적금', 'beginner'),
('product', 'CMA', 'intermediate'),
('product', 'MMF', 'intermediate'),
('product', '펀드', 'intermediate'),
('product', 'ETF', 'intermediate'),
('product', '주식', 'beginner'),
('product', '채권', 'intermediate'),
('product', '보험의 기본 원리', 'beginner'),
('product', '실손의료보험', 'beginner'),
('product', '저축성보험', 'intermediate'),
('product', '종신보험', 'intermediate'),
('product', '연금보험', 'intermediate'),
('product', '개인연금', 'intermediate'),
('product', '퇴직연금(DB·DC형)', 'advanced'),
('product', 'IRP(개인형퇴직연금)', 'advanced'),
('product', '연금저축', 'intermediate'),
('product', 'ISA(개인종합자산관리계좌)', 'intermediate'),
('product', '청년도약계좌', 'beginner'),
('product', '청년희망적금', 'beginner'),
('product', '주택청약종합저축', 'beginner'),
('product', '청약가점제', 'intermediate'),
('product', '전세자금대출', 'intermediate'),
('product', '주택담보대출', 'intermediate'),
('product', '신탁상품', 'advanced'),
('product', '파생상품 기초', 'advanced'),
('product', '선물·옵션 개념', 'advanced'),
('product', '리츠(REITs)', 'advanced'),
('product', '가상자산 투자 유의점', 'intermediate'),
('product', '예금자보호제도', 'beginner'),
('product', '복리의 힘', 'beginner'),
('product', '단리 vs 복리', 'beginner'),
('product', '이자소득세', 'intermediate'),
('product', '비과세 금융상품', 'intermediate'),
('product', '세제혜택 상품', 'intermediate'),
('product', '만기환급금', 'beginner'),
('product', '보험료 산정 기준', 'intermediate'),
('product', '보장성보험', 'beginner'),
('product', '자동차보험', 'beginner'),
('product', '여행자보험', 'beginner'),
('product', '건강보험', 'beginner'),
('product', '실비보험', 'beginner'),
('product', '금융상품 약관 읽는 법', 'beginner'),
('product', '원금보장형 상품', 'intermediate'),
('product', '투자상품 위험등급', 'intermediate'),
('product', '분산투자', 'intermediate'),
('product', '적립식 투자 vs 거치식 투자', 'intermediate');

-- =========================================================
-- 3. 시장분석 (market) - 50개
-- =========================================================
INSERT INTO finance_keywords (category, keyword, difficulty) VALUES
('market', '기준금리', 'beginner'),
('market', '금리인상의 영향', 'beginner'),
('market', '금리인하의 영향', 'beginner'),
('market', '인플레이션', 'beginner'),
('market', '디플레이션', 'intermediate'),
('market', '환율의 이해', 'beginner'),
('market', '원/달러 환율', 'beginner'),
('market', '코스피(KOSPI)', 'beginner'),
('market', '코스닥(KOSDAQ)', 'beginner'),
('market', '나스닥(NASDAQ)', 'beginner'),
('market', '다우존스지수', 'intermediate'),
('market', 'S&P500', 'intermediate'),
('market', '경기침체', 'intermediate'),
('market', '경기순환', 'intermediate'),
('market', 'GDP(국내총생산)', 'beginner'),
('market', '실업률', 'beginner'),
('market', '소비자물가지수(CPI)', 'intermediate'),
('market', '경제성장률', 'beginner'),
('market', '무역수지', 'intermediate'),
('market', '경상수지', 'advanced'),
('market', '양적완화', 'advanced'),
('market', '테이퍼링', 'advanced'),
('market', '통화정책', 'intermediate'),
('market', '재정정책', 'intermediate'),
('market', '중앙은행의 역할', 'beginner'),
('market', '한국은행 금융통화위원회', 'intermediate'),
('market', '미국 연준(Fed)', 'intermediate'),
('market', '시가총액', 'beginner'),
('market', '배당수익률', 'intermediate'),
('market', '주가수익비율(PER)', 'intermediate'),
('market', '주가순자산비율(PBR)', 'intermediate'),
('market', '주가 변동성', 'intermediate'),
('market', '기업 상장(IPO)', 'intermediate'),
('market', '공모주 청약', 'intermediate'),
('market', '애널리스트 리포트 보는 법', 'advanced'),
('market', '매수세·매도세', 'beginner'),
('market', '강세장(불장)', 'beginner'),
('market', '약세장(베어마켓)', 'beginner'),
('market', '자산 버블', 'intermediate'),
('market', '원자재 가격', 'intermediate'),
('market', '국제 유가', 'intermediate'),
('market', '금 시세', 'beginner'),
('market', '부동산 시장 동향', 'beginner'),
('market', '전세가율', 'intermediate'),
('market', '미분양 주택', 'intermediate'),
('market', '산업별 시장 동향', 'intermediate'),
('market', '글로벌 공급망', 'advanced'),
('market', '지정학적 리스크', 'advanced'),
('market', '경제지표 발표 일정', 'intermediate'),
('market', '뉴스로 시장 읽는 법', 'beginner');

-- =========================================================
-- 참고: 랜덤 추천 쿼리 예시
-- =========================================================
-- 카테고리별 랜덤 2개씩 뽑기 (MySQL 기준)
-- SELECT * FROM finance_keywords
-- WHERE category = 'credit' AND is_active = TRUE
-- ORDER BY RAND() LIMIT 2;

-- 난이도 필터링 예시 (초급 유저용)
-- SELECT * FROM finance_keywords
-- WHERE category = 'product' AND difficulty = 'beginner' AND is_active = TRUE
-- ORDER BY RAND() LIMIT 2;
