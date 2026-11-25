import { QUIZ_SOURCES } from "./quiz-sources";
import type { PreTestQuestion, RawQuizQuestion } from "./types";

const QUESTIONS_PER_CATEGORY = 5;

function shuffle<T>(array: T[]): T[] {
  const copy = [...array];
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy;
}

/** 난이도가 골고루 섞이도록 count개 문제를 추출 */
export function selectBalancedQuestions(
  pool: RawQuizQuestion[],
  count: number
): RawQuizQuestion[] {
  if (pool.length <= count) {
    return shuffle(pool);
  }

  const byDifficulty = new Map<number, RawQuizQuestion[]>();

  for (const question of pool) {
    const group = byDifficulty.get(question.difficulty) ?? [];
    group.push(question);
    byDifficulty.set(question.difficulty, group);
  }

  for (const [level, questions] of byDifficulty) {
    byDifficulty.set(level, shuffle(questions));
  }

  const levels = [...byDifficulty.keys()].sort((a, b) => a - b);
  const selected: RawQuizQuestion[] = [];
  const usedIds = new Set<string>();
  let round = 0;

  while (selected.length < count && levels.length > 0) {
    const level = levels[round % levels.length];
    const available = (byDifficulty.get(level) ?? []).filter(
      (q) => !usedIds.has(q.id)
    );

    if (available.length === 0) {
      const idx = levels.indexOf(level);
      levels.splice(idx, 1);
      continue;
    }

    const pick = available[0];
    selected.push(pick);
    usedIds.add(pick.id);
    round++;
  }

  if (selected.length < count) {
    const remaining = shuffle(pool.filter((q) => !usedIds.has(q.id)));
    selected.push(...remaining.slice(0, count - selected.length));
  }

  return selected;
}

/** 모든 카테고리 JSON에서 각 5문제씩 추출 후 하나의 배열로 합침 */
export function generatePreTestQuestions(): PreTestQuestion[] {
  const allQuestions: PreTestQuestion[] = [];

  for (const source of QUIZ_SOURCES) {
    const picked = selectBalancedQuestions(
      source.questions,
      QUESTIONS_PER_CATEGORY
    );

    for (const question of picked) {
      allQuestions.push({
        ...question,
        sourceFile: source.fileName,
        categoryLabel: source.categoryLabel,
      });
    }
  }

  return shuffle(allQuestions);
}
