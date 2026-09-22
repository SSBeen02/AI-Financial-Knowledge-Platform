import { NextResponse } from "next/server";
import {
  buildConversationSummary,
} from "@/lib/explore/intent-detection";
import { KEYWORD_QUIZ_PROMPT } from "@/lib/explore/prompts";
import type { ChatMessage, ExploreQuizQuestion } from "@/lib/explore/types";
import { OllamaConnectionError, ollamaChat } from "@/lib/ollama/client";

function parseQuizJson(raw: string): {
  keywords: string[];
  questions: ExploreQuizQuestion[];
} {
  const jsonMatch = raw.match(/\{[\s\S]*\}/);
  if (!jsonMatch) {
    throw new Error("JSON parse failed");
  }

  const parsed = JSON.parse(jsonMatch[0]) as {
    keywords?: string[];
    questions?: ExploreQuizQuestion[];
  };

  const keywords = (parsed.keywords ?? []).slice(0, 5);
  const questions = (parsed.questions ?? []).slice(0, 3).map((q, i) => ({
    id: q.id ?? `eq_${i + 1}`,
    keyword: q.keyword ?? keywords[i] ?? "금융 개념",
    question: q.question,
    type: q.type === "ox" ? "ox" : "multiple",
    options: q.options,
    answer: q.answer,
    explanation: q.explanation ?? "",
  })) as ExploreQuizQuestion[];

  if (questions.length === 0) {
    throw new Error("No questions generated");
  }

  return { keywords, questions };
}

export async function POST(request: Request) {
  let body: { messages?: ChatMessage[] };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "잘못된 요청입니다." }, { status: 400 });
  }

  const history = body.messages ?? [];
  if (history.length === 0) {
    return NextResponse.json(
      { error: "대화 내용이 없습니다." },
      { status: 400 }
    );
  }

  const summary = buildConversationSummary(history);

  const ollamaMessages: ChatMessage[] = [
    { role: "system", content: KEYWORD_QUIZ_PROMPT },
    {
      role: "user",
      content: `다음은 학습자와 AI 튜터의 대화입니다:\n\n${summary}`,
    },
  ];

  try {
    const raw = await ollamaChat(ollamaMessages, { json: true });
    const { keywords, questions } = parseQuizJson(raw);

    return NextResponse.json({ keywords, questions });
  } catch (error) {
    if (error instanceof OllamaConnectionError) {
      return NextResponse.json({ error: error.message }, { status: 503 });
    }
    console.error("[explore/quiz]", error);
    return NextResponse.json(
      { error: "퀴즈 생성 중 오류가 발생했습니다. 다시 시도해 주세요." },
      { status: 500 }
    );
  }
}
