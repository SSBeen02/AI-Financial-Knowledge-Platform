/**
 * LLM 채팅 응답을 UI 렌더링에 맞게 정규화합니다.
 * **볼드**와 대시(-) 목록, 줄바꿈은 유지하고 불필요한 마크다운만 제거합니다.
 */
export function normalizeChatReply(text: string): string {
  let result = text;

  // 코드 블록 — 내용만 남김
  result = result.replace(/```[\s\S]*?```/g, (block) =>
    block.replace(/```\w*\n?/g, "").replace(/```/g, "").trim()
  );
  result = result.replace(/`([^`]+)`/g, "$1");

  // 제목(#) — 텍스트만 남김
  result = result.replace(/^#{1,6}\s+/gm, "");

  // 기울임(*, _) — 볼드(**)는 유지
  result = result.replace(/(?<!\*)\*(?!\*)([^*\n]+?)(?<!\*)\*(?!\*)/g, "$1");
  result = result.replace(/_([^_\n]+?)_/g, "$1");

  // 인용(>)
  result = result.replace(/^>\s+/gm, "");

  // 숫자 목록 → 대시 목록으로 통일
  result = result.replace(/^[\t ]*\d+\.\s+/gm, "- ");

  // 줄 끝 공백 제거
  result = result.replace(/[ \t]+\n/g, "\n");
  result = result.replace(/\r\n/g, "\n");

  // 과도한 빈 줄 정리
  result = result.replace(/\n{3,}/g, "\n\n");

  return result.trim();
}

/** @deprecated normalizeChatReply 사용 */
export const sanitizeChatReply = normalizeChatReply;
