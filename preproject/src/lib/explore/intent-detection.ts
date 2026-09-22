const SESSION_END_PATTERNS = [
  /이해했(어|습니다|어요|음)/,
  /알겠(어|습니다|어요|음)/,
  /그만\s*(질문|물어|할게|할래)/,
  /다\s*이해/,
  /충분(해|합니다|해요)/,
  /고마(워|워요|습니다)/,
  /감사(합니다|해요)/,
  /됐(어|습니다|어요)/,
  /질문\s*없(어|습니다)/,
  /더\s*이상\s*(질문|궁금)/,
  /이제\s*(알|이해|됐)/,
  /설명\s*감사/,
  /잘\s*알겠/,
];

export function detectSessionEnd(message: string): boolean {
  const normalized = message.trim().toLowerCase();
  if (!normalized) return false;
  return SESSION_END_PATTERNS.some((pattern) => pattern.test(normalized));
}

export function buildConversationSummary(messages: { role: string; content: string }[]): string {
  return messages
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m) => `${m.role === "user" ? "학습자" : "튜터"}: ${m.content}`)
    .join("\n\n");
}
