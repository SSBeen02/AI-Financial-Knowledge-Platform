import { NextResponse } from "next/server";
import { getLevelFromScore } from "@/lib/pretest/level-character";
import { buildReportAnalysis } from "@/lib/pretest/report-analysis";
import {
  buildFallbackReport,
  buildReportUserPrompt,
  FINANCIAL_REPORT_SYSTEM_PROMPT,
} from "@/lib/pretest/report-prompt";
import type { PreTestResultDetail } from "@/lib/pretest/types";
import type { ChatMessage } from "@/lib/explore/types";
import { OllamaConnectionError, ollamaChat } from "@/lib/ollama/client";
import { createClient } from "@/utils/supabase/server";
import { isSupabaseConfigured } from "@/lib/supabase-config";

async function getAuthorizedResult(resultId: string) {
  if (!isSupabaseConfigured()) {
    return { error: "Supabase 설정이 필요합니다.", status: 503 as const };
  }

  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return { error: "로그인이 필요합니다.", status: 401 as const };
  }

  const { data: result, error } = await supabase
    .from("pre_test_results")
    .select("id, user_id, total_score, details, created_at")
    .eq("id", resultId)
    .eq("user_id", user.id)
    .maybeSingle();

  if (error || !result) {
    return { error: "사전테스트 결과를 찾을 수 없습니다.", status: 404 as const };
  }

  return { user, result, supabase };
}

export async function GET(request: Request) {
  const resultId = new URL(request.url).searchParams.get("resultId");

  if (!resultId) {
    return NextResponse.json(
      { error: "resultId가 필요합니다." },
      { status: 400 }
    );
  }

  const auth = await getAuthorizedResult(resultId);
  if ("error" in auth) {
    return NextResponse.json({ error: auth.error }, { status: auth.status });
  }

  const { data: existing } = await auth.supabase
    .from("financial_reports")
    .select("*")
    .eq("pre_test_result_id", resultId)
    .maybeSingle();

  if (!existing) {
    return NextResponse.json({ report: null }, { status: 200 });
  }

  return NextResponse.json({ report: existing });
}

export async function POST(request: Request) {
  let body: { resultId?: string; force?: boolean };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "잘못된 요청입니다." }, { status: 400 });
  }

  const { resultId, force = false } = body;

  if (!resultId) {
    return NextResponse.json(
      { error: "resultId가 필요합니다." },
      { status: 400 }
    );
  }

  const auth = await getAuthorizedResult(resultId);
  if ("error" in auth) {
    return NextResponse.json({ error: auth.error }, { status: auth.status });
  }

  const { result, supabase, user } = auth;
  const details = (result.details ?? []) as PreTestResultDetail[];

  if (!force) {
    const { data: cached } = await supabase
      .from("financial_reports")
      .select("*")
      .eq("pre_test_result_id", resultId)
      .maybeSingle();

    if (cached) {
      return NextResponse.json({ report: cached, cached: true });
    }
  } else {
    await supabase
      .from("financial_reports")
      .delete()
      .eq("pre_test_result_id", resultId);
  }

  const analysis = buildReportAnalysis(details, result.total_score);
  const level = getLevelFromScore(result.total_score);

  let reportText: string;
  let isFallback = false;

  const ollamaMessages: ChatMessage[] = [
    { role: "system", content: FINANCIAL_REPORT_SYSTEM_PROMPT },
    {
      role: "user",
      content: buildReportUserPrompt(analysis, level),
    },
  ];

  try {
    reportText = (await ollamaChat(ollamaMessages)).trim();
    if (!reportText) {
      throw new Error("Empty response");
    }
  } catch (error) {
    console.error("[pre-test/report]", error);
    reportText = buildFallbackReport(analysis, level);
    isFallback = true;

    if (!(error instanceof OllamaConnectionError)) {
      isFallback = true;
    }
  }

  const { data: saved, error: saveError } = await supabase
    .from("financial_reports")
    .insert({
      user_id: user.id,
      pre_test_result_id: resultId,
      level_key: level.key,
      level_name: level.name,
      total_score: result.total_score,
      accuracy_rate: analysis.accuracyRate,
      report_text: reportText,
      is_fallback: isFallback,
    })
    .select("*")
    .single();

  if (saveError) {
    console.error("[pre-test/report] save error:", saveError.message);
    return NextResponse.json(
      {
        error: "보고서 저장에 실패했습니다.",
        report: {
          level_key: level.key,
          level_name: level.name,
          total_score: result.total_score,
          accuracy_rate: analysis.accuracyRate,
          report_text: reportText,
          is_fallback: isFallback,
          pre_test_result_id: resultId,
          created_at: new Date().toISOString(),
        },
        unsaved: true,
      },
      { status: 200 }
    );
  }

  return NextResponse.json({
    report: saved,
    cached: false,
    isFallback,
  });
}
