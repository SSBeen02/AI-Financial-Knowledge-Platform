"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { CategoryScoreSummary } from "@/lib/pretest/types";

interface CategoryScoreChartProps {
  data: CategoryScoreSummary[];
}

const BAR_COLORS = [
  "#2563eb",
  "#3b82f6",
  "#60a5fa",
  "#1d4ed8",
  "#6366f1",
  "#0ea5e9",
  "#0284c7",
];

export default function CategoryScoreChart({ data }: CategoryScoreChartProps) {
  const chartData = data.map((item) => ({
    name: item.categoryLabel,
    정답: item.correct,
    전체: item.total,
    정답률: item.rate,
  }));

  return (
    <div className="w-full">
      <h3 className="mb-4 text-lg font-semibold text-slate-900">
        카테고리별 정답 현황
      </h3>
      <div className="h-80 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={chartData}
            margin={{ top: 8, right: 8, left: -16, bottom: 48 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis
              dataKey="name"
              tick={{ fontSize: 12, fill: "#64748b" }}
              angle={-25}
              textAnchor="end"
              interval={0}
              height={60}
            />
            <YAxis
              allowDecimals={false}
              tick={{ fontSize: 12, fill: "#64748b" }}
              domain={[0, 5]}
            />
            <Tooltip
              contentStyle={{
                borderRadius: "12px",
                border: "1px solid #e2e8f0",
                boxShadow: "0 4px 24px -4px rgba(37, 99, 235, 0.12)",
              }}
              formatter={(value, name, props) => {
                if (name === "정답") {
                  const total = props.payload?.전체 ?? 0;
                  return [`${value} / ${total}문제`, "정답"];
                }
                return [value, name];
              }}
            />
            <Bar dataKey="정답" radius={[8, 8, 0, 0]} maxBarSize={48}>
              {chartData.map((_, index) => (
                <Cell
                  key={`cell-${index}`}
                  fill={BAR_COLORS[index % BAR_COLORS.length]}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-4 flex flex-wrap gap-3">
        {data.map((item, index) => (
          <div
            key={item.categoryLabel}
            className="flex items-center gap-2 rounded-lg bg-slate-50 px-3 py-1.5 text-sm"
          >
            <span
              className="h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: BAR_COLORS[index % BAR_COLORS.length] }}
            />
            <span className="text-slate-600">{item.categoryLabel}</span>
            <span className="font-semibold text-brand-700">{item.rate}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}
