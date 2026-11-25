export interface FinancialReportRecord {
  id: string;
  user_id: string;
  pre_test_result_id: string;
  level_key: string;
  level_name: string;
  total_score: number;
  accuracy_rate: number;
  report_text: string;
  is_fallback: boolean;
  created_at: string;
}

export interface FinancialReportResponse {
  report: FinancialReportRecord;
  levelKey: string;
  levelName: string;
  isFallback: boolean;
}
