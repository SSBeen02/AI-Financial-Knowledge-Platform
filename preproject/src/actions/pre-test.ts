"use server";

import { createClient } from "@/utils/supabase/server";
import { isSupabaseConfigured } from "@/lib/supabase-config";
import type { PreTestResultDetail } from "@/lib/pretest/types";

export type SavePreTestResultState = {
  error?: string;
  resultId?: string;
};

export async function savePreTestResult(
  totalScore: number,
  details: PreTestResultDetail[]
): Promise<SavePreTestResultState> {
  if (!isSupabaseConfigured()) {
    return { error: "Supabase 설정이 필요합니다." };
  }

  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return { error: "로그인이 필요합니다." };
  }

  const { data, error } = await supabase
    .from("pre_test_results")
    .insert({
      user_id: user.id,
      total_score: totalScore,
      details,
    })
    .select("id")
    .single();

  if (error) {
    console.error("Pre-test save error:", error.message);
    return { error: "결과 저장에 실패했습니다. 잠시 후 다시 시도해 주세요." };
  }

  return { resultId: data.id };
}
