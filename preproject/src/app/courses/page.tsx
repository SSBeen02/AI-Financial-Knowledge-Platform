import Link from "next/link";
import { BookOpen } from "lucide-react";

export default function CoursesPage() {
  return (
    <div className="section-container py-16">
      <div className="mx-auto max-w-2xl text-center">
        <div className="mx-auto mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-brand-50 text-brand-600">
          <BookOpen className="h-8 w-8" />
        </div>
        <h1 className="text-3xl font-bold text-slate-900">교육 목록</h1>
        <p className="mt-3 text-slate-600">
          곧 다양한 금융 교육 강의가 이곳에 제공됩니다.
        </p>
        <Link href="/" className="btn-primary mt-8 inline-flex">
          홈으로 돌아가기
        </Link>
      </div>
    </div>
  );
}
