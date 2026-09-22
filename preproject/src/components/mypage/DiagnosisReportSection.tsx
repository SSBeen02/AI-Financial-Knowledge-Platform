import Link from "next/link";
import { FileText } from "lucide-react";
import LevelCharacterCard from "@/components/pre-test/LevelCharacterCard";
import ReportContent from "@/components/pre-test/ReportContent";
import type { FinancialReportRecord } from "@/lib/pretest/report-types";

interface DiagnosisReportSectionProps {
  report: FinancialReportRecord;
  totalQuestions: number;
  testedAt: string;
}

export default function DiagnosisReportSection({
  report,
  totalQuestions,
  testedAt,
}: DiagnosisReportSectionProps) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
          <FileText className="h-5 w-5 text-brand-600" />
          내 금융 진단 리포트
        </h3>
        <Link
          href={`/test-report?resultId=${report.pre_test_result_id}`}
          className="text-sm font-medium text-brand-600 hover:text-brand-700"
        >
          전체 보기
        </Link>
      </div>

      <LevelCharacterCard
        correctCount={report.total_score}
        totalQuestions={totalQuestions}
        testedAt={testedAt}
      />

      <ReportContent
        reportText={report.report_text}
        isFallback={report.is_fallback}
      />
    </div>
  );
}
