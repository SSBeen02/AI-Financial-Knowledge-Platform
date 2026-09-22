"use client";

function renderReportText(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);

  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={index} className="font-semibold text-slate-900">
          {part.slice(2, -2)}
        </strong>
      );
    }

    return part.split("\n").map((line, lineIndex, arr) => (
      <span key={`${index}-${lineIndex}`}>
        {line}
        {lineIndex < arr.length - 1 && <br />}
      </span>
    ));
  });
}

interface ReportContentProps {
  reportText: string;
  isFallback?: boolean;
}

export default function ReportContent({
  reportText,
  isFallback = false,
}: ReportContentProps) {
  return (
    <div className="card">
      <div className="mb-4 flex items-center justify-between gap-2">
        <h3 className="text-lg font-semibold text-slate-900">AI 맞춤형 분석</h3>
        {isFallback && (
          <span className="rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-700">
            기본 템플릿
          </span>
        )}
      </div>
      <div className="prose prose-sm max-w-none text-sm leading-relaxed text-slate-700">
        {renderReportText(reportText)}
      </div>
    </div>
  );
}
