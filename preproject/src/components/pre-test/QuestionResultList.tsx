"use client";

import { useMemo, useState } from "react";
import {
  CheckCircle2,
  ClipboardList,
  XCircle,
} from "lucide-react";
import QuestionDetailModal from "@/components/pre-test/QuestionDetailModal";
import {
  enrichResultDetails,
  type EnrichedResultDetail,
} from "@/lib/pretest/enrich-detail";
import type { PreTestResultDetail } from "@/lib/pretest/types";

interface QuestionResultListProps {
  details: PreTestResultDetail[];
}

export default function QuestionResultList({ details }: QuestionResultListProps) {
  const enrichedDetails = useMemo(
    () => enrichResultDetails(details),
    [details]
  );
  const [selectedDetail, setSelectedDetail] =
    useState<EnrichedResultDetail | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);

  const openModal = (detail: EnrichedResultDetail, index: number) => {
    setSelectedDetail(detail);
    setSelectedIndex(index);
  };

  return (
    <>
      <div className="space-y-3">
        {enrichedDetails.map((detail, index) => (
          <div
            key={detail.questionId}
            className={`flex items-start gap-3 rounded-xl border px-4 py-3 ${
              detail.isCorrect
                ? "border-green-100 bg-green-50/50"
                : "border-red-100 bg-red-50/50"
            }`}
          >
            {detail.isCorrect ? (
              <CheckCircle2
                className="mt-0.5 h-5 w-5 shrink-0 text-green-600"
                aria-label="정답"
              />
            ) : (
              <XCircle
                className="mt-0.5 h-5 w-5 shrink-0 text-red-500"
                aria-label="오답"
              />
            )}
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="font-medium text-slate-500">{index + 1}번</span>
                <span className="rounded-full bg-white px-2 py-0.5 font-medium text-brand-700">
                  {detail.categoryLabel}
                </span>
                <span className="rounded-full bg-white px-2 py-0.5 text-slate-500">
                  Lv.{detail.difficulty}
                </span>
              </div>
              <p className="mt-1 text-sm font-medium text-slate-800">
                {detail.concept}
              </p>
              {!detail.isCorrect && (
                <p className="mt-1 text-xs text-slate-500">
                  선택: {detail.selectedAnswer}번 · 정답: {detail.correctAnswer}번
                </p>
              )}
            </div>
            {detail.hasDetailData && (
              <button
                type="button"
                onClick={() => openModal(detail, index)}
                title="선지 및 해설 보기"
                aria-label="선지 및 해설 보기"
                className="mt-0.5 shrink-0 rounded-lg border border-slate-200 bg-white p-2 text-slate-500 transition hover:border-brand-300 hover:bg-brand-50 hover:text-brand-700"
              >
                <ClipboardList className="h-4 w-4" />
              </button>
            )}
          </div>
        ))}
      </div>

      {selectedDetail && (
        <QuestionDetailModal
          detail={selectedDetail}
          questionNumber={selectedIndex + 1}
          onClose={() => setSelectedDetail(null)}
        />
      )}
    </>
  );
}
