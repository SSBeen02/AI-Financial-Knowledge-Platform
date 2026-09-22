import { NextResponse } from "next/server";
import { buildConversationSummary } from "@/lib/explore/intent-detection";
import type { ChatMessage, ExploreQuizQuestion } from "@/lib/explore/types";
import {
  buildNoteTitle,
  extractExploreQuestions,
  type QuizAttemptInput,
} from "@/lib/notes/types";
import { createClient } from "@/utils/supabase/server";
import { isSupabaseConfigured } from "@/lib/supabase-config";

export async function GET() {
  if (!isSupabaseConfigured()) {
    return NextResponse.json({ notes: [] });
  }

  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "로그인이 필요합니다." }, { status: 401 });
  }

  const { data, error } = await supabase
    .from("explore_notes")
    .select(
      "id, title, keywords, correct_count, total_quiz_count, has_wrong_answers, created_at"
    )
    .eq("user_id", user.id)
    .order("created_at", { ascending: false });

  if (error) {
    console.error("[notes GET]", error.message);
    return NextResponse.json(
      { error: "학습노트를 불러오지 못했습니다." },
      { status: 500 }
    );
  }

  return NextResponse.json({ notes: data ?? [] });
}

export async function POST(request: Request) {
  if (!isSupabaseConfigured()) {
    return NextResponse.json(
      { error: "Supabase 설정이 필요합니다." },
      { status: 503 }
    );
  }

  let body: {
    messages?: ChatMessage[];
    keywords?: string[];
    questions?: ExploreQuizQuestion[];
    attempts?: QuizAttemptInput[];
  };

  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "잘못된 요청입니다." }, { status: 400 });
  }

  const messages = body.messages ?? [];
  const keywords = body.keywords ?? [];
  const questions = body.questions ?? [];
  const attempts = body.attempts ?? [];

  if (questions.length === 0 || attempts.length === 0) {
    return NextResponse.json(
      { error: "퀴즈와 풀이 결과가 필요합니다." },
      { status: 400 }
    );
  }

  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "로그인이 필요합니다." }, { status: 401 });
  }

  const correctCount = attempts.filter((a) => a.isCorrect).length;
  const hasWrongAnswers = attempts.some((a) => !a.isCorrect);
  const title = buildNoteTitle(keywords, messages);
  const exploreQuestions = extractExploreQuestions(messages);
  const conversationSummary = buildConversationSummary(messages);

  const { data: note, error: noteError } = await supabase
    .from("explore_notes")
    .insert({
      user_id: user.id,
      title,
      keywords,
      explore_questions: exploreQuestions,
      conversation_summary: conversationSummary,
      correct_count: correctCount,
      total_quiz_count: questions.length,
      has_wrong_answers: hasWrongAnswers,
    })
    .select("id")
    .single();

  if (noteError || !note) {
    console.error("[notes POST] note:", noteError?.message);
    return NextResponse.json(
      { error: "학습노트 저장에 실패했습니다." },
      { status: 500 }
    );
  }

  for (let i = 0; i < questions.length; i++) {
    const q = questions[i];
    const attempt = attempts.find((a) => a.questionId === q.id);

    if (!attempt) continue;

    const { data: quiz, error: quizError } = await supabase
      .from("explore_quizzes")
      .insert({
        note_id: note.id,
        sort_order: i,
        keyword: q.keyword,
        question: q.question,
        quiz_type: q.type,
        options: q.options ?? (q.type === "ox" ? ["O", "X"] : []),
        correct_answer: q.answer,
        explanation: q.explanation,
      })
      .select("id")
      .single();

    if (quizError || !quiz) {
      console.error("[notes POST] quiz:", quizError?.message);
      continue;
    }

    const { error: attemptError } = await supabase
      .from("explore_quiz_attempts")
      .insert({
        quiz_id: quiz.id,
        note_id: note.id,
        user_id: user.id,
        selected_answer: attempt.selectedAnswer,
        is_correct: attempt.isCorrect,
      });

    if (attemptError) {
      console.error("[notes POST] attempt:", attemptError.message);
    }
  }

  return NextResponse.json({
    noteId: note.id,
    message: "학습노트에 저장했어!",
  });
}
