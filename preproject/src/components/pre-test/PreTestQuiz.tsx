"use client";

import { useState } from "react";
import { ArrowRight, BarChart3, Loader2 } from "lucide-react";
import { savePreTestResult } from "@/actions/pre-test";
import PreTestResultView from "@/components/pre-test/PreTestResultView";
import { calculatePreTestScore } from "@/lib/pretest/score";
import { generatePreTestQuestions } from "@/lib/pretest/select-questions";
import type {
  PreTestAnswer,
  PreTestQuestion,
  PreTestScoreResult,
} from "@/lib/pretest/types";

interface PreTestQuizProps {
  initialQuestions: PreTestQuestion[];
}

type Phase = "quiz" | "loading" | "result";

export default function PreTestQuiz({ initialQuestions }: PreTestQuizProps) {
  const [phase, setPhase] = useState<Phase>("quiz");
  const [questions, setQuestions] = useState(initialQuestions);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [answers, setAnswers] = useState<PreTestAnswer[]>([]);
  const [selectedOption, setSelectedOption] = useState<number | null>(null);
  const [scoreResult, setScoreResult] = useState<PreTestScoreResult | null>(
    null
  );
  const [saveError, setSaveError] = useState<string>();
  const [resultId, setResultId] = useState<string>();

  const currentQuestion = questions[currentIndex];
  const totalQuestions = questions.length;
  const isLastQuestion = currentIndex === totalQuestions - 1;
  const progress = ((currentIndex + 1) / totalQuestions) * 100;

  const handleSelectOption = (optionIndex: number) => {
    setSelectedOption(optionIndex);
  };

  const handleNext = async () => {
    if (!currentQuestion || selectedOption === null) return;

    const newAnswer: PreTestAnswer = {
      questionId: currentQuestion.id,
      category: currentQuestion.category,
      categoryLabel: currentQuestion.categoryLabel,
      difficulty: currentQuestion.difficulty,
      concept: currentQuestion.concept,
      selectedAnswer: selectedOption,
      correctAnswer: currentQuestion.answer,
      isCorrect: selectedOption === currentQuestion.answer,
    };

    const updatedAnswers = [
      ...answers.filter((a) => a.questionId !== currentQuestion.id),
      newAnswer,
    ];
    setAnswers(updatedAnswers);

    if (!isLastQuestion) {
      const nextIndex = currentIndex + 1;
      setCurrentIndex(nextIndex);
      const nextAnswer = updatedAnswers.find(
        (a) => a.questionId === questions[nextIndex].id
      );
      setSelectedOption(nextAnswer?.selectedAnswer ?? null);
      return;
    }

    setPhase("loading");
    const result = calculatePreTestScore(questions, updatedAnswers);
    setScoreResult(result);

    const saveResponse = await savePreTestResult(
      result.totalScore,
      result.details
    );

    if (saveResponse.error) {
      setSaveError(saveResponse.error);
    }
    if (saveResponse.resultId) {
      setResultId(saveResponse.resultId);
    }

    setPhase("result");
  };

  const handleRetry = () => {
    const newQuestions = generatePreTestQuestions();
    setQuestions(newQuestions);
    setCurrentIndex(0);
    setAnswers([]);
    setSelectedOption(null);
    setScoreResult(null);
    setSaveError(undefined);
    setResultId(undefined);
    setPhase("quiz");
  };

  if (phase === "loading") {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4">
        <Loader2 className="h-10 w-10 animate-spin text-brand-600" />
        <p className="text-slate-600">결과를 분석하고 저장하는 중...</p>
      </div>
    );
  }

  if (phase === "result" && scoreResult) {
    return (
      <PreTestResultView
        result={scoreResult}
        saveError={saveError}
        resultId={resultId}
        onRetry={handleRetry}
      />
    );
  }

  return (
    <div className="section-container py-10">
      <div className="mx-auto max-w-2xl">
        <div className="mb-8 text-center">
          <div className="mb-3 inline-flex items-center gap-2 rounded-full bg-brand-50 px-4 py-1.5 text-sm font-medium text-brand-700">
            <BarChart3 className="h-4 w-4" />
            금융 지식 사전테스트
          </div>
          <h1 className="text-2xl font-bold text-slate-900">
            나의 금융 역량을 확인해 보세요
          </h1>
          <p className="mt-2 text-sm text-slate-500">
            7개 카테고리 · 총 {totalQuestions}문제
          </p>
        </div>

        <div className="mb-6">
          <div className="mb-2 flex items-center justify-between text-sm">
            <span className="font-medium text-brand-700">
              {currentQuestion.categoryLabel}
            </span>
            <span className="text-slate-500">
              {currentIndex + 1} / {totalQuestions}
            </span>
          </div>
          <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
            <div
              className="h-full rounded-full bg-brand-600 transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>

        <div className="card">
          <div className="mb-4 flex items-center gap-2">
            <span className="rounded-full bg-brand-50 px-2.5 py-0.5 text-xs font-semibold text-brand-700">
              Lv.{currentQuestion.difficulty}
            </span>
            <span className="text-xs text-slate-400">{currentQuestion.concept}</span>
          </div>

          <h2 className="text-lg font-semibold leading-relaxed text-slate-900 sm:text-xl">
            {currentQuestion.question}
          </h2>

          <ul className="mt-6 space-y-3">
            {currentQuestion.options.map((option, index) => {
              const optionNumber = index + 1;
              const isSelected = selectedOption === optionNumber;

              return (
                <li key={option}>
                  <button
                    type="button"
                    onClick={() => handleSelectOption(optionNumber)}
                    className={`w-full rounded-xl border px-4 py-3.5 text-left text-sm transition sm:text-base ${
                      isSelected
                        ? "border-brand-500 bg-brand-50 font-medium text-brand-800 ring-2 ring-brand-500/20"
                        : "border-slate-200 bg-white text-slate-700 hover:border-brand-200 hover:bg-brand-50/30"
                    }`}
                  >
                    {option}
                  </button>
                </li>
              );
            })}
          </ul>

          <div className="mt-8 flex justify-end">
            <button
              type="button"
              onClick={handleNext}
              disabled={selectedOption === null}
              className="btn-primary gap-2 px-6 py-3 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isLastQuestion ? "결과 보기" : "다음 문제"}
              <ArrowRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
