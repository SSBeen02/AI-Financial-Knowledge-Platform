export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

export interface ExploreQuizQuestion {
  id: string;
  keyword: string;
  question: string;
  type: "multiple" | "ox";
  options?: string[];
  answer: number | boolean;
  explanation: string;
}

export interface ChatResponse {
  reply: string;
  isSessionEnd: boolean;
  error?: string;
}

export interface QuizResponse {
  keywords: string[];
  questions: ExploreQuizQuestion[];
  error?: string;
}
