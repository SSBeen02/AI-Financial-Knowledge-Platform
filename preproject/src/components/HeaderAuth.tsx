import Link from "next/link";
import { signOut } from "@/actions/auth";
import { isSupabaseConfigured } from "@/lib/supabase-config";
import { getSafeUser } from "@/lib/supabase-safe";
import { LogOut, User } from "lucide-react";

export default async function HeaderAuth() {
  if (!isSupabaseConfigured()) {
    return (
      <Link href="/login" className="btn-primary">
        로그인
      </Link>
    );
  }

  const user = await getSafeUser();

  if (!user) {
    return (
      <Link href="/login" className="btn-primary">
        로그인
      </Link>
    );
  }

  const displayName =
    user.user_metadata?.full_name ?? user.email?.split("@")[0] ?? "사용자";

  return (
    <div className="flex items-center gap-2">
      <Link
        href="/mypage"
        className="btn-ghost hidden items-center gap-1.5 sm:inline-flex"
      >
        <User className="h-4 w-4" />
        {displayName}
      </Link>
      <form action={signOut}>
        <button
          type="submit"
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 transition hover:border-red-200 hover:bg-red-50 hover:text-red-600"
        >
          <LogOut className="h-4 w-4" />
          <span className="hidden sm:inline">로그아웃</span>
        </button>
      </form>
    </div>
  );
}
