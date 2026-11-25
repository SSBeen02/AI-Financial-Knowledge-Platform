import { QUIZ_SOURCES } from "./quiz-sources";
import type { PreTestResultDetail, QuizExplanation } from "./types";

export function findQuestionById(questionId: string) {
  for (const source of QUIZ_SOURCES) {
    const found = source.questions.find((q) => q.id === questionId);
    if (found) return found;
  }
  return null;
}

export interface EnrichedResultDetail extends PreTestResultDetail {
  question: string;
  options: string[];
  explanation?: QuizExplanation;
  hasDetailData: boolean;
}

export function enrichResultDetail(
  detail: PreTestResultDetail
): EnrichedResultDetail {
  const lookup = findQuestionById(detail.questionId);

  const question = detail.question ?? lookup?.question ?? detail.concept;
  const options = detail.options ?? lookup?.options ?? [];
  const explanation = detail.explanation ?? lookup?.explanation;

  return {
    ...detail,
    question,
    options,
    explanation,
    hasDetailData: options.length > 0,
  };
}

export function enrichResultDetails(
  details: PreTestResultDetail[]
): EnrichedResultDetail[] {
  return details.map(enrichResultDetail);
}
