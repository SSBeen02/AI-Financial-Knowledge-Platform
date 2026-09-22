import type { ChatMessage, ExploreQuizQuestion } from "@/lib/explore/types";
import { buildConversationSummary } from "@/lib/explore/intent-detection";

export interface QuizAttemptInput {
  questionId: string;
  selectedAnswer: number | boolean;
  isCorrect: boolean;
}

export interface SaveNotePayload {
  messages: ChatMessage[];
  keywords: string[];
  questions: ExploreQuizQuestion[];
  attempts: QuizAttemptInput[];
}

export interface ExploreNoteListItem {
  id: string;
  title: string;
  keywords: string[];
  correct_count: number;
  total_quiz_count: number;
  has_wrong_answers: boolean;
  created_at: string;
}

export interface ExploreNoteQuizDetail {
  id: string;
  sort_order: number;
  keyword: string;
  question: string;
  quiz_type: "multiple" | "ox";
  options: string[];
  correct_answer: number | boolean;
  explanation: string;
  selected_answer: number | boolean;
  is_correct: boolean;
}

export interface ExploreNoteDetail extends ExploreNoteListItem {
  explore_questions: string[];
  conversation_summary: string | null;
  quizzes: ExploreNoteQuizDetail[];
}

export function buildNoteTitle(
  keywords: string[],
  messages: ChatMessage[]
): string {
  if (keywords.length > 0) {
    return keywords.slice(0, 3).join(" · ");
  }

  const firstUser = messages.find((m) => m.role === "user");
  if (firstUser?.content) {
    const trimmed = firstUser.content.trim();
    return trimmed.length > 40 ? `${trimmed.slice(0, 40)}…` : trimmed;
  }

  return "금융 탐색 학습";
}

export function extractExploreQuestions(messages: ChatMessage[]): string[] {
  return messages
    .filter((m) => m.role === "user")
    .map((m) => m.content.trim())
    .filter(Boolean);
}

export function buildNoteSummary(messages: ChatMessage[]): string {
  return buildConversationSummary(messages);
}

export function formatAnswerLabel(
  type: "multiple" | "ox",
  answer: number | boolean,
  options?: string[]
): string {
  if (type === "ox") {
    return answer === true ? "O" : "X";
  }

  const index = typeof answer === "number" ? answer - 1 : Number(answer) - 1;
  if (options && options[index]) {
    return options[index];
  }
  return `${answer}번`;
}
