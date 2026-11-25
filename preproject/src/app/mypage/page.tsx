import { redirect } from "next/navigation";
import MyPageClient from "@/components/mypage/MyPageClient";
import { getLatestFinancialReport } from "@/actions/financial-report";
import type { StoredPreTestResult } from "@/lib/pretest/result-utils";
import type { PreTestResultDetail } from "@/lib/pretest/types";
import { isSupabaseConfigured } from "@/lib/supabase-config";
import { createClient } from "@/utils/supabase/server";

export const metadata = {
  title: "마이페이지 | FinEdu",
};

export default async function MyPage() {
  if (!isSupabaseConfigured()) {
    redirect("/login?next=/mypage");
  }

  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login?next=/mypage");
  }

  const { data: profile } = await supabase
    .from("profiles")
    .select("full_name")
    .eq("id", user.id)
    .single();

  const displayName =
    profile?.full_name ??
    user.user_metadata?.full_name ??
    user.email?.split("@")[0] ??
    "사용자";

  const { data: latestResultRow } = await supabase
    .from("pre_test_results")
    .select("id, total_score, details, created_at")
    .eq("user_id", user.id)
    .order("created_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  const latestResult: StoredPreTestResult | null = latestResultRow
    ? {
        id: latestResultRow.id,
        total_score: latestResultRow.total_score,
        details: latestResultRow.details as PreTestResultDetail[],
        created_at: latestResultRow.created_at,
      }
    : null;

  const latestReport = await getLatestFinancialReport();

  return (
    <MyPageClient
      displayName={displayName}
      email={user.email ?? ""}
      latestResult={latestResult}
      latestReport={latestReport}
    />
  );
}
