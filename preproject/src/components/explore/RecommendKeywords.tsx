"use client";

import { RefreshCw } from "lucide-react";
import { useRecommendKeywords } from "@/hooks/useRecommendKeywords";
import { buildKeywordPrompt } from "@/lib/explore/recommend-keywords";

interface RecommendKeywordsProps {
  preTestScore: number | null;
  onSelectKeyword: (prompt: string) => void;
  disabled?: boolean;
}

export default function RecommendKeywords({
  preTestScore,
  onSelectKeyword,
  disabled = false,
}: RecommendKeywordsProps) {
  const { keywords, refresh, markUsed } = useRecommendKeywords(preTestScore);

  const handleKeywordClick = (keyword: string) => {
    if (disabled) return;
    markUsed(keyword);
    onSelectKeyword(buildKeywordPrompt(keyword));
  };

  if (keywords.length === 0) return null;

  return (
    <div className="mb-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-xs font-medium text-slate-500">
          추천 키워드
          {preTestScore !== null && (
            <span className="ml-1 text-slate-400">
              (사전테스트 {preTestScore}점 기준)
            </span>
          )}
        </p>
        <button
          type="button"
          onClick={refresh}
          disabled={disabled}
          title="추천 키워드 새로고침"
          aria-label="추천 키워드 새로고침"
          className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-slate-500 transition hover:bg-slate-100 hover:text-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          새로고침
        </button>
      </div>
      <div className="flex flex-wrap gap-2">
        {keywords.map((item) => (
          <button
            key={item.keyword}
            type="button"
            onClick={() => handleKeywordClick(item.keyword)}
            disabled={disabled}
            className="rounded-full border border-brand-200 bg-brand-50 px-3 py-1.5 text-xs font-medium text-brand-700 transition hover:border-brand-300 hover:bg-brand-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {item.keyword}
          </button>
        ))}
      </div>
    </div>
  );
}
