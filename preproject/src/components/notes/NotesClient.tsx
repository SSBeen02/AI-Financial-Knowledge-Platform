"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Archive,
  ArrowLeft,
  BookOpen,
  Calendar,
  CheckCircle2,
  Loader2,
  XCircle,
} from "lucide-react";
import NoteDetailModal from "@/components/notes/NoteDetailModal";
import type { ExploreNoteListItem } from "@/lib/notes/types";

interface NotesClientProps {
  initialNotes: ExploreNoteListItem[];
}

export default function NotesClient({ initialNotes }: NotesClientProps) {
  const [notes, setNotes] = useState(initialNotes);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const refreshNotes = useCallback(async () => {
    const res = await fetch("/api/notes");
    if (res.ok) {
      const data = await res.json();
      setNotes(data.notes ?? []);
    }
  }, []);

  useEffect(() => {
    refreshNotes();
  }, [refreshNotes]);

  return (
    <>
      <Link
        href="/main"
        className="mb-8 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-brand-600"
      >
        <ArrowLeft className="h-4 w-4" />
        메인 페이지로
      </Link>

      <div className="mb-8 flex items-center gap-3">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-100 text-emerald-600">
          <Archive className="h-6 w-6" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-slate-900">학습노트</h1>
          <p className="text-sm text-slate-500">탐색한 금융 지식과 퀴즈 기록</p>
        </div>
      </div>

      {notes.length === 0 ? (
        <div className="card text-center">
          <BookOpen className="mx-auto h-10 w-10 text-slate-300" />
          <p className="mt-4 font-medium text-slate-800">
            아직 저장된 학습노트가 없어
          </p>
          <p className="mt-2 text-sm text-slate-500">
            금융지식 탐색하기에서 대화 후 맞춤 퀴즈를 풀면 여기에 자동 저장돼!
          </p>
          <Link href="/explore" className="btn-primary mt-6 inline-flex">
            탐색하러 가기
          </Link>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {notes.map((note) => {
            const date = new Date(note.created_at).toLocaleDateString("ko-KR", {
              year: "numeric",
              month: "long",
              day: "numeric",
            });
            const allCorrect =
              !note.has_wrong_answers &&
              note.correct_count === note.total_quiz_count;

            return (
              <button
                key={note.id}
                type="button"
                onClick={() => setSelectedId(note.id)}
                className="card text-left transition hover:border-brand-200 hover:shadow-md"
              >
                <div className="flex items-start justify-between gap-2">
                  <h2 className="font-semibold text-slate-900 line-clamp-2">
                    {note.title}
                  </h2>
                  {allCorrect ? (
                    <span className="shrink-0 rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-700">
                      전부 정답
                    </span>
                  ) : note.has_wrong_answers ? (
                    <span className="shrink-0 rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-700">
                      오답 포함
                    </span>
                  ) : null}
                </div>

                <div className="mt-3 flex flex-wrap gap-1.5">
                  {note.keywords.slice(0, 4).map((kw) => (
                    <span
                      key={kw}
                      className="rounded-full bg-violet-50 px-2 py-0.5 text-xs text-violet-700"
                    >
                      {kw}
                    </span>
                  ))}
                </div>

                <div className="mt-4 flex items-center justify-between text-sm text-slate-500">
                  <span className="inline-flex items-center gap-1">
                    <Calendar className="h-3.5 w-3.5" />
                    {date}
                  </span>
                  <span className="inline-flex items-center gap-1 font-medium text-brand-700">
                    {note.has_wrong_answers ? (
                      <XCircle className="h-3.5 w-3.5 text-red-400" />
                    ) : (
                      <CheckCircle2 className="h-3.5 w-3.5 text-green-500" />
                    )}
                    {note.correct_count}/{note.total_quiz_count} 정답
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      )}

      {selectedId && (
        <NoteDetailModal
          noteId={selectedId}
          onClose={() => setSelectedId(null)}
        />
      )}
    </>
  );
}
