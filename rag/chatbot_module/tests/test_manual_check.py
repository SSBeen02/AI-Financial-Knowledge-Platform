import httpx

from scripts.run_manual_check import check_expectations, render_report, run_checks


def test_expectation_pass_and_fail():
    item = {"expect_notice_contains": "자유 질문", "expect_suggested": "분업/특화"}
    assert check_expectations(item, {"notice": "자유 질문 안내", "suggested_concept": {"term": "분업/특화"}})[0] == "PASS"
    assert check_expectations(item, {"notice": None, "suggested_concept": None})[0] == "FAIL"


def test_http_error_continues_and_report_contains_details():
    def respond(request):
        if request.content and b"first" in request.content:
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(200, json={"answer": "답변 전문", "notice": None, "band": "high",
                                          "top_score": 0.8, "is_related": False, "session_started": False,
                                          "display_sources": [{"term": "용어", "score": 0.8}]})

    with httpx.Client(base_url="http://test", transport=httpx.MockTransport(respond)) as client:
        results = run_checks(client, [{"question": "first"}, {"question": "second", "expect_notice_empty": True}])
    assert [row["result"] for row in results] == ["FAIL", "PASS"]
    report = render_report(results, user_id="manual-check-user", stage="stage1")
    assert "PASS 1 / FAIL 1" in report
    assert "답변 전문" in report and "용어 · 0.8" in report
