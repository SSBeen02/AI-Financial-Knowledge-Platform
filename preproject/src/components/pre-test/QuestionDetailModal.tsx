"use client";

import { CheckCircle2, Star, X, XCircle } from "lucide-react";
import type { EnrichedResultDetail } from "@/lib/pretest/enrich-detail";

interface QuestionDetailModalProps {
  detail: EnrichedResultDetail;
  questionNumber: number;
  onClose: () => void;
}

export default function QuestionDetailModal({
  detail,
  questionNumber,
  onClose,
}: QuestionDetailModalProps) {
  const { explanation } = detail;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        aria-label="닫기"
        className="absolute inset-0 bg-slate-900/50"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="question-detail-title"
        className="relative max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl bg-white p-6 shadow-xl"
      >
        <button
          type="button"
          onClick={onClose}
          className="absolute right-4 top-4 rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
        >
          <X className="h-5 w-5" />
        </button>

        {!detail.hasDetailData ? (
          <div className="py-8 text-center">
            <p className="text-slate-600">
              이 문제에 대한 상세 데이터가 없습니다.
            </p>
            <button type="button" onClick={onClose} className="btn-primary mt-4">
              닫기
            </button>
          </div>
        ) : (
          <>
            <div className="pr-8">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="font-semibold text-brand-700">
                  {questionNumber}번
                </span>
                <span className="rounded-full bg-brand-50 px-2.5 py-0.5 font-medium text-brand-700">
                  {detail.categoryLabel}
                </span>
                <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-slate-500">
                  Lv.{detail.difficulty}
                </span>
                {detail.isCorrect ? (
                  <span className="inline-flex items-center gap-1 text-green-600">
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    정답
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-red-500">
                    <XCircle className="h-3.5 w-3.5" />
                    오답
                  </span>
                )}
              </div>

              <h2
                id="question-detail-title"
                className="mt-3 text-lg font-bold text-slate-900"
              >
                {detail.concept}
              </h2>
              <p className="mt-2 text-sm leading-relaxed text-slate-700">
                {detail.question}
              </p>
            </div>

            <div className="mt-6 space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                선지
              </p>
              {detail.options.map((option, index) => {
                const optionNum = index + 1;
                const isUserChoice = detail.selectedAnswer === optionNum;
                const isCorrectChoice = detail.correctAnswer === optionNum;
                const optionDetail = explanation?.options_detail?.[index];

                let borderClass = "border-slate-200 bg-white";
                if (isUserChoice && isCorrectChoice) {
                  borderClass = "border-green-400 bg-green-50 ring-1 ring-green-200";
                } else if (isCorrectChoice) {
                  borderClass = "border-green-400 bg-green-50/80 ring-1 ring-green-100";
                } else if (isUserChoice) {
                  borderClass = "border-red-400 bg-red-50 ring-1 ring-red-100";
                }

                return (
                  <div
                    key={option}
                    className={`rounded-xl border px-4 py-3 ${borderClass}`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <p className="text-sm font-medium text-slate-800">
                        <span className="mr-2 text-brand-600">{optionNum}.</span>
                        {option.replace(/^\d+\)\s*/, "")}
                      </p>
                      <div className="flex shrink-0 gap-1">
                        {isUserChoice && (
                          <span className="rounded-full bg-brand-100 px-2 py-0.5 text-[10px] font-semibold text-brand-700">
                            내 선택
                          </span>
                        )}
                        {isCorrectChoice && (
                          <span className="inline-flex items-center gap-0.5 rounded-full bg-green-100 px-2 py-0.5 text-[10px] font-semibold text-green-700">
                            <Star className="h-2.5 w-2.5" />
                            정답
                          </span>
                        )}
                      </div>
                    </div>
                    {optionDetail && (
                      <p className="mt-2 border-t border-slate-100 pt-2 text-xs leading-relaxed text-slate-600">
                        {optionDetail}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>

            {explanation?.correct && (
              <div className="mt-6 rounded-xl border border-brand-100 bg-brand-50/50 p-4">
                <p className="text-xs font-semibold text-brand-700">해설</p>
                <p className="mt-2 text-sm leading-relaxed text-slate-700">
                  {explanation.correct}
                </p>
              </div>
            )}

            <div className="mt-6 flex justify-end">
              <button type="button" onClick={onClose} className="btn-primary">
                닫기
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
