import { NextResponse } from "next/server";
import type { ExploreNoteDetail, ExploreNoteQuizDetail } from "@/lib/notes/types";
import { createClient } from "@/utils/supabase/server";
import { isSupabaseConfigured } from "@/lib/supabase-config";

interface RouteParams {
  params: Promise<{ id: string }>;
}

export async function GET(_request: Request, { params }: RouteParams) {
  const { id } = await params;

  if (!isSupabaseConfigured()) {
    return NextResponse.json(
      { error: "Supabase 설정이 필요합니다." },
      { status: 503 }
    );
  }

  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "로그인이 필요합니다." }, { status: 401 });
  }

  const { data: note, error: noteError } = await supabase
    .from("explore_notes")
    .select("*")
    .eq("id", id)
    .eq("user_id", user.id)
    .maybeSingle();

  if (noteError || !note) {
    return NextResponse.json(
      { error: "학습노트를 찾을 수 없습니다." },
      { status: 404 }
    );
  }

  const { data: quizzes } = await supabase
    .from("explore_quizzes")
    .select("*")
    .eq("note_id", id)
    .order("sort_order", { ascending: true });

  const { data: attempts } = await supabase
    .from("explore_quiz_attempts")
    .select("*")
    .eq("note_id", id);

  const attemptMap = new Map(
    (attempts ?? []).map((a) => [a.quiz_id as string, a])
  );

  const quizDetails: ExploreNoteQuizDetail[] = (quizzes ?? []).map((q) => {
    const attempt = attemptMap.get(q.id as string);
    return {
      id: q.id as string,
      sort_order: q.sort_order as number,
      keyword: q.keyword as string,
      question: q.question as string,
      quiz_type: q.quiz_type as "multiple" | "ox",
      options: (q.options as string[]) ?? [],
      correct_answer: q.correct_answer as number | boolean,
      explanation: q.explanation as string,
      selected_answer: (attempt?.selected_answer ?? q.correct_answer) as
        | number
        | boolean,
      is_correct: (attempt?.is_correct ?? false) as boolean,
    };
  });

  const detail: ExploreNoteDetail = {
    id: note.id as string,
    title: note.title as string,
    keywords: (note.keywords as string[]) ?? [],
    correct_count: note.correct_count as number,
    total_quiz_count: note.total_quiz_count as number,
    has_wrong_answers: note.has_wrong_answers as boolean,
    created_at: note.created_at as string,
    explore_questions: (note.explore_questions as string[]) ?? [],
    conversation_summary: (note.conversation_summary as string) ?? null,
    quizzes: quizDetails,
  };

  return NextResponse.json({ note: detail });
}
