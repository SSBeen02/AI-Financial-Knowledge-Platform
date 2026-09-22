"use client";

import Image from "next/image";
import { Sparkles } from "lucide-react";
import { getLevelFromScore } from "@/lib/pretest/level-character";

interface LevelCharacterCardProps {
  correctCount: number;
  totalQuestions: number;
  testedAt?: string;
}

export default function LevelCharacterCard({
  correctCount,
  totalQuestions,
  testedAt,
}: LevelCharacterCardProps) {
  const level = getLevelFromScore(correctCount);
  const rate =
    totalQuestions > 0
      ? Math.round((correctCount / totalQuestions) * 100)
      : 0;

  return (
    <div className="card overflow-hidden bg-gradient-to-br from-brand-50 via-white to-amber-50">
      <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-center sm:gap-6">
        <div className="relative h-36 w-36 shrink-0 overflow-hidden rounded-2xl bg-white shadow-md ring-4 ring-brand-100">
          <Image
            src={level.image}
            alt={level.name}
            fill
            className="object-contain p-2"
            priority
          />
        </div>
        <div className="flex-1 text-center sm:text-left">
          <div className="inline-flex items-center gap-1.5 rounded-full bg-brand-100 px-3 py-1 text-xs font-semibold text-brand-700">
            <Sparkles className="h-3.5 w-3.5" />
            나의 금융 레벨
          </div>
          <h2 className="mt-2 text-2xl font-bold text-slate-900">{level.name}</h2>
          <p className="mt-1 text-sm text-slate-600">{level.description}</p>
          <p className="mt-3 text-sm text-slate-500">
            정답 {correctCount}/{totalQuestions} · 정답률 {rate}%
            {testedAt && (
              <span className="ml-2 text-slate-400">· {testedAt}</span>
            )}
          </p>
        </div>
      </div>
    </div>
  );
}
