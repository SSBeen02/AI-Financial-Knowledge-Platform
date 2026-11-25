import Link from "next/link";
import {
  ArrowRight,
  BookOpen,
  BrainCircuit,
  ChartLine,
  PiggyBank,
  Sparkles,
  Target,
  TrendingUp,
  Wallet,
} from "lucide-react";
import StartButton from "@/components/StartButton";

const features = [
  {
    icon: BookOpen,
    title: "기초부터 시작하는 단계별 커리큘럼",
    description:
      "예·적금, 세금, 투자까지 어려운 금융 개념을 쉬운 언어로 단계별로 학습할 수 있어요.",
  },
  {
    icon: BrainCircuit,
    title: "퀴즈로 확인하는 금융 지식",
    description:
      "매 강의마다 제공되는 퀴즈로 배운 내용을 바로 확인하고, 실수를 통해 확실히 기억해요.",
  },
  {
    icon: ChartLine,
    title: "나의 학습 현황 관리",
    description:
      "완료한 강의, 퀴즈 점수, 학습 streak을 한눈에 확인하며 꾸준히 성장할 수 있어요.",
  },
];

const previewCourses = [
  {
    icon: PiggyBank,
    title: "월급쟁이를 위한 예·적금 가이드",
    description: "처음 받은 월급, 어디에 어떻게 모을까?",
    level: "입문",
    duration: "20분",
    color: "from-brand-500 to-brand-700",
  },
  {
    icon: Wallet,
    title: "알기 쉬운 세금과 공제",
    description: "연말정산, 소득세… 꼭 알아야 할 기본 개념",
    level: "기초",
    duration: "25분",
    color: "from-sky-500 to-brand-600",
  },
  {
    icon: TrendingUp,
    title: "투자 입문: ETF란 무엇인가",
    description: "주식 시장에 첫 발을 내딛는 가장 안전한 방법",
    level: "입문",
    duration: "30분",
    color: "from-indigo-500 to-brand-700",
  },
];

export default function HomePage() {
  return (
    <>
      {/* Hero Section */}
      <section className="relative overflow-hidden bg-gradient-to-b from-brand-50 via-white to-slate-50">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-brand-100/40 via-transparent to-transparent" />
        <div className="section-container relative py-20 sm:py-28">
          <div className="mx-auto max-w-3xl text-center">
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-brand-200 bg-white px-4 py-1.5 text-sm font-medium text-brand-700 shadow-sm">
              <Sparkles className="h-4 w-4 text-brand-500" />
              금융 문맹 탈출 프로젝트
            </div>

            <h1 className="text-4xl font-extrabold tracking-tight text-slate-900 sm:text-5xl lg:text-6xl">
              금융이 쉬워지는 첫걸음,{" "}
              <span className="bg-gradient-to-r from-brand-600 to-brand-800 bg-clip-text text-transparent">
                FinEdu
              </span>
            </h1>

            <p className="mt-6 text-lg leading-relaxed text-slate-600 sm:text-xl">
              어려운 경제/금융 개념을 기초부터 실전까지 차근차근 배워보세요.
            </p>

            <div className="mt-10 flex flex-col items-center justify-center gap-4 sm:flex-row">
              <StartButton />
              <Link href="/courses" className="btn-secondary gap-2 px-8 py-3 text-base">
                <Target className="h-4 w-4" />
                강의 둘러보기
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section className="section-container py-20">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-bold text-slate-900">
            FinEdu가 특별한 이유
          </h2>
          <p className="mt-3 text-slate-600">
            복잡한 금융 지식을 누구나 이해할 수 있도록 설계했어요.
          </p>
        </div>

        <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {features.map((feature) => (
            <article key={feature.title} className="card group">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-brand-50 text-brand-600 transition group-hover:bg-brand-600 group-hover:text-white">
                <feature.icon className="h-6 w-6" />
              </div>
              <h3 className="text-lg font-semibold text-slate-900">
                {feature.title}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-600">
                {feature.description}
              </p>
            </article>
          ))}
        </div>
      </section>

      {/* Course Preview Section */}
      <section className="bg-white py-20">
        <div className="section-container">
          <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-end">
            <div>
              <h2 className="text-3xl font-bold text-slate-900">
                추천 강의 맛보기
              </h2>
              <p className="mt-2 text-slate-600">
                지금 바로 시작할 수 있는 인기 강의를 미리 만나보세요.
              </p>
            </div>
            <Link
              href="/courses"
              className="inline-flex items-center gap-1 text-sm font-semibold text-brand-600 hover:text-brand-700"
            >
              전체 강의 보기
              <ArrowRight className="h-4 w-4" />
            </Link>
          </div>

          <div className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {previewCourses.map((course) => (
              <article
                key={course.title}
                className="group overflow-hidden rounded-2xl border border-slate-100 bg-white shadow-card transition hover:-translate-y-1 hover:shadow-card-hover"
              >
                <div
                  className={`flex h-36 items-center justify-center bg-gradient-to-br ${course.color}`}
                >
                  <course.icon className="h-14 w-14 text-white/90 transition group-hover:scale-110" />
                </div>
                <div className="p-5">
                  <div className="flex items-center gap-2 text-xs font-medium">
                    <span className="rounded-full bg-brand-50 px-2.5 py-0.5 text-brand-700">
                      {course.level}
                    </span>
                    <span className="text-slate-400">{course.duration}</span>
                  </div>
                  <h3 className="mt-3 font-semibold text-slate-900">
                    {course.title}
                  </h3>
                  <p className="mt-1.5 text-sm text-slate-600">
                    {course.description}
                  </p>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="section-container py-20">
        <div className="rounded-3xl bg-gradient-to-r from-brand-600 to-brand-800 px-8 py-14 text-center text-white shadow-lg sm:px-16">
          <h2 className="text-2xl font-bold sm:text-3xl">
            오늘부터 금융 문맹 탈출을 시작하세요
          </h2>
          <p className="mx-auto mt-3 max-w-lg text-brand-100">
            무료로 가입하고 첫 강의를 완료하면 금융 기초를 확실히 다질 수 있어요.
          </p>
          <StartButton
            label="무료로 시작하기"
            className="mt-8 inline-flex items-center gap-2 rounded-lg bg-white px-8 py-3 text-base font-semibold text-brand-700 shadow-sm transition hover:bg-brand-50"
          />
        </div>
      </section>
    </>
  );
}
