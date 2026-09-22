import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";
import { isSupabaseConfigured } from "@/lib/supabase-config";

function isInvalidRefreshToken(error: { code?: string; message?: string }) {
  return (
    error.code === "refresh_token_not_found" ||
    error.message?.includes("Refresh Token") === true
  );
}

export async function updateSession(request: NextRequest) {
  if (!isSupabaseConfigured()) {
    return NextResponse.next({ request });
  }

  let supabaseResponse = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet: { name: string; value: string; options?: Record<string, unknown> }[]) {
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value)
          );
          supabaseResponse = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            supabaseResponse.cookies.set(name, value, options)
          );
        },
      },
    }
  );

  const hasAuthCookie = request.cookies
    .getAll()
    .some((cookie) => cookie.name.includes("-auth-token"));

  // 로그인 쿠키가 없으면 getUser()가 "Auth session missing"을 반환하므로 호출하지 않음
  if (!hasAuthCookie) {
    return supabaseResponse;
  }

  const { error } = await supabase.auth.getUser();

  // Supabase pause 복구·세션 만료 등으로 쿠키만 남은 경우 → 자동 로그아웃 처리
  if (error && isInvalidRefreshToken(error)) {
    await supabase.auth.signOut();
  }

  return supabaseResponse;
}
