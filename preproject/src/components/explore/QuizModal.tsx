"use client";



import { useEffect, useRef, useState } from "react";

import { useRouter } from "next/navigation";
import {

  Archive,

  BrainCircuit,

  CheckCircle2,

  Loader2,

  X,

  XCircle,

} from "lucide-react";

import type { ChatMessage, ExploreQuizQuestion } from "@/lib/explore/types";

import type { QuizAttemptInput } from "@/lib/notes/types";



export interface QuizProgress {
  currentIndex: number;
  selected: number | boolean | null;
  showResult: boolean;
  attempts: QuizAttemptInput[];
}

interface QuizModalProps {
  initialProgress?: QuizProgress;
  onProgress: (progress: QuizProgress) => void;
  onFinish: () => void;

  questions: ExploreQuizQuestion[];

  keywords: string[];

  messages: ChatMessage[];

  onClose: () => void;

}



export default function QuizModal({

  questions,

  keywords,

  messages,
  initialProgress,
  onProgress,
  onFinish,
  onClose,

}: QuizModalProps) {

  const router = useRouter();

  const [currentIndex, setCurrentIndex] = useState(initialProgress?.currentIndex ?? 0);

  const [selected, setSelected] = useState<number | boolean | null>(initialProgress?.selected ?? null);

  const [showResult, setShowResult] = useState(initialProgress?.showResult ?? false);

  const [score, setScore] = useState(
    () => initialProgress?.attempts.filter((attempt) => attempt.isCorrect).length ?? 0,
  );

  const [finished, setFinished] = useState(false);

  const [attempts, setAttempts] = useState<QuizAttemptInput[]>(initialProgress?.attempts ?? []);

  const [isSaving, setIsSaving] = useState(false);

  const [saveError, setSaveError] = useState<string>();

  const [saved, setSaved] = useState(false);

  const saveStarted = useRef(false);



  const question = questions[currentIndex];

  const isCorrect =

    selected !== null &&

    (question.type === "ox"

      ? selected === question.answer

      : selected === question.answer);



  const handleSelect = (answer: number | boolean) => {
    setSelected(answer);
    onProgress({ currentIndex, selected: answer, showResult: false, attempts });
  };

  const handleConfirm = () => {

    if (selected === null) return;

    const correct =

      question.type === "ox"

        ? selected === question.answer

        : selected === question.answer;

    if (correct) setScore((s) => s + 1);



    const nextAttempts = [
      ...attempts,
      { questionId: question.id, selectedAnswer: selected, isCorrect: correct },
    ];
    setAttempts(nextAttempts);
    onProgress({ currentIndex, selected, showResult: true, attempts: nextAttempts });
    setShowResult(true);

  };



  const handleNext = () => {

    if (currentIndex < questions.length - 1) {

      onProgress({ currentIndex: currentIndex + 1, selected: null, showResult: false, attempts });
      setCurrentIndex(currentIndex + 1);

      setSelected(null);

      setShowResult(false);

    } else {

      onFinish();
      setFinished(true);

    }

  };



  useEffect(() => {

    if (!finished || saveStarted.current) return;

    saveStarted.current = true;



    async function saveNote() {

      setIsSaving(true);

      setSaveError(undefined);

      try {

        const response = await fetch("/api/notes", {

          method: "POST",

          headers: { "Content-Type": "application/json" },

          body: JSON.stringify({

            messages: messages.filter((m) => m.role !== "system"),

            keywords,

            questions,

            attempts,

          }),

        });

        const data = await response.json();

        if (!response.ok) {

          setSaveError(data.error ?? "저장에 실패했습니다.");

          return;

        }

        setSaved(true);

      } catch {

        setSaveError("네트워크 오류로 저장하지 못했습니다.");

      } finally {

        setIsSaving(false);

      }

    }



    saveNote();

  }, [finished, messages, keywords, questions, attempts]);



  return (

    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">

      <button

        type="button"

        aria-label="닫기"

        className="absolute inset-0 bg-slate-900/50"

        onClick={onClose}

      />

      <div className="relative max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl bg-white p-6 shadow-xl">

        <button

          type="button"

          onClick={onClose}

          className="absolute right-4 top-4 rounded-lg p-1 text-slate-400 hover:bg-slate-100"

        >

          <X className="h-5 w-5" />

        </button>



        {finished ? (

          <div className="py-4 text-center">

            <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-brand-50 text-brand-600">

              <BrainCircuit className="h-8 w-8" />

            </div>

            <h2 className="text-xl font-bold text-slate-900">퀴즈 완료!</h2>

            <p className="mt-2 text-slate-600">

              {questions.length}문제 중{" "}

              <span className="font-bold text-brand-700">{score}문제 정답</span>

            </p>

            <div className="mt-4 flex flex-wrap justify-center gap-2">

              {keywords.map((kw) => (

                <span

                  key={kw}

                  className="rounded-full bg-violet-50 px-3 py-1 text-xs font-medium text-violet-700"

                >

                  {kw}

                </span>

              ))}

            </div>



            {isSaving && (

              <div className="mt-4 flex items-center justify-center gap-2 text-sm text-slate-500">

                <Loader2 className="h-4 w-4 animate-spin text-brand-600" />

                학습노트에 저장하는 중...

              </div>

            )}



            {saveError && (

              <p className="mt-4 text-sm text-red-600">{saveError}</p>

            )}



            {saved && !saveError && (

              <p className="mt-4 inline-flex items-center gap-1 text-sm font-medium text-green-700">

                <CheckCircle2 className="h-4 w-4" />

                학습노트에 저장했어!

              </p>

            )}



            <div className="mt-6 flex flex-col gap-2 sm:flex-row sm:justify-center">

              {saved && (

                <button

                  type="button"

                  onClick={() => router.push("/notes")}

                  className="btn-primary gap-2"

                >

                  <Archive className="h-4 w-4" />

                  학습노트 보기

                </button>

              )}

              <button type="button" onClick={onClose} className="btn-secondary">

                닫기

              </button>

            </div>

          </div>

        ) : (

          <>

            <div className="mb-4 flex items-center justify-between pr-8">

              <span className="text-sm font-medium text-brand-700">

                맞춤형 퀴즈 {currentIndex + 1}/{questions.length}

              </span>

              <span className="rounded-full bg-violet-50 px-2.5 py-0.5 text-xs font-medium text-violet-700">

                {question.keyword}

              </span>

            </div>



            <h3 className="text-lg font-semibold text-slate-900">

              {question.question}

            </h3>



            <div className="mt-4 space-y-2">

              {question.type === "ox" ? (

                (["O", "X"] as const).map((label, idx) => {

                  const value = idx === 0;

                  const isSelected = selected === value;

                  return (

                    <button

                      key={label}

                      type="button"

                      disabled={showResult}

                      onClick={() => handleSelect(value)}

                      className={`w-full rounded-xl border px-4 py-3 text-left font-semibold transition ${

                        isSelected

                          ? "border-brand-500 bg-brand-50 text-brand-800"

                          : "border-slate-200 hover:border-brand-200"

                      }`}

                    >

                      {label}

                    </button>

                  );

                })

              ) : (

                question.options?.map((opt, idx) => {

                  const optionNum = idx + 1;

                  const isSelected = selected === optionNum;

                  return (

                    <button

                      key={opt}

                      type="button"

                      disabled={showResult}

                      onClick={() => handleSelect(optionNum)}

                      className={`w-full rounded-xl border px-4 py-3 text-left text-sm transition ${

                        isSelected

                          ? "border-brand-500 bg-brand-50 text-brand-800"

                          : "border-slate-200 hover:border-brand-200"

                      }`}

                    >

                      {opt}

                    </button>

                  );

                })

              )}

            </div>



            {showResult && (

              <div

                className={`mt-4 rounded-xl border px-4 py-3 ${

                  isCorrect

                    ? "border-green-200 bg-green-50"

                    : "border-red-200 bg-red-50"

                }`}

              >

                <div className="flex items-center gap-2 font-semibold">

                  {isCorrect ? (

                    <>

                      <CheckCircle2 className="h-5 w-5 text-green-600" />

                      <span className="text-green-700">정답!</span>

                    </>

                  ) : (

                    <>

                      <XCircle className="h-5 w-5 text-red-500" />

                      <span className="text-red-600">오답</span>

                    </>

                  )}

                </div>

                <p className="mt-1 text-sm text-slate-600">{question.explanation}</p>

              </div>

            )}



            <div className="mt-6 flex justify-end gap-2">

              {!showResult ? (

                <button

                  type="button"

                  onClick={handleConfirm}

                  disabled={selected === null}

                  className="btn-primary disabled:opacity-50"

                >

                  확인

                </button>

              ) : (

                <button type="button" onClick={handleNext} className="btn-primary">

                  {currentIndex < questions.length - 1 ? "다음 문제" : "결과 보기"}

                </button>

              )}

            </div>

          </>

        )}

      </div>

    </div>

  );

}

