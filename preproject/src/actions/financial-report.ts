"use server";

import { createClient } from "@/utils/supabase/server";
import { isSupabaseConfigured } from "@/lib/supabase-config";
import type { FinancialReportRecord } from "@/lib/pretest/report-types";

export async function getFinancialReportByResultId(
  resultId: string
): Promise<FinancialReportRecord | null> {
  if (!isSupabaseConfigured()) {
    return null;
  }

  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return null;
  }

  const { data } = await supabase
    .from("financial_reports")
    .select("*")
    .eq("pre_test_result_id", resultId)
    .eq("user_id", user.id)
    .maybeSingle();

  return data as FinancialReportRecord | null;
}

export async function getLatestFinancialReport(): Promise<FinancialReportRecord | null> {
  if (!isSupabaseConfigured()) {
    return null;
  }

  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return null;
  }

  const { data } = await supabase
    .from("financial_reports")
    .select("*")
    .eq("user_id", user.id)
    .order("created_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  return data as FinancialReportRecord | null;
}
