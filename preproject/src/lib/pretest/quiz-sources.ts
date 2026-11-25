import type { RawQuizQuestion } from "./types";

import loanQuestions from "@/data/pretest/대출.json";
import tax1Questions from "@/data/pretest/세금1.json";
import tax2Questions from "@/data/pretest/세금2.json";
import productQuestions from "@/data/pretest/상품이해.json";
import marketQuestions from "@/data/pretest/시장분석.json";
import creditQuestions from "@/data/pretest/신용관리.json";
import pensionQuestions from "@/data/pretest/연금.json";

export interface QuizSource {
  fileName: string;
  categoryLabel: string;
  questions: RawQuizQuestion[];
}

export const QUIZ_SOURCES: QuizSource[] = [
  { fileName: "대출.json", categoryLabel: "대출", questions: loanQuestions as RawQuizQuestion[] },
  { fileName: "세금1.json", categoryLabel: "세금 기초", questions: tax1Questions as RawQuizQuestion[] },
  { fileName: "세금2.json", categoryLabel: "세금 심화", questions: tax2Questions as RawQuizQuestion[] },
  { fileName: "상품이해.json", categoryLabel: "상품 이해", questions: productQuestions as RawQuizQuestion[] },
  { fileName: "시장분석.json", categoryLabel: "시장 분석", questions: marketQuestions as RawQuizQuestion[] },
  { fileName: "신용관리.json", categoryLabel: "신용 관리", questions: creditQuestions as RawQuizQuestion[] },
  { fileName: "연금.json", categoryLabel: "연금", questions: pensionQuestions as RawQuizQuestion[] },
];
