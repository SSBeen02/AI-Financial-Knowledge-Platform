import { Fragment, type ReactNode } from "react";

interface ChatMessageBodyProps {
  content: string;
  variant: "user" | "assistant";
}

function parseBoldText(text: string): ReactNode[] {
  const parts: ReactNode[] = [];
  const regex = /\*\*([^*]+)\*\*/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(
        <Fragment key={`t-${key++}`}>{text.slice(lastIndex, match.index)}</Fragment>
      );
    }
    parts.push(<strong key={`b-${key++}`}>{match[1]}</strong>);
    lastIndex = regex.lastIndex;
  }

  if (lastIndex < text.length) {
    parts.push(<Fragment key={`t-${key++}`}>{text.slice(lastIndex)}</Fragment>);
  }

  return parts.length > 0 ? parts : [text];
}

export default function ChatMessageBody({
  content,
  variant,
}: ChatMessageBodyProps) {
  const isAssistant = variant === "assistant";

  return (
    <div
      className={
        isAssistant
          ? "whitespace-pre-wrap text-sm leading-relaxed [&_strong]:font-bold [&_strong]:text-blue-600"
          : "whitespace-pre-wrap text-sm leading-relaxed"
      }
    >
      {isAssistant ? parseBoldText(content) : content}
    </div>
  );
}
