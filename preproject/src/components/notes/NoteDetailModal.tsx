"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertCircle,
  BookMarked,
  CheckCircle2,
  Loader2,
  X,
  XCircle,
} from "lucide-react";
import ChatMessageBody from "@/components/explore/ChatMessageBody";
import type { ExploreNoteDetail } from "@/lib/notes/types";
import { formatAnswerLabel } from "@/lib/notes/types";

interface NoteDetailModalProps {
  noteId: string;
  onClose: () => void;
}

export default function NoteDetailModal({ noteId, onClose }: NoteDetailModalProps) {
  const [note, setNote] = useState<ExploreNoteDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string>();

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setIsLoading(true);
      setError(undefined);
      try {
        const res = await fetch(`/api/notes/${noteId}`);
        const data = await res.json();
        if (!res.ok) {
          if (!cancelled) setError(data.error ?? "불러오기 실패");
          return;
        }
        if (!cancelled) setNote(data.note);
      } catch {
        if (!cancelled) setError("네트워크 오류가 발생했습니다.");
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [noteId]);

  const wrongQuizzes = note?.quizzes.filter((q) => !q.is_correct) ?? [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        aria-label="닫기"
        className="absolute inset-0 bg-slate-900/50"
        onClick={onClose}
      />
      <div className="relative max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white p-6 shadow-xl">
        <button
          type="button"
          onClick={onClose}
          className="absolute right-4 top-4 rounded-lg p-1 text-slate-400 hover:bg-slate-100"
        >
          <X className="h-5 w-5" />
        </button>

        {isLoading && (
          <div className="flex flex-col items-center py-16">
            <Loader2 className="h-8 w-8 animate-spin text-brand-600" />
            <p className="mt-3 text-sm text-slate-500">노트 불러오는 중...</p>
          </div>
        )}

        {error && (
          <div className="flex items-center gap-2 py-8 text-red-600">
            <AlertCircle className="h-5 w-5" />
            {error}
          </div>
        )}

        {note && !isLoading && (
          <div className="pr-6">
            <h2 className="text-xl font-bold text-slate-900">{note.title}</h2>
            <p className="mt-1 text-sm text-slate-500">
              {new Date(note.created_at).toLocaleDateString("ko-KR", {
                year: "numeric",
                month: "long",
                day: "numeric",
              })}
              · 퀴즈 {note.correct_count}/{note.total_quiz_count} 정답
            </p>

            {note.explore_questions.length > 0 && (
              <section className="mt-6">
                <h3 className="text-sm font-semibold text-slate-700">
                  탐색 질문
                </h3>
                <ul className="mt-2 space-y-2">
                  {note.explore_questions.map((q, i) => (
                    <li
                      key={`${q}-${i}`}
                      className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700"
                    >
                      {q}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <section className="mt-6">
              <h3 className="text-sm font-semibold text-slate-700">
                퀴즈 풀이 기록
              </h3>
              <div className="mt-3 space-y-4">
                {note.quizzes.map((quiz, index) => (
                  <div
                    key={quiz.id}
                    className={`rounded-xl border p-4 ${
                      quiz.is_correct
                        ? "border-green-100 bg-green-50/50"
                        : "border-red-200 bg-red-50/60"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-medium text-violet-700">
                        {index + 1}번 · {quiz.keyword}
                      </span>
                      {quiz.is_correct ? (
                        <span className="inline-flex items-center gap-1 text-xs font-semibold text-green-700">
                          <CheckCircle2 className="h-3.5 w-3.5" />
                          정답
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-xs font-semibold text-red-600">
                          <XCircle className="h-3.5 w-3.5" />
                          오답
                        </span>
                      )}
                    </div>

                    <p className="mt-2 text-sm font-medium text-slate-900">
                      {quiz.question}
                    </p>

                    {quiz.quiz_type === "multiple" && quiz.options.length > 0 && (
                      <ul className="mt-2 space-y-1 text-xs text-slate-600">
                        {quiz.options.map((opt) => (
                          <li key={opt}>{opt}</li>
                        ))}
                      </ul>
                    )}

                    <div className="mt-3 space-y-1 text-sm">
                      <p>
                        <span className="text-slate-500">내 답: </span>
                        <span
                          className={
                            quiz.is_correct
                              ? "font-medium text-green-700"
                              : "font-medium text-red-600"
                          }
                        >
                          {formatAnswerLabel(
                            quiz.quiz_type,
                            quiz.selected_answer,
                            quiz.options
                          )}
                        </span>
                      </p>
                      {!quiz.is_correct && (
                        <p>
                          <span className="text-slate-500">정답: </span>
                          <span className="font-medium text-green-700">
                            {formatAnswerLabel(
                              quiz.quiz_type,
                              quiz.correct_answer,
                              quiz.options
                            )}
                          </span>
                        </p>
                      )}
                    </div>

                    <p className="mt-2 border-t border-slate-200/80 pt-2 text-xs leading-relaxed text-slate-600">
                      {quiz.explanation}
                    </p>
                  </div>
                ))}
              </div>
            </section>

            {wrongQuizzes.length > 0 && (
              <section className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4">
                <h3 className="flex items-center gap-2 font-semibold text-red-800">
                  <BookMarked className="h-4 w-4" />
                  다시 복습하기
                </h3>
                <p className="mt-1 text-sm text-red-700/90">
                  틀린 {wrongQuizzes.length}문제를 다시 확인해 봐!
                </p>
                <ul className="mt-3 space-y-2">
                  {wrongQuizzes.map((q) => (
                    <li
                      key={q.id}
                      className="rounded-lg border border-red-100 bg-white px-3 py-2 text-sm text-red-900"
                    >
                      <span className="font-medium">{q.keyword}</span>
                      <span className="text-red-600"> — {q.question}</span>
                    </li>
                  ))}
                </ul>
                <Link
                  href="/explore"
                  className="btn-primary mt-4 inline-flex text-sm"
                  onClick={onClose}
                >
                  탐색하기에서 다시 학습하기
                </Link>
              </section>
            )}

            {note.conversation_summary && (
              <details className="mt-6">
                <summary className="cursor-pointer text-sm font-medium text-slate-500">
                  대화 요약 보기
                </summary>
                <div className="mt-2 rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
                  <ChatMessageBody
                    content={note.conversation_summary.replace(
                      /^(학습자|튜터): /gm,
                      ""
                    )}
                    variant="assistant"
                  />
                </div>
              </details>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
