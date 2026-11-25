"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertCircle,
  ArrowLeft,
  FileText,
  Loader2,
  RefreshCw,
} from "lucide-react";
import LevelCharacterCard from "@/components/pre-test/LevelCharacterCard";
import ReportContent from "@/components/pre-test/ReportContent";
import type { FinancialReportRecord } from "@/lib/pretest/report-types";
import type { PreTestResultDetail } from "@/lib/pretest/types";

interface FinancialReportViewProps {
  resultId: string;
  totalScore: number;
  details: PreTestResultDetail[];
  testedAt: string;
  initialReport?: FinancialReportRecord | null;
}

export default function FinancialReportView({
  resultId,
  totalScore,
  details,
  testedAt,
  initialReport = null,
}: FinancialReportViewProps) {
  const totalQuestions = details.length;
  const [report, setReport] = useState<FinancialReportRecord | null>(
    initialReport
  );
  const [isLoading, setIsLoading] = useState(!initialReport);
  const [error, setError] = useState<string>();
  const [isRetrying, setIsRetrying] = useState(false);

  const generateReport = useCallback(
    async (force = false) => {
      setIsLoading(true);
      setError(undefined);

      try {
        const response = await fetch("/api/pre-test/report", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ resultId, force }),
        });

        const data = await response.json();

        if (!response.ok && !data.report) {
          setError(data.error ?? "보고서 생성에 실패했습니다.");
          return;
        }

        if (data.report?.report_text) {
          setReport(data.report);
        } else if (data.error) {
          setError(data.error);
        }
      } catch {
        setError(
          "Ollama 서버에 연결할 수 없습니다. Ollama 앱이 실행 중인지 확인해 주세요."
        );
      } finally {
        setIsLoading(false);
        setIsRetrying(false);
      }
    },
    [resultId]
  );

  useEffect(() => {
    if (!initialReport) {
      generateReport(false);
    }
  }, [initialReport, generateReport]);

  const handleRetry = () => {
    setIsRetrying(true);
    generateReport(true);
  };

  return (
    <div className="mx-auto max-w-3xl">
      <Link
        href="/mypage"
        className="mb-4 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-brand-600"
      >
        <ArrowLeft className="h-4 w-4" />
        마이페이지로
      </Link>

      <div className="mb-6 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-100 text-brand-600">
          <FileText className="h-5 w-5" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-slate-900 sm:text-2xl">
            내 맞춤형 금융 보고서
          </h1>
          <p className="text-sm text-slate-500">사전테스트 기반 AI 진단 리포트</p>
        </div>
      </div>

      <LevelCharacterCard
        correctCount={totalScore}
        totalQuestions={totalQuestions}
        testedAt={testedAt}
      />

      {isLoading && (
        <div className="card mt-6 flex flex-col items-center justify-center gap-4 py-16">
          <div className="relative">
            <Loader2 className="h-12 w-12 animate-spin text-brand-600" />
            <SparkleRing />
          </div>
          <div className="text-center">
            <p className="font-medium text-slate-800">
              AI가 금융 보고서를 작성 중입니다...
            </p>
            <p className="mt-1 text-sm text-slate-500">
              Qwen 모델이 맞춤형 분석을 생성하고 있어요. 잠시만 기다려 주세요.
            </p>
          </div>
        </div>
      )}

      {error && !isLoading && !report && (
        <div className="card mt-6">
          <div className="flex items-start gap-3 text-red-700">
            <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
            <div>
              <p className="font-medium">{error}</p>
              <button
                type="button"
                onClick={handleRetry}
                disabled={isRetrying}
                className="btn-primary mt-4 gap-2"
              >
                {isRetrying ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )}
                다시 생성하기
              </button>
            </div>
          </div>
        </div>
      )}

      {report && !isLoading && (
        <div className="mt-6 space-y-4">
          <ReportContent
            reportText={report.report_text}
            isFallback={report.is_fallback}
          />
          {report.is_fallback && (
            <div className="flex justify-end">
              <button
                type="button"
                onClick={handleRetry}
                disabled={isRetrying}
                className="btn-secondary gap-2 text-sm"
              >
                {isRetrying ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )}
                AI 보고서 다시 생성
              </button>
            </div>
          )}
        </div>
      )}

      <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:justify-center">
        <Link href="/explore" className="btn-primary text-center">
          금융지식 탐색하기
        </Link>
        <Link href="/main" className="btn-secondary text-center">
          메인 페이지로
        </Link>
      </div>
    </div>
  );
}

function SparkleRing() {
  return (
    <div className="pointer-events-none absolute inset-0 animate-ping rounded-full border-2 border-brand-300 opacity-30" />
  );
}
