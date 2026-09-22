"use client";

import { useActionState, useEffect, useRef } from "react";
import { Loader2, Lock } from "lucide-react";
import { updatePassword, type PasswordUpdateState } from "@/actions/auth";

const initialState: PasswordUpdateState = {};

export default function PasswordChangeForm() {
  const [state, formAction, isPending] = useActionState(
    updatePassword,
    initialState
  );
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    if (state.success) {
      formRef.current?.reset();
    }
  }, [state.success]);

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-xl font-bold text-slate-900">비밀번호 변경</h2>
        <p className="mt-1 text-sm text-slate-500">
          새 비밀번호는 6자 이상이어야 합니다.
        </p>
      </div>

      <form ref={formRef} action={formAction} className="max-w-md space-y-4">
        <div>
          <label
            htmlFor="password"
            className="mb-1.5 block text-sm font-medium text-slate-700"
          >
            새 비밀번호
          </label>
          <input
            id="password"
            name="password"
            type="password"
            required
            minLength={6}
            autoComplete="new-password"
            placeholder="6자 이상 입력"
            className="input-field"
          />
        </div>

        <div>
          <label
            htmlFor="confirmPassword"
            className="mb-1.5 block text-sm font-medium text-slate-700"
          >
            새 비밀번호 확인
          </label>
          <input
            id="confirmPassword"
            name="confirmPassword"
            type="password"
            required
            minLength={6}
            autoComplete="new-password"
            placeholder="비밀번호를 다시 입력"
            className="input-field"
          />
        </div>

        {state.success && (
          <div
            role="status"
            className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700"
          >
            비밀번호가 변경되었습니다.
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
          disabled={isPending}
          className="btn-primary gap-2 disabled:opacity-60"
        >
          {isPending ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              변경 중...
            </>
          ) : (
            <>
              <Lock className="h-4 w-4" />
              비밀번호 변경
            </>
          )}
        </button>
      </form>
    </div>
  );
}
