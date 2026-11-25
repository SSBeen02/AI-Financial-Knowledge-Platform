"use client";

import { useState } from "react";
import { BarChart3, Lock, User } from "lucide-react";
import AbilityTab from "@/components/mypage/AbilityTab";
import PasswordChangeForm from "@/components/mypage/PasswordChangeForm";
import DeleteAccountSection from "@/components/mypage/DeleteAccountSection";
import type { StoredPreTestResult } from "@/lib/pretest/result-utils";
import type { FinancialReportRecord } from "@/lib/pretest/report-types";

type MyPageTab = "ability" | "password";

interface MyPageClientProps {
  displayName: string;
  email: string;
  latestResult: StoredPreTestResult | null;
  latestReport: FinancialReportRecord | null;
}

const tabs: { id: MyPageTab; label: string; icon: typeof BarChart3 }[] = [
  { id: "ability", label: "내 금융 역량", icon: BarChart3 },
  { id: "password", label: "계정 설정", icon: Lock },
];

export default function MyPageClient({
  displayName,
  email,
  latestResult,
  latestReport,
}: MyPageClientProps) {
  const [activeTab, setActiveTab] = useState<MyPageTab>("ability");

  return (
    <div className="section-container py-10">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-slate-900">마이페이지</h1>
        <p className="mt-1 text-sm text-slate-500">
          {displayName} · {email}
        </p>
      </div>

      <div className="flex flex-col gap-6 lg:flex-row">
        <aside className="lg:w-56">
          <nav className="card space-y-1 p-2">
            <div className="mb-3 flex items-center gap-2 px-3 py-2">
              <div className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-100 text-brand-600">
                <User className="h-4 w-4" />
              </div>
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-slate-900">
                  {displayName}
                </p>
                <p className="truncate text-xs text-slate-400">{email}</p>
              </div>
            </div>

            {tabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={`flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-sm font-medium transition ${
                  activeTab === tab.id
                    ? "bg-brand-50 text-brand-700"
                    : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                }`}
              >
                <tab.icon className="h-4 w-4 shrink-0" />
                {tab.label}
              </button>
            ))}
          </nav>
        </aside>

        <main className="min-w-0 flex-1">
          {activeTab === "ability" && (
            <AbilityTab
              latestResult={latestResult}
              latestReport={latestReport}
            />
          )}
          {activeTab === "password" && (
            <div className="card">
              <PasswordChangeForm />
              <DeleteAccountSection />
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
