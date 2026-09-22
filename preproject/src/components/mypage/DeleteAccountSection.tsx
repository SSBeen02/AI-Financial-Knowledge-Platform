"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, Loader2, Trash2, X } from "lucide-react";
import { DELETE_CONFIRM_TEXT } from "@/lib/validators";

export default function DeleteAccountSection() {
  const router = useRouter();
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [confirmText, setConfirmText] = useState("");
  const [error, setError] = useState<string>();
  const [isDeleting, setIsDeleting] = useState(false);

  const canSubmit =
    password.length > 0 && confirmText === DELETE_CONFIRM_TEXT && !isDeleting;

  const closeModal = () => {
    if (isDeleting) return;
    setIsModalOpen(false);
    setPassword("");
    setConfirmText("");
    setError(undefined);
  };

  const handleDelete = async () => {
    if (!canSubmit) return;

    setIsDeleting(true);
    setError(undefined);

    try {
      const response = await fetch("/api/user", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password, confirmText }),
      });

      const data = await response.json();

      if (!response.ok) {
        setError(data.error ?? "계정 삭제에 실패했습니다.");
        return;
      }

      router.push("/");
      router.refresh();
    } catch {
      setError("네트워크 오류가 발생했습니다. 다시 시도해 주세요.");
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <>
      <div className="mt-10 border-t border-red-100 pt-8">
        <h3 className="text-lg font-semibold text-red-700">위험 구역</h3>
        <p className="mt-1 text-sm text-slate-500">
          계정을 삭제하면 프로필, 사전테스트 결과 등 모든 데이터가 영구적으로
          삭제됩니다.
        </p>
        <button
          type="button"
          onClick={() => setIsModalOpen(true)}
          className="mt-4 inline-flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm font-semibold text-red-700 transition hover:bg-red-100"
        >
          <Trash2 className="h-4 w-4" />
          회원 탈퇴
        </button>
      </div>

      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <button
            type="button"
            aria-label="닫기"
            className="absolute inset-0 bg-slate-900/50"
            onClick={closeModal}
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-account-title"
            className="relative w-full max-w-md rounded-2xl bg-white p-6 shadow-xl"
          >
            <button
              type="button"
              onClick={closeModal}
              disabled={isDeleting}
              className="absolute right-4 top-4 rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            >
              <X className="h-5 w-5" />
            </button>

            <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-red-50 text-red-600">
              <AlertTriangle className="h-6 w-6" />
            </div>

            <h2
              id="delete-account-title"
              className="text-xl font-bold text-slate-900"
            >
              정말 탈퇴하시겠습니까?
            </h2>
            <p className="mt-2 text-sm text-slate-600">
              이 작업은 되돌릴 수 없습니다. 탈퇴를 진행하려면 비밀번호를
              입력하고 아래 문구를 정확히 입력해 주세요.
            </p>

            <div className="mt-6 space-y-4">
              <div>
                <label
                  htmlFor="delete-password"
                  className="mb-1.5 block text-sm font-medium text-slate-700"
                >
                  비밀번호
                </label>
                <input
                  id="delete-password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={isDeleting}
                  autoComplete="current-password"
                  placeholder="현재 비밀번호"
                  className="input-field"
                />
              </div>

              <div>
                <label
                  htmlFor="delete-confirm"
                  className="mb-1.5 block text-sm font-medium text-slate-700"
                >
                  확인 문구
                </label>
                <input
                  id="delete-confirm"
                  type="text"
                  value={confirmText}
                  onChange={(e) => setConfirmText(e.target.value)}
                  disabled={isDeleting}
                  placeholder={DELETE_CONFIRM_TEXT}
                  className="input-field"
                />
                <p className="mt-1 text-xs text-slate-400">
                  <span className="font-medium text-red-600">
                    {DELETE_CONFIRM_TEXT}
                  </span>
                  를 입력하세요
                </p>
              </div>

              {error && (
                <div
                  role="alert"
                  className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
                >
                  {error}
                </div>
              )}
            </div>

            <div className="mt-6 flex gap-3">
              <button
                type="button"
                onClick={closeModal}
                disabled={isDeleting}
                className="btn-secondary flex-1 justify-center"
              >
                취소
              </button>
              <button
                type="button"
                onClick={handleDelete}
                disabled={!canSubmit}
                className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-red-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isDeleting ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    처리 중...
                  </>
                ) : (
                  "탈퇴하기"
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
