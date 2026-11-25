"use client";

import { useActionState } from "react";
import Link from "next/link";
import { GraduationCap, Loader2 } from "lucide-react";
import { signIn, type AuthActionState } from "@/actions/auth";

const initialState: AuthActionState = {};

export default function LoginForm() {
  const [state, formAction, isPending] = useActionState(signIn, initialState);

  return (
    <div className="flex min-h-[calc(100vh-8rem)] items-center justify-center px-4 py-12">
      <div className="w-full max-w-md">
        <div className="card">
          <div className="mb-8 text-center">
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-brand-600 text-white">
              <GraduationCap className="h-6 w-6" />
            </div>
            <h1 className="text-2xl font-bold text-slate-900">로그인</h1>
            <p className="mt-2 text-sm text-slate-500">
              FinEdu 계정으로 로그인하세요
            </p>
          </div>

          <form action={formAction} className="space-y-4">
            <div>
              <label
                htmlFor="email"
                className="mb-1.5 block text-sm font-medium text-slate-700"
              >
                이메일
              </label>
              <input
                id="email"
                name="email"
                type="email"
                required
                autoComplete="email"
                placeholder="example@email.com"
                className="input-field"
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
                autoComplete="current-password"
                placeholder="비밀번호를 입력하세요"
                className="input-field"
              />
            </div>

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
              disabled={isPending}
              className="btn-primary w-full gap-2 py-3 disabled:opacity-60"
            >
              {isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  로그인 중...
                </>
              ) : (
                "로그인"
              )}
            </button>
          </form>

          <p className="mt-6 text-center text-sm text-slate-500">
            아직 계정이 없으신가요?{" "}
            <Link
              href="/signup"
              className="font-semibold text-brand-600 hover:text-brand-700"
            >
              회원가입
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
