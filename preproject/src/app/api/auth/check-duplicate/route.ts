import { NextResponse } from "next/server";
import { isValidEmail } from "@/lib/validators";
import { isSupabaseConfigured } from "@/lib/supabase-config";
import { createClient } from "@/utils/supabase/server";

export async function POST(request: Request) {
  if (!isSupabaseConfigured()) {
    return NextResponse.json(
      { available: false, message: "Supabase 설정이 필요합니다." },
      { status: 503 }
    );
  }

  let body: { email?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { available: false, message: "잘못된 요청입니다." },
      { status: 400 }
    );
  }

  const email = body.email?.trim() ?? "";

  if (!email) {
    return NextResponse.json(
      { available: false, message: "이메일을 입력해 주세요." },
      { status: 400 }
    );
  }

  if (!isValidEmail(email)) {
    return NextResponse.json(
      { available: false, message: "올바른 이메일 형식을 입력해 주세요." },
      { status: 400 }
    );
  }

  const supabase = await createClient();
  const { data, error } = await supabase.rpc("check_email_available", {
    check_email: email,
  });

  if (error) {
    console.error("[check-duplicate]", error.message);
    return NextResponse.json(
      {
        available: false,
        message: "중복 확인 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
      },
      { status: 500 }
    );
  }

  const available = Boolean(data);

  return NextResponse.json({
    available,
    message: available
      ? "사용 가능한 이메일입니다."
      : "이미 사용 중인 이메일입니다.",
  });
}
