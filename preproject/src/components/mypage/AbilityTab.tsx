import Link from "next/link";
import { BarChart3, ClipboardList, FileText } from "lucide-react";
import CategoryScoreChart from "@/components/pre-test/CategoryScoreChart";
import DiagnosisReportSection from "@/components/mypage/DiagnosisReportSection";
import {
  summarizeStoredResult,
  type StoredPreTestResult,
} from "@/lib/pretest/result-utils";
import type { FinancialReportRecord } from "@/lib/pretest/report-types";

interface AbilityTabProps {
  latestResult: StoredPreTestResult | null;
  latestReport: FinancialReportRecord | null;
}

export default function AbilityTab({
  latestResult,
  latestReport,
}: AbilityTabProps) {
  if (!latestResult) {
    return (
      <div className="card text-center">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-brand-50 text-brand-600">
          <ClipboardList className="h-7 w-7" />
        </div>
        <h2 className="text-xl font-bold text-slate-900">
          아직 사전테스트 기록이 없어요
        </h2>
        <p className="mt-2 text-sm text-slate-500">
          사전테스트를 완료하면 카테고리별 금융 역량 결과가 이곳에 표시됩니다.
        </p>
        <Link href="/pre-test" className="btn-primary mt-6 inline-flex">
          사전테스트 시작하기
        </Link>
      </div>
    );
  }

  const summary = summarizeStoredResult(latestResult);

  return (
    <div className="space-y-6">
      <div className="card">
        <div className="flex items-start gap-4">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
            <BarChart3 className="h-6 w-6" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-slate-900">내 금융 역량</h2>
            <p className="mt-1 text-sm text-slate-500">
              최근 사전테스트 · {summary.testedAt}
            </p>
            <p className="mt-3 text-lg">
              총{" "}
              <span className="font-bold text-brand-700">
                {summary.totalQuestions}문제
              </span>{" "}
              중{" "}
              <span className="font-bold text-brand-700">
                {summary.correctCount}문제 정답
              </span>
              <span className="ml-2 text-sm text-slate-500">
                (정답률 {summary.rate}%)
              </span>
            </p>
          </div>
        </div>
      </div>

      <div className="card">
        <CategoryScoreChart data={summary.categoryScores} />
      </div>

      {latestReport ? (
        <div className="card">
          <DiagnosisReportSection
            report={latestReport}
            totalQuestions={summary.totalQuestions}
            testedAt={summary.testedAt}
          />
        </div>
      ) : (
        <div className="card border-dashed border-brand-200 bg-brand-50/30 text-center">
          <FileText className="mx-auto h-8 w-8 text-brand-500" />
          <p className="mt-3 font-medium text-slate-800">
            AI 맞춤형 금융 보고서가 아직 없어요
          </p>
          <p className="mt-1 text-sm text-slate-500">
            사전테스트 결과 화면에서 보고서를 생성해 보세요.
          </p>
          <Link
            href={`/test-report?resultId=${latestResult.id}`}
            className="btn-primary mt-4 inline-flex gap-2"
          >
            <FileText className="h-4 w-4" />
            보고서 생성하기
          </Link>
        </div>
      )}

      <div className="flex gap-3">
        <Link href="/pre-test" className="btn-secondary">
          다시 테스트하기
        </Link>
        <Link href="/main" className="btn-primary">
          학습 시작하기
        </Link>
      </div>
    </div>
  );
}
