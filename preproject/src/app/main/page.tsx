import Link from "next/link";
import { redirect } from "next/navigation";
import { Archive, ArrowRight, BookOpen, Sparkles } from "lucide-react";
import { isSupabaseConfigured } from "@/lib/supabase-config";
import { createClient } from "@/utils/supabase/server";

export const metadata = {
  title: "메인 페이지 | FinEdu",
  description: "금융지식 탐색과 학습노트 관리를 선택하세요",
};

const hubCards = [
  {
    href: "/explore",
    title: "금융지식 탐색하기",
    description:
      "궁금한 금융 용어나 개념을 AI에게 질문해 보세요. 친절한 설명과 함께 즉시 이해도를 검증하는 맞춤 퀴즈가 제공됩니다.",
    icon: Sparkles,
    gradient: "from-violet-500 to-brand-600",
    iconBg: "bg-violet-50 text-violet-600 group-hover:bg-violet-600 group-hover:text-white",
    borderHover: "hover:border-violet-200",
  },
  {
    href: "/notes",
    title: "학습노트 관리하기",
    description:
      "그동안 탐색했던 금융 지식과 풀었던 퀴즈, 오답 노트를 한곳에서 모아보고 복습해 보세요.",
    icon: BookOpen,
    gradient: "from-emerald-500 to-teal-600",
    iconBg: "bg-emerald-50 text-emerald-600 group-hover:bg-emerald-600 group-hover:text-white",
    borderHover: "hover:border-emerald-200",
  },
];

export default async function MainPage() {
  if (!isSupabaseConfigured()) {
    redirect("/login?next=/main");
  }

  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login?next=/main");
  }

  return (
    <div className="section-container py-12 sm:py-16">
      <div className="mx-auto max-w-3xl text-center">
        <h1 className="text-3xl font-bold text-slate-900 sm:text-4xl">
          어떤 학습을 시작할까요?
        </h1>
        <p className="mt-3 text-slate-600">
          FinEdu의 핵심 기능 중 원하는 방식을 선택해 주세요.
        </p>
      </div>

      <div className="mx-auto mt-12 grid max-w-4xl gap-6 sm:grid-cols-2">
        {hubCards.map((card) => (
          <Link
            key={card.href}
            href={card.href}
            className={`group relative overflow-hidden rounded-2xl border border-slate-100 bg-white p-8 shadow-card transition hover:-translate-y-1 hover:shadow-card-hover ${card.borderHover}`}
          >
            <div
              className={`absolute inset-x-0 top-0 h-1 bg-gradient-to-r ${card.gradient}`}
            />
            <div
              className={`mb-6 flex h-14 w-14 items-center justify-center rounded-2xl transition ${card.iconBg}`}
            >
              <card.icon className="h-7 w-7" />
            </div>
            <h2 className="text-xl font-bold text-slate-900">{card.title}</h2>
            <p className="mt-3 text-sm leading-relaxed text-slate-600">
              {card.description}
            </p>
            <span className="mt-6 inline-flex items-center gap-1 text-sm font-semibold text-brand-600 group-hover:gap-2 transition-all">
              시작하기
              <ArrowRight className="h-4 w-4" />
            </span>
          </Link>
        ))}
      </div>

      <div className="mx-auto mt-10 flex max-w-4xl justify-center">
        <Link
          href="/mypage"
          className="inline-flex items-center gap-2 text-sm text-slate-500 hover:text-brand-600"
        >
          <Archive className="h-4 w-4" />
          마이페이지에서 학습 현황 확인하기
        </Link>
      </div>
    </div>
  );
}
