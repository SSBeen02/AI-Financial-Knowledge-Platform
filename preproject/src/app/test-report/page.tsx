import { redirect } from "next/navigation";
import FinancialReportView from "@/components/pre-test/FinancialReportView";
import { getFinancialReportByResultId } from "@/actions/financial-report";
import { isSupabaseConfigured } from "@/lib/supabase-config";
import { createClient } from "@/utils/supabase/server";
import type { PreTestResultDetail } from "@/lib/pretest/types";

export const metadata = {
  title: "맞춤형 금융 보고서 | FinEdu",
};

interface TestReportPageProps {
  searchParams: Promise<{ resultId?: string }>;
}

export default async function TestReportPage({
  searchParams,
}: TestReportPageProps) {
  if (!isSupabaseConfigured()) {
    redirect("/login?next=/test-report");
  }

  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login?next=/test-report");
  }

  const { resultId: queryResultId } = await searchParams;

  let resultRow;

  if (queryResultId) {
    const { data } = await supabase
      .from("pre_test_results")
      .select("id, total_score, details, created_at")
      .eq("id", queryResultId)
      .eq("user_id", user.id)
      .maybeSingle();
    resultRow = data;
  } else {
    const { data } = await supabase
      .from("pre_test_results")
      .select("id, total_score, details, created_at")
      .eq("user_id", user.id)
      .order("created_at", { ascending: false })
      .limit(1)
      .maybeSingle();
    resultRow = data;
  }

  if (!resultRow) {
    redirect("/pre-test");
  }

  const existingReport = await getFinancialReportByResultId(resultRow.id);
  const testedAt = new Date(resultRow.created_at).toLocaleDateString("ko-KR", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  return (
    <div className="section-container py-10">
      <FinancialReportView
        resultId={resultRow.id}
        totalScore={resultRow.total_score}
        details={resultRow.details as PreTestResultDetail[]}
        testedAt={testedAt}
        initialReport={existingReport}
      />
    </div>
  );
}
