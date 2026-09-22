"use client";

import { useActionState, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { GraduationCap, Loader2 } from "lucide-react";
import { signUp, type AuthActionState } from "@/actions/auth";
import { isValidEmail } from "@/lib/validators";

const initialState: AuthActionState = {};

type DuplicateStatus = "idle" | "checking" | "available" | "unavailable" | "invalid";

export default function SignUpForm() {
  const [state, formAction, isPending] = useActionState(signUp, initialState);
  const [email, setEmail] = useState("");
  const [duplicateStatus, setDuplicateStatus] =
    useState<DuplicateStatus>("idle");
  const [duplicateMessage, setDuplicateMessage] = useState("");
  const [emailVerified, setEmailVerified] = useState(false);
  const lastCheckedEmail = useRef("");

  useEffect(() => {
    setDuplicateStatus("idle");
    setDuplicateMessage("");
    setEmailVerified(false);
    lastCheckedEmail.current = "";
  }, [email]);

  const handleCheckDuplicate = async () => {
    const trimmed = email.trim();

    if (!trimmed) {
      setDuplicateStatus("invalid");
      setDuplicateMessage("이메일을 입력해 주세요.");
      setEmailVerified(false);
      return;
    }

    if (!isValidEmail(trimmed)) {
      setDuplicateStatus("invalid");
      setDuplicateMessage("올바른 이메일 형식을 입력해 주세요.");
      setEmailVerified(false);
      return;
    }

    setDuplicateStatus("checking");
    setDuplicateMessage("");
    setEmailVerified(false);

    try {
      const response = await fetch("/api/auth/check-duplicate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: trimmed }),
      });

      const data = await response.json();

      if (!response.ok) {
        setDuplicateStatus("invalid");
        setDuplicateMessage(data.message ?? "중복 확인에 실패했습니다.");
        setEmailVerified(false);
        return;
      }

      if (data.available) {
        setDuplicateStatus("available");
        setDuplicateMessage(data.message);
        setEmailVerified(true);
        lastCheckedEmail.current = trimmed;
      } else {
        setDuplicateStatus("unavailable");
        setDuplicateMessage(data.message);
        setEmailVerified(false);
      }
    } catch {
      setDuplicateStatus("invalid");
      setDuplicateMessage("네트워크 오류가 발생했습니다.");
      setEmailVerified(false);
    }
  };

  const canSubmit =
    emailVerified && lastCheckedEmail.current === email.trim() && !isPending;

  return (
    <div className="flex min-h-[calc(100vh-8rem)] items-center justify-center px-4 py-12">
      <div className="w-full max-w-md">
        <div className="card">
          <div className="mb-8 text-center">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-brand-600 text-white">
              <GraduationCap className="h-6 w-6" />
            </div>
            <h1 className="text-2xl font-bold text-slate-900">회원가입</h1>
            <p className="mt-2 text-sm text-slate-500">
              FinEdu와 함께 금융 문맹 탈출을 시작하세요
            </p>
          </div>

          <form action={formAction} className="space-y-4">
            <div>
              <label
                htmlFor="fullName"
                className="mb-1.5 block text-sm font-medium text-slate-700"
              >
                이름 (닉네임)
              </label>
              <input
                id="fullName"
                name="fullName"
                type="text"
                required
                autoComplete="name"
                placeholder="홍길동"
                className="input-field"
              />
            </div>

            <div>
              <label
                htmlFor="email"
                className="mb-1.5 block text-sm font-medium text-slate-700"
              >
                이메일
              </label>
              <div className="flex gap-2">
                <input
                  id="email"
                  name="email"
                  type="email"
                  required
                  autoComplete="email"
                  placeholder="example@email.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="input-field min-w-0 flex-1"
                />
                <button
                  type="button"
                  onClick={handleCheckDuplicate}
                  disabled={duplicateStatus === "checking"}
                  className="shrink-0 rounded-lg border border-brand-200 bg-brand-50 px-3 py-2 text-sm font-semibold text-brand-700 transition hover:bg-brand-100 disabled:opacity-60"
                >
                  {duplicateStatus === "checking" ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    "중복 확인"
                  )}
                </button>
              </div>
              {duplicateMessage && (
                <p
                  role="status"
                  className={`mt-1.5 text-sm ${
                    duplicateStatus === "available"
                      ? "text-green-600"
                      : duplicateStatus === "unavailable"
                        ? "text-red-600"
                        : "text-amber-600"
                  }`}
                >
                  {duplicateMessage}
                </p>
              )}
              <input
                type="hidden"
                name="emailVerified"
                value={emailVerified ? "true" : "false"}
              />
            </div>

            <div>
              <label
                htmlFor="password"
                className="mb-1.5 block text-sm font-medium text-slate-700"
              >
                비밀번호
              </label>
              <input
                id="password"
                name="password"
                type="password"
                required
                autoComplete="new-password"
                placeholder="6자 이상 입력하세요"
                minLength={6}
                className="input-field"
              />
            </div>

            {state.success && (
              <div
                role="status"
                className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700"
              >
                회원가입이 완료되었습니다. 이메일로 발송된 인증 링크를
                확인해 주세요.
              </div>
            )}

            {state.error && (
              <div
                role="alert"
                className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
              >
                {state.error}
              </div>
            )}

            <button
              type="submit"
              disabled={!canSubmit}
              className="btn-primary w-full gap-2 py-3 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  가입 중...
                </>
              ) : (
                "회원가입"
              )}
            </button>

            {!emailVerified && email.trim() && (
              <p className="text-center text-xs text-slate-400">
                이메일 중복 확인을 완료해야 가입할 수 있습니다.
              </p>
            )}
          </form>

          <p className="mt-6 text-center text-sm text-slate-500">
            이미 계정이 있으신가요?{" "}
            <Link
              href="/login"
              className="font-semibold text-brand-600 hover:text-brand-700"
            >
              로그인
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
