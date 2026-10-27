import unittest

from schemas.llm_report import LlmReportAnalysis, LevelDiagnosis, WrongAnswerAnalysis
from services.report_summary import add_lowest_stage_summary


class LowestStageSummaryTest(unittest.TestCase):
    def report(self):
        return LlmReportAnalysis(
            level_diagnosis=LevelDiagnosis(overall_level="보완필요", summary="수준 설명이오.", domain_comments=[]),
            wrong_answer_analysis=WrongAnswerAnalysis(summary="오답 설명이오.", items=[]),
            recommendations=[],
        )

    def rows(self, scores):
        domains = [
            ("finance_investment", "금융·투자"),
            ("macroeconomy_monetary_fiscal_policy", "거시경제·통화·재정"),
            ("international_economy_industry_technology", "국제경제·산업·기술"),
            ("socioeconomic_phenomena_consumer_life", "사회경제·소비생활"),
        ]
        return [dict(domain=d, domain_label=label, score=score) for (d, label), score in zip(domains, scores)]

    def test_single_lowest_stage_in_both_introductions(self):
        original=self.report()
        result=add_lowest_stage_summary(original,self.rows([83.3,66.7,50,16.7]))
        for text in [result.level_diagnosis.summary,result.wrong_answer_analysis.summary]:
            self.assertIn("Stage1 사회경제·소비생활의 17점",text)
            self.assertNotIn("Stage2",text)
        self.assertEqual(original.level_diagnosis.summary,"수준 설명이오.")

    def test_ties_include_all_lowest_in_stage_order(self):
        result=add_lowest_stage_summary(self.report(),self.rows([33.3,66.7,50,33.3]))
        text=result.wrong_answer_analysis.summary
        self.assertIn("공동 최저점",text)
        self.assertLess(text.index("Stage1"),text.index("Stage2"))
        self.assertNotIn("Stage3",text)

    def test_all_tied_includes_four_stages(self):
        result=add_lowest_stage_summary(self.report(),self.rows([33.3]*4))
        for n in range(1,5):self.assertIn(f"Stage{n}",result.level_diagnosis.summary)

    def test_perfect_has_no_fabricated_weakness(self):
        result=add_lowest_stage_summary(self.report(),self.rows([100]*4))
        self.assertIn("모두 100점이며, 오답은 없소",result.wrong_answer_analysis.summary)
        self.assertNotIn("최저",result.level_diagnosis.summary)

    def test_repeated_lookup_does_not_duplicate_fact(self):
        rows=self.rows([0,33.3,50,66.7])
        once=add_lowest_stage_summary(self.report(),rows)
        twice=add_lowest_stage_summary(once,rows)
        self.assertEqual(once,twice)

    def test_no_scores_leaves_report_unchanged(self):
        original=self.report()
        self.assertEqual(original,add_lowest_stage_summary(original,[]))
