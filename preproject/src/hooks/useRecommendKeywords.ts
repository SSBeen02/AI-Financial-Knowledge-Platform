"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { FinanceKeyword } from "@/data/random_keywords/keywords";
import {
  filterKeywordsByScore,
  KEYWORD_DISPLAY_COUNT,
  pickRandomKeywords,
} from "@/lib/explore/recommend-keywords";

export function useRecommendKeywords(preTestScore: number | null) {
  const score = preTestScore ?? 0;
  const seenKeywordsRef = useRef<Set<string>>(new Set());
  const [keywords, setKeywords] = useState<FinanceKeyword[]>([]);

  const drawKeywords = useCallback(() => {
    const pool = filterKeywordsByScore(score);
    let next = pickRandomKeywords(
      pool,
      KEYWORD_DISPLAY_COUNT,
      seenKeywordsRef.current
    );

    if (next.length < KEYWORD_DISPLAY_COUNT) {
      seenKeywordsRef.current.clear();
      next = pickRandomKeywords(pool, KEYWORD_DISPLAY_COUNT);
    }

    next.forEach((item) => seenKeywordsRef.current.add(item.keyword));
    setKeywords(next);
  }, [score]);

  useEffect(() => {
    seenKeywordsRef.current.clear();
    drawKeywords();
  }, [drawKeywords]);

  const refresh = useCallback(() => {
    drawKeywords();
  }, [drawKeywords]);

  const markUsed = useCallback((keyword: string) => {
    seenKeywordsRef.current.add(keyword);
  }, []);

  return {
    keywords,
    refresh,
    markUsed,
  };
}
