import type { LevelCharacter } from "@/lib/pretest/level-character";
import {
  formatAnalysisForPrompt,
  type ReportAnalysisInput,
} from "@/lib/pretest/report-analysis";

export const FINANCIAL_REPORT_SYSTEM_PROMPT = `당신은 FinEdu의 금융 교육 전문 분석가입니다.
사전테스트 결과를 바탕으로 청소년·사회초년생을 위한 맞춤형 금융 진단 보고서를 작성합니다.

작성 규칙:
- 반드시 한국어 존댓말로 작성하세요.
- 아래 3개 섹션 제목을 그대로 사용하고, 각 섹션마다 2~4문장으로 구체적으로 작성하세요.
- 투자 종목 추천이나 확정적 수익 보장 표현은 금지합니다.
- 격려하고 실천 가능한 학습 방향을 제시하세요.
- 마크다운 # 제목은 사용하지 말고, **굵은 글씨**만 사용할 수 있습니다.

보고서 형식:
**1. 총평**
(현재 금융 지식 수준 요약)

**2. 강점 및 약점 영역 분석**
(카테고리·난이도·정오답 패턴 기준 분석)

**3. 향후 맞춤형 금융 학습 방향 제안**
(구체적인 학습 우선순위와 방법 제안)`;

export function buildReportUserPrompt(
  analysis: ReportAnalysisInput,
  level: LevelCharacter
): string {
  return `다음 사전테스트 결과를 분석하여 맞춤형 금융 진단 보고서를 작성해 주세요.

[사용자 레벨]
${level.name} (${level.description})

[테스트 결과 데이터]
${formatAnalysisForPrompt(analysis)}`;
}

export function buildFallbackReport(
  analysis: ReportAnalysisInput,
  level: LevelCharacter
): string {
  const strongCategories = analysis.categoryStats
    .filter((c) => c.rate >= 60)
    .map((c) => c.categoryLabel);
  const weakCategories = analysis.categoryStats
    .filter((c) => c.rate < 60)
    .map((c) => c.categoryLabel);

  const easyRate =
    analysis.difficultyStats.find((d) => d.difficulty === 1)?.rate ?? 0;
  const hardRate =
    analysis.difficultyStats.find((d) => d.difficulty >= 3)?.rate ?? 0;

  const strengthText =
    strongCategories.length > 0
      ? `${strongCategories.join(", ")} 영역에서 비교적 좋은 성과를 보였습니다.`
      : "아직 모든 영역에서 기초를 다져 나가는 단계입니다.";

  const weaknessText =
    weakCategories.length > 0
      ? `${weakCategories.join(", ")} 영역은 추가 학습이 필요합니다.`
      : analysis.wrongConcepts.length > 0
        ? `틀린 개념(${analysis.wrongConcepts.slice(0, 5).join(", ")})을 중심으로 복습이 필요합니다.`
        : "전반적으로 고르게 학습하시면 좋겠습니다.";

  const learningTip =
    level.key === "baby_lion"
      ? "기초 개념(예금·적금, 신용점수, 예산 관리)부터 차근차근 학습하고, FinEdu 탐색하기에서 궁금한 키워드를 질문해 보세요."
      : level.key === "brave_lion"
        ? "약한 카테고리 문제를 다시 풀어보고, 중급 난이도 개념을 심화 학습하세요. 카테고리별 퀴즈와 AI 대화를 병행하면 효과적입니다."
        : "고급 주제와 실전 응용 문제에 도전하고, 틀린 개념은 해설을 통해 원리까지 정리해 보세요.";

  return `**1. 총평**
총 ${analysis.totalQuestions}문제 중 ${analysis.correctCount}문제를 맞혀 정답률 ${analysis.accuracyRate}%를 기록하셨습니다. 현재 레벨은 **${level.name}**으로, ${level.description}

**2. 강점 및 약점 영역 분석**
${strengthText} ${weaknessText} 쉬운 난이도(Lv.1) 정답률은 ${easyRate}%이며, 어려운 난이도 정답률은 ${hardRate}%입니다.

**3. 향후 맞춤형 금융 학습 방향 제안**
${learningTip} 매일 10~15분씩 꾸준히 학습하고, 사전테스트를 주기적으로 다시 풀어 성장을 확인해 보세요.

※ AI 서버 연결 문제로 기본 분석 템플릿이 제공되었습니다. 나중에 다시 생성해 보세요.`;
}
