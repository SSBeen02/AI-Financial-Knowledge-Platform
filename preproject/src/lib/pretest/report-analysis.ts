import type { PreTestResultDetail } from "@/lib/pretest/types";

export interface DifficultyStats {
  difficulty: number;
  correct: number;
  total: number;
  rate: number;
}

export interface CategoryStats {
  categoryLabel: string;
  correct: number;
  total: number;
  rate: number;
}

export interface ReportAnalysisInput {
  totalQuestions: number;
  correctCount: number;
  accuracyRate: number;
  categoryStats: CategoryStats[];
  difficultyStats: DifficultyStats[];
  correctConcepts: string[];
  wrongConcepts: string[];
  details: PreTestResultDetail[];
}

export function buildReportAnalysis(
  details: PreTestResultDetail[],
  totalScore: number
): ReportAnalysisInput {
  const totalQuestions = details.length;
  const correctCount = totalScore;
  const accuracyRate =
    totalQuestions > 0
      ? Math.round((correctCount / totalQuestions) * 100)
      : 0;

  const categoryMap = new Map<string, { correct: number; total: number }>();
  const difficultyMap = new Map<number, { correct: number; total: number }>();

  for (const detail of details) {
    const cat = categoryMap.get(detail.categoryLabel) ?? {
      correct: 0,
      total: 0,
    };
    cat.total += 1;
    if (detail.isCorrect) cat.correct += 1;
    categoryMap.set(detail.categoryLabel, cat);

    const diff = difficultyMap.get(detail.difficulty) ?? {
      correct: 0,
      total: 0,
    };
    diff.total += 1;
    if (detail.isCorrect) diff.correct += 1;
    difficultyMap.set(detail.difficulty, diff);
  }

  const categoryStats = [...categoryMap.entries()]
    .map(([categoryLabel, stats]) => ({
      categoryLabel,
      correct: stats.correct,
      total: stats.total,
      rate: Math.round((stats.correct / stats.total) * 100),
    }))
    .sort((a, b) => a.categoryLabel.localeCompare(b.categoryLabel, "ko"));

  const difficultyStats = [...difficultyMap.entries()]
    .map(([difficulty, stats]) => ({
      difficulty,
      correct: stats.correct,
      total: stats.total,
      rate: Math.round((stats.correct / stats.total) * 100),
    }))
    .sort((a, b) => a.difficulty - b.difficulty);

  const correctConcepts = details
    .filter((d) => d.isCorrect)
    .map((d) => d.concept);
  const wrongConcepts = details
    .filter((d) => !d.isCorrect)
    .map((d) => d.concept);

  return {
    totalQuestions,
    correctCount,
    accuracyRate,
    categoryStats,
    difficultyStats,
    correctConcepts,
    wrongConcepts,
    details,
  };
}

export function formatAnalysisForPrompt(analysis: ReportAnalysisInput): string {
  const categoryLines = analysis.categoryStats
    .map(
      (c) =>
        `- ${c.categoryLabel}: ${c.correct}/${c.total} (${c.rate}%)`
    )
    .join("\n");

  const difficultyLines = analysis.difficultyStats
    .map(
      (d) =>
        `- 난이도 Lv.${d.difficulty}: ${d.correct}/${d.total} (${d.rate}%)`
    )
    .join("\n");

  const wrongList =
    analysis.wrongConcepts.length > 0
      ? analysis.wrongConcepts.join(", ")
      : "없음";

  const correctList =
    analysis.correctConcepts.length > 0
      ? analysis.correctConcepts.slice(0, 10).join(", ")
      : "없음";

  return `총 ${analysis.totalQuestions}문제 중 ${analysis.correctCount}문제 정답 (정답률 ${analysis.accuracyRate}%)

[카테고리별 정답률]
${categoryLines}

[난이도별 정답률]
${difficultyLines}

[맞힌 개념 (일부)]
${correctList}

[틀린 개념]
${wrongList}`;
}
