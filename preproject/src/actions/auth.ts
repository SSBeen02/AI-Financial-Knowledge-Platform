"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { getAuthErrorMessage } from "@/lib/auth-errors";
import { isSupabaseConfigured } from "@/lib/supabase-config";
import { createClient } from "@/utils/supabase/server";

export type AuthActionState = {
  error?: string;
  success?: boolean;
};

export async function signUp(
  _prevState: AuthActionState,
  formData: FormData
): Promise<AuthActionState> {
  const email = formData.get("email") as string;
  const password = formData.get("password") as string;
  const fullName = formData.get("fullName") as string;
  const emailVerified = formData.get("emailVerified") === "true";

  if (!isSupabaseConfigured()) {
    return {
      error:
        "Supabase 설정이 필요합니다. .env.local 파일에 URL과 Key를 입력해 주세요.",
    };
  }

  if (!email || !password || !fullName) {
    return { error: "모든 항목을 입력해 주세요." };
  }

  if (!emailVerified) {
    return { error: "이메일 중복 확인을 완료해 주세요." };
  }

  if (password.length < 6) {
    return { error: "비밀번호는 6자 이상이어야 합니다." };
  }

  const supabase = await createClient();

  const { data: isAvailable, error: checkError } = await supabase.rpc(
    "check_email_available",
    { check_email: email }
  );

  if (checkError) {
    console.error("Email check error:", checkError.message);
    return { error: "이메일 확인 중 오류가 발생했습니다." };
  }

  if (!isAvailable) {
    return { error: "이미 사용 중인 이메일입니다. 로그인해 주세요." };
  }

  const { data, error } = await supabase.auth.signUp({
    email,
    password,
    options: {
      data: {
        full_name: fullName,
      },
    },
  });

  if (error) {
    return { error: getAuthErrorMessage(error.message) };
  }

  // 이메일 인증이 필요한 경우 (세션 없음)
  if (data.user && !data.session) {
    return {
      success: true,
    };
  }

  if (data.user && data.session) {
    const { error: profileError } = await supabase.from("profiles").upsert({
      id: data.user.id,
      full_name: fullName,
      email,
    });

    if (profileError) {
      // DB 트리거가 프로필을 생성했을 수 있으므로 치명적 오류로 처리하지 않음
      console.error("Profile upsert error:", profileError.message);
    }
  }

  revalidatePath("/", "layout");
  redirect("/");
}

export async function signIn(
  _prevState: AuthActionState,
  formData: FormData
): Promise<AuthActionState> {
  const email = formData.get("email") as string;
  const password = formData.get("password") as string;

  if (!isSupabaseConfigured()) {
    return {
      error:
        "Supabase 설정이 필요합니다. .env.local 파일에 URL과 Key를 입력해 주세요.",
    };
  }

  if (!email || !password) {
    return { error: "이메일과 비밀번호를 입력해 주세요." };
  }

  const supabase = await createClient();

  const { error } = await supabase.auth.signInWithPassword({
    email,
    password,
  });

  if (error) {
    return { error: getAuthErrorMessage(error.message) };
  }

  revalidatePath("/", "layout");
  redirect("/");
}

export async function signOut() {
  const supabase = await createClient();
  await supabase.auth.signOut();
  revalidatePath("/", "layout");
  redirect("/");
}

export type PasswordUpdateState = {
  error?: string;
  success?: boolean;
};

export async function updatePassword(
  _prevState: PasswordUpdateState,
  formData: FormData
): Promise<PasswordUpdateState> {
  const password = formData.get("password") as string;
  const confirmPassword = formData.get("confirmPassword") as string;

  if (!isSupabaseConfigured()) {
    return { error: "Supabase 설정이 필요합니다." };
  }

  if (!password || !confirmPassword) {
    return { error: "모든 항목을 입력해 주세요." };
  }

  if (password.length < 6) {
    return { error: "비밀번호는 6자 이상이어야 합니다." };
  }

  if (password !== confirmPassword) {
    return { error: "새 비밀번호와 확인 비밀번호가 일치하지 않습니다." };
  }

  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return { error: "로그인이 필요합니다." };
  }

  const { error } = await supabase.auth.updateUser({ password });

  if (error) {
    return { error: getAuthErrorMessage(error.message) };
  }

  return { success: true };
}
