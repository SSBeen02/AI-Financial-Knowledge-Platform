export interface QuizExplanation {
  correct: string;
  options_detail: string[];
}

export interface RawQuizQuestion {
  id: string;
  category: string;
  difficulty: number;
  concept: string;
  question: string;
  options: string[];
  answer: number;
  explanation: QuizExplanation;
}

export interface PreTestQuestion extends RawQuizQuestion {
  sourceFile: string;
  categoryLabel: string;
}

export interface PreTestAnswer {
  questionId: string;
  category: string;
  categoryLabel: string;
  difficulty: number;
  concept: string;
  selectedAnswer: number;
  correctAnswer: number;
  isCorrect: boolean;
}

export interface PreTestResultDetail {
  questionId: string;
  category: string;
  categoryLabel: string;
  difficulty: number;
  concept: string;
  question?: string;
  options?: string[];
  explanation?: QuizExplanation;
  selectedAnswer: number;
  correctAnswer: number;
  isCorrect: boolean;
}

export interface CategoryScoreSummary {
  categoryLabel: string;
  correct: number;
  total: number;
  rate: number;
}

export interface PreTestScoreResult {
  totalScore: number;
  totalQuestions: number;
  correctCount: number;
  wrongCount: number;
  details: PreTestResultDetail[];
  categoryScores: CategoryScoreSummary[];
}
