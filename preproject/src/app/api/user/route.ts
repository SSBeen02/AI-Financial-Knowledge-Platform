import { NextResponse } from "next/server";
import { DELETE_CONFIRM_TEXT } from "@/lib/validators";
import { isSupabaseConfigured } from "@/lib/supabase-config";
import { createAdminClient, isAdminConfigured } from "@/utils/supabase/admin";
import { createClient } from "@/utils/supabase/server";

export async function DELETE(request: Request) {
  if (!isSupabaseConfigured()) {
    return NextResponse.json(
      { error: "Supabase 설정이 필요합니다." },
      { status: 503 }
    );
  }

  if (!isAdminConfigured()) {
    return NextResponse.json(
      {
        error:
          "계정 삭제 기능을 사용하려면 SUPABASE_SERVICE_ROLE_KEY 환경 변수가 필요합니다.",
      },
      { status: 503 }
    );
  }

  let body: { password?: string; confirmText?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "잘못된 요청입니다." }, { status: 400 });
  }

  const password = body.password ?? "";
  const confirmText = body.confirmText?.trim() ?? "";

  if (!password) {
    return NextResponse.json(
      { error: "비밀번호를 입력해 주세요." },
      { status: 400 }
    );
  }

  if (confirmText !== DELETE_CONFIRM_TEXT) {
    return NextResponse.json(
      { error: `"${DELETE_CONFIRM_TEXT}"를 정확히 입력해 주세요.` },
      { status: 400 }
    );
  }

  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user?.email) {
    return NextResponse.json(
      { error: "로그인이 필요합니다." },
      { status: 401 }
    );
  }

  const { error: signInError } = await supabase.auth.signInWithPassword({
    email: user.email,
    password,
  });

  if (signInError) {
    return NextResponse.json(
      { error: "비밀번호가 올바르지 않습니다." },
      { status: 401 }
    );
  }

  const admin = createAdminClient();
  if (!admin) {
    return NextResponse.json(
      { error: "서버 설정 오류입니다." },
      { status: 503 }
    );
  }

  const { error: deleteError } = await admin.auth.admin.deleteUser(user.id);

  if (deleteError) {
    console.error("[delete-user]", deleteError.message);
    return NextResponse.json(
      { error: "계정 삭제에 실패했습니다. 잠시 후 다시 시도해 주세요." },
      { status: 500 }
    );
  }

  await supabase.auth.signOut();

  return NextResponse.json({ success: true });
}
