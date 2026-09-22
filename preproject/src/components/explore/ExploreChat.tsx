"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  AlertCircle,
  ArrowLeft,
  BrainCircuit,
  Loader2,
  Send,
  Sparkles,
} from "lucide-react";
import QuizModal from "@/components/explore/QuizModal";
import ChatMessageBody from "@/components/explore/ChatMessageBody";
import RecommendKeywords from "@/components/explore/RecommendKeywords";
import type { ChatMessage, ExploreQuizQuestion } from "@/lib/explore/types";

interface ExploreChatProps {
  preTestScore?: number | null;
}

export default function ExploreChat({ preTestScore = null }: ExploreChatProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      role: "assistant",
      content:
        "**FinEdu** 금융 친구야! 궁금한 개념 편하게 물어봐.\n\n예를 들면 \"**복리**가 뭐야?\" \"**연말정산**은 왜 하는 거야?\" 이런 것도 OK야.\n\n혹시 **예금**이나 **신용점수**부터 알아볼까?",
    },
  ]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string>();
  const [showCompletionCard, setShowCompletionCard] = useState(false);
  const [isGeneratingQuiz, setIsGeneratingQuiz] = useState(false);
  const [quizData, setQuizData] = useState<{
    keywords: string[];
    questions: ExploreQuizQuestion[];
  } | null>(null);
  const [showQuizModal, setShowQuizModal] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const handleKeywordSelect = (prompt: string) => {
    setInput(prompt);
    inputRef.current?.focus();
  };

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading, showCompletionCard]);

  const sendMessage = async () => {
    const trimmed = input.trim();
    if (!trimmed || isLoading) return;

    const userMessage: ChatMessage = { role: "user", content: trimmed };
    const nextMessages = [...messages, userMessage];

    setMessages(nextMessages);
    setInput("");
    setError(undefined);
    setIsLoading(true);
    setShowCompletionCard(false);

    try {
      const response = await fetch("/api/explore/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: nextMessages.filter((m) => m.role !== "system"),
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        setError(data.error ?? "답변을 받지 못했습니다.");
        return;
      }

      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: data.reply },
      ]);

      if (data.isSessionEnd) {
        setShowCompletionCard(true);
      }
    } catch {
      setError(
        "Ollama 서버에 연결할 수 없습니다. Ollama 앱이 실행 중인지 확인해 주세요."
      );
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  const handleStartQuiz = async () => {
    setIsGeneratingQuiz(true);
    setError(undefined);

    try {
      const response = await fetch("/api/explore/quiz", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: messages.filter((m) => m.role !== "system"),
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        setError(data.error ?? "퀴즈 생성에 실패했습니다.");
        return;
      }

      setQuizData({
        keywords: data.keywords,
        questions: data.questions,
      });
      setShowQuizModal(true);
      setShowCompletionCard(false);
    } catch {
      setError("퀴즈 생성 중 네트워크 오류가 발생했습니다.");
    } finally {
      setIsGeneratingQuiz(false);
    }
  };

  return (
    <div className="flex min-h-[calc(100vh-8rem)] flex-col">
      <Link
        href="/main"
        className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-brand-600"
      >
        <ArrowLeft className="h-4 w-4" />
        메인 페이지로
      </Link>

      <div className="mb-4 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-100 text-violet-600">
          <Sparkles className="h-5 w-5" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-slate-900">금융지식 탐색하기</h1>
          <p className="text-sm text-slate-500">AI Q&A + 맞춤 퀴즈</p>
        </div>
      </div>

      <div className="card flex flex-1 flex-col overflow-hidden p-0">
        <div className="flex-1 space-y-4 overflow-y-auto p-4 sm:p-6">
          {messages.map((msg, index) => (
            <div
              key={`${msg.role}-${index}`}
              className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[85%] rounded-2xl px-4 py-3 ${
                  msg.role === "user"
                    ? "bg-brand-600 text-white"
                    : "bg-slate-100 text-slate-800"
                }`}
              >
                <ChatMessageBody
                  content={msg.content}
                  variant={msg.role === "user" ? "user" : "assistant"}
                />
              </div>
            </div>
          ))}

          {isLoading && (
            <div className="flex justify-start">
              <div className="flex items-center gap-2 rounded-2xl bg-slate-100 px-4 py-3 text-sm text-slate-500">
                <Loader2 className="h-4 w-4 animate-spin text-brand-600" />
                AI가 답변을 작성하고 있어요...
              </div>
            </div>
          )}

          {showCompletionCard && (
            <div className="rounded-2xl border border-violet-200 bg-gradient-to-r from-violet-50 to-brand-50 p-5">
              <div className="flex items-start gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-violet-100 text-violet-600">
                  <BrainCircuit className="h-5 w-5" />
                </div>
                <div className="flex-1">
                  <p className="font-semibold text-slate-900">
                    방금 배운 내용 정리 완료!
                  </p>
                  <p className="mt-1 text-sm text-slate-600">
                    맞춤형 퀴즈를 풀러가시겠습니까?
                  </p>
                  <button
                    type="button"
                    onClick={handleStartQuiz}
                    disabled={isGeneratingQuiz}
                    className="btn-primary mt-3 gap-2 disabled:opacity-60"
                  >
                    {isGeneratingQuiz ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" />
                        퀴즈 생성 중...
                      </>
                    ) : (
                      "맞춤형 퀴즈 풀러가기"
                    )}
                  </button>
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {error && (
          <div className="mx-4 mb-2 flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 sm:mx-6">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <div className="border-t border-slate-100 p-4 sm:p-6">
          <RecommendKeywords
            preTestScore={preTestScore}
            onSelectKeyword={handleKeywordSelect}
            disabled={isLoading}
          />
          <div className="flex gap-2">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isLoading}
              placeholder="금융 개념에 대해 질문해 보세요... (예: ETF가 뭐야?)"
              rows={2}
              className="input-field min-h-[48px] resize-none"
            />
            <button
              type="button"
              onClick={sendMessage}
              disabled={isLoading || !input.trim()}
              className="btn-primary shrink-0 self-end px-4 disabled:opacity-50"
            >
              {isLoading ? (
                <Loader2 className="h-5 w-5 animate-spin" />
              ) : (
                <Send className="h-5 w-5" />
              )}
            </button>
          </div>
          <p className="mt-2 text-xs text-slate-400">
            &quot;이해했어&quot;, &quot;고마워&quot; 등으로 대화를 마치면 맞춤 퀴즈를 추천해 드려요.
          </p>
        </div>
      </div>

      {showQuizModal && quizData && (
        <QuizModal
          questions={quizData.questions}
          keywords={quizData.keywords}
          messages={messages}
          onClose={() => setShowQuizModal(false)}
        />
      )}
    </div>
  );
}
