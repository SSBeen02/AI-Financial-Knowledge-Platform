import Link from "next/link";
import { Heart } from "lucide-react";

export default function Footer() {
  return (
    <footer className="border-t border-slate-100 bg-white">
      <div className="section-container py-10">
        <div className="flex flex-col items-center justify-between gap-6 md:flex-row">
          <div className="text-center md:text-left">
            <p className="text-lg font-bold text-brand-800">FinEdu</p>
            <p className="mt-1 text-sm text-slate-500">
              청소년과 사회초년생을 위한 금융 교육 플랫폼
            </p>
          </div>

          <nav className="flex flex-wrap items-center justify-center gap-6 text-sm text-slate-600">
            <Link href="/main" className="hover:text-brand-600">
              메인 페이지
            </Link>
            <Link href="/pre-test" className="hover:text-brand-600">
              사전테스트
            </Link>
            <Link href="/mypage" className="hover:text-brand-600">
              마이페이지
            </Link>
            <Link href="/login" className="hover:text-brand-600">
              로그인
            </Link>
          </nav>
        </div>

        <div className="mt-8 flex flex-col items-center justify-between gap-2 border-t border-slate-100 pt-6 text-xs text-slate-400 md:flex-row">
          <p>© 2026 FinEdu. All rights reserved.</p>
          <p className="flex items-center gap-1">
            Made with <Heart className="h-3 w-3 text-brand-500" /> for financial literacy
          </p>
        </div>
      </div>
    </footer>
  );
}
