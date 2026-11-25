"use client";

import Link from "next/link";
import { CheckCircle2, FileText, Home, RotateCcw } from "lucide-react";
import CategoryScoreChart from "@/components/pre-test/CategoryScoreChart";
import QuestionResultList from "@/components/pre-test/QuestionResultList";
import type { PreTestScoreResult } from "@/lib/pretest/types";

interface PreTestResultViewProps {
  result: PreTestScoreResult;
  saveError?: string;
  resultId?: string;
  onRetry: () => void;
}

export default function PreTestResultView({
  result,
  saveError,
  resultId,
  onRetry,
}: PreTestResultViewProps) {
  const { correctCount, totalQuestions, wrongCount, categoryScores } = result;
  const rate = Math.round((correctCount / totalQuestions) * 100);

  return (
    <div className="section-container py-10">
      <div className="mx-auto max-w-3xl">
        <div className="card text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-brand-50">
            <CheckCircle2 className="h-8 w-8 text-brand-600" />
          </div>
          <h1 className="text-2xl font-bold text-slate-900 sm:text-3xl">
            총 {totalQuestions}문제 중{" "}
            <span className="text-brand-600">{correctCount}문제 정답!</span>
          </h1>
          <p className="mt-2 text-slate-600">
            정답률 {rate}% · 틀린 문제 {wrongCount}개
          </p>

          {saveError && (
            <div
              role="alert"
              className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
            >
              {saveError} (결과 화면은 확인할 수 있습니다)
            </div>
          )}
        </div>

        <div className="card mt-6">
          <CategoryScoreChart data={categoryScores} />
        </div>

        <div className="card mt-6">
          <h3 className="mb-4 text-lg font-semibold text-slate-900">
            문제별 결과
          </h3>
          <QuestionResultList details={result.details} />
        </div>

        <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:justify-center">
          {resultId && (
            <Link
              href={`/test-report?resultId=${resultId}`}
              className="btn-primary gap-2 text-center"
            >
              <FileText className="h-4 w-4" />
              내 맞춤형 금융 보고서 보러가기
            </Link>
          )}
          <button type="button" onClick={onRetry} className="btn-secondary gap-2">
            <RotateCcw className="h-4 w-4" />
            다시 풀기
          </button>
          <Link href="/mypage" className="btn-ghost gap-2 text-center">
            마이페이지로
          </Link>
          <Link href="/" className="btn-ghost gap-2 text-center">
            <Home className="h-4 w-4" />
            홈으로
          </Link>
        </div>
      </div>
    </div>
  );
}
