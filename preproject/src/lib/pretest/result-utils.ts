import type {
  CategoryScoreSummary,
  PreTestResultDetail,
} from "./types";

export function buildCategoryScoresFromDetails(
  details: PreTestResultDetail[]
): CategoryScoreSummary[] {
  const categoryMap = new Map<string, { correct: number; total: number }>();

  for (const detail of details) {
    const current = categoryMap.get(detail.categoryLabel) ?? {
      correct: 0,
      total: 0,
    };
    current.total += 1;
    if (detail.isCorrect) current.correct += 1;
    categoryMap.set(detail.categoryLabel, current);
  }

  return [...categoryMap.entries()]
    .map(([categoryLabel, stats]) => ({
      categoryLabel,
      correct: stats.correct,
      total: stats.total,
      rate: Math.round((stats.correct / stats.total) * 100),
    }))
    .sort((a, b) => a.categoryLabel.localeCompare(b.categoryLabel, "ko"));
}

export interface StoredPreTestResult {
  id: string;
  total_score: number;
  details: PreTestResultDetail[];
  created_at: string;
}

export function summarizeStoredResult(result: StoredPreTestResult) {
  const details = result.details ?? [];
  const totalQuestions = details.length;
  const correctCount = result.total_score;
  const wrongCount = totalQuestions - correctCount;
  const rate =
    totalQuestions > 0
      ? Math.round((correctCount / totalQuestions) * 100)
      : 0;

  return {
    totalQuestions,
    correctCount,
    wrongCount,
    rate,
    categoryScores: buildCategoryScoresFromDetails(details),
    testedAt: new Date(result.created_at).toLocaleDateString("ko-KR", {
      year: "numeric",
      month: "long",
      day: "numeric",
    }),
  };
}
