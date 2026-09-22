import {
  FINANCE_KEYWORDS,
  type FinanceKeyword,
  type KeywordDifficulty,
} from "@/data/random_keywords/keywords";

export const KEYWORD_DISPLAY_COUNT = 5;

export function getAllowedDifficulties(score: number): KeywordDifficulty[] {
  if (score <= 15) return ["beginner"];
  if (score <= 25) return ["beginner", "intermediate"];
  return ["beginner", "intermediate", "advanced"];
}

export function filterKeywordsByScore(
  score: number,
  keywords: FinanceKeyword[] = FINANCE_KEYWORDS
): FinanceKeyword[] {
  const allowed = new Set(getAllowedDifficulties(score));
  return keywords.filter((item) => allowed.has(item.difficulty));
}

function shuffle<T>(items: T[]): T[] {
  const copy = [...items];
  for (let i = copy.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

export function pickRandomKeywords(
  pool: FinanceKeyword[],
  count: number,
  excludeKeywords: ReadonlySet<string> = new Set()
): FinanceKeyword[] {
  const available = pool.filter((item) => !excludeKeywords.has(item.keyword));
  const source = available.length >= count ? available : pool;
  return shuffle(source).slice(0, Math.min(count, source.length));
}

export function buildKeywordPrompt(keyword: string): string {
  return `${keyword}에 대해서 알려줘`;
}
