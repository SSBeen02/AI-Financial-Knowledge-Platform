import type {
  CategoryScoreSummary,
  PreTestAnswer,
  PreTestQuestion,
  PreTestResultDetail,
  PreTestScoreResult,
} from "./types";

export function calculatePreTestScore(
  questions: PreTestQuestion[],
  answers: PreTestAnswer[]
): PreTestScoreResult {
  const answerMap = new Map(answers.map((a) => [a.questionId, a]));

  const details: PreTestResultDetail[] = questions.map((q) => {
    const answer = answerMap.get(q.id);
    const selectedAnswer = answer?.selectedAnswer ?? 0;
    const isCorrect = selectedAnswer === q.answer;

    return {
      questionId: q.id,
      category: q.category,
      categoryLabel: q.categoryLabel,
      difficulty: q.difficulty,
      concept: q.concept,
      question: q.question,
      options: q.options,
      explanation: q.explanation,
      selectedAnswer,
      correctAnswer: q.answer,
      isCorrect,
    };
  });

  const correctCount = details.filter((d) => d.isCorrect).length;
  const wrongCount = details.length - correctCount;

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

  const categoryScores: CategoryScoreSummary[] = [...categoryMap.entries()]
    .map(([categoryLabel, stats]) => ({
      categoryLabel,
      correct: stats.correct,
      total: stats.total,
      rate: Math.round((stats.correct / stats.total) * 100),
    }))
    .sort((a, b) => a.categoryLabel.localeCompare(b.categoryLabel, "ko"));

  return {
    totalScore: correctCount,
    totalQuestions: details.length,
    correctCount,
    wrongCount,
    details,
    categoryScores,
  };
}
