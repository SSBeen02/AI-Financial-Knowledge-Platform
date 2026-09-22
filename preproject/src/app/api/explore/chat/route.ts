import { NextResponse } from "next/server";
import { detectSessionEnd } from "@/lib/explore/intent-detection";
import { FINANCE_TUTOR_SYSTEM_PROMPT } from "@/lib/explore/prompts";
import { sanitizeChatReply } from "@/lib/explore/sanitize-chat-reply";
import type { ChatMessage } from "@/lib/explore/types";
import { OllamaConnectionError, ollamaChat } from "@/lib/ollama/client";

export async function POST(request: Request) {
  let body: { messages?: ChatMessage[] };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "잘못된 요청입니다." }, { status: 400 });
  }

  const history = body.messages ?? [];
  const lastUserMessage = [...history]
    .reverse()
    .find((m) => m.role === "user");

  if (!lastUserMessage?.content?.trim()) {
    return NextResponse.json(
      { error: "질문을 입력해 주세요." },
      { status: 400 }
    );
  }

  const isSessionEnd = detectSessionEnd(lastUserMessage.content);

  const ollamaMessages: ChatMessage[] = [
    { role: "system", content: FINANCE_TUTOR_SYSTEM_PROMPT },
    ...history.filter((m) => m.role === "user" || m.role === "assistant"),
  ];

  try {
    const reply = sanitizeChatReply(await ollamaChat(ollamaMessages));

    return NextResponse.json({
      reply,
      isSessionEnd,
    });
  } catch (error) {
    if (error instanceof OllamaConnectionError) {
      return NextResponse.json({ error: error.message }, { status: 503 });
    }
    console.error("[explore/chat]", error);
    return NextResponse.json(
      { error: "답변 생성 중 오류가 발생했습니다." },
      { status: 500 }
    );
  }
}
