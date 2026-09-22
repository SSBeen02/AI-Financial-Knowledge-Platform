import { cache } from "react";
import { cookies } from "next/headers";
import { isSupabaseConfigured } from "@/lib/supabase-config";
import { createClient } from "@/utils/supabase/server";
import type { User } from "@supabase/supabase-js";

function isInvalidRefreshToken(error: { code?: string; message?: string }) {
  return (
    error.code === "refresh_token_not_found" ||
    error.message?.includes("Refresh Token") === true
  );
}

function isAuthSessionMissing(error: { name?: string; message?: string }) {
  return (
    error.name === "AuthSessionMissingError" ||
    error.message === "Auth session missing!"
  );
}

function hasAuthCookie(cookieList: { name: string }[]) {
  return cookieList.some((cookie) => cookie.name.includes("-auth-token"));
}

/** Supabase 네트워크 오류 시에도 앱이 죽지 않도록 안전하게 사용자 조회 */
export const getSafeUser = cache(async (): Promise<User | null> => {
  if (!isSupabaseConfigured()) {
    return null;
  }

  try {
    const cookieStore = await cookies();
    if (!hasAuthCookie(cookieStore.getAll())) {
      return null;
    }

    const supabase = await createClient();
    const {
      data: { user },
      error,
    } = await supabase.auth.getUser();

    if (error) {
      if (isAuthSessionMissing(error)) {
        return null;
      }
      if (isInvalidRefreshToken(error)) {
        await supabase.auth.signOut();
        return null;
      }
      console.error("[Supabase] getUser failed:", error.message);
      return null;
    }

    return user;
  } catch (error) {
    console.error("[Supabase] connection failed:", error);
    return null;
  }
});