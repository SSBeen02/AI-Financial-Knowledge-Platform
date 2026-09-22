import Link from "next/link";
import { GraduationCap } from "lucide-react";
import HeaderAuth from "@/components/HeaderAuth";
import { getHeaderNavState } from "@/lib/pre-test-status";

export default async function Header() {
  const { showPreTest } = await getHeaderNavState();

  const navLinks = [
    { href: "/main", label: "메인 페이지" },
    ...(showPreTest ? [{ href: "/pre-test", label: "사전테스트" }] : []),
    { href: "/mypage", label: "마이페이지" },
  ];

  return (
    <header className="sticky top-0 z-50 border-b border-slate-100 bg-white/90 backdrop-blur-md">
      <div className="section-container flex h-16 items-center justify-between">
        <Link href="/" className="flex items-center gap-2 group">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-600 text-white shadow-sm transition group-hover:bg-brand-700">
            <GraduationCap className="h-5 w-5" />
          </span>
          <span className="text-xl font-bold tracking-tight text-brand-800">
            FinEdu
          </span>
        </Link>

        <nav className="hidden items-center gap-1 md:flex">
          {navLinks.map((link) => (
            <Link key={link.href} href={link.href} className="btn-ghost">
              {link.label}
            </Link>
          ))}
        </nav>

        <HeaderAuth />
      </div>
    </header>
  );
}
