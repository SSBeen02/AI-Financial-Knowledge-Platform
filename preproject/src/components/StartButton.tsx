"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Loader2 } from "lucide-react";
import { getStartDestination } from "@/actions/start-flow";

interface StartButtonProps {
  label?: string;
  className?: string;
}

export default function StartButton({
  label = "시작하기",
  className = "btn-primary gap-2 px-8 py-3 text-base",
}: StartButtonProps) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  const handleClick = async () => {
    setLoading(true);
    try {
      const destination = await getStartDestination();
      router.push(destination);
    } catch {
      router.push("/login");
    } finally {
      setLoading(false);
    }
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={loading}
      className={`inline-flex items-center justify-center disabled:opacity-70 ${className}`}
    >
      {loading ? (
        <>
          <Loader2 className="h-4 w-4 animate-spin" />
          확인 중...
        </>
      ) : (
        <>
          {label}
          <ArrowRight className="h-4 w-4" />
        </>
      )}
    </button>
  );
}
