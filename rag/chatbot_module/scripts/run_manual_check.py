"""Run an ordered manual question set against an already running local dev server."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUESTIONS = Path(__file__).with_name("manual_check_questions.json")


def check_expectations(item: dict, response: dict) -> tuple[str, list[str]]:
    notice = response.get("notice") or ""
    suggested = response.get("suggested_concept") or {}
    failures = []
    if item.get("expect_notice_contains") and item["expect_notice_contains"] not in notice:
        failures.append(f"notice에 {item['expect_notice_contains']!r} 없음")
    if item.get("expect_notice_empty") and notice:
        failures.append("notice가 비어 있지 않음")
    if item.get("expect_suggested") and suggested.get("term") != item["expect_suggested"]:
        failures.append(f"추천 용어: {suggested.get('term')!r}")
    if item.get("expect_not_contains") and item["expect_not_contains"] in notice:
        failures.append(f"notice에 금지 문구 {item['expect_not_contains']!r} 있음")
    return ("FAIL" if failures else "PASS", failures)


def _request(client: httpx.Client, method: str, path: str, *, body: dict | None = None,
             headers: dict | None = None) -> dict:
    response = client.request(method, path, json=body, headers=headers)
    response.raise_for_status()
    return response.json()


def run_checks(client: httpx.Client, items: list[dict]) -> list[dict]:
    results = []
    session_id = None
    for item in items:
        started = time.perf_counter()
        try:
            action = item.get("action", "question")
            if action == "complete":
                if not session_id:
                    raise ValueError("완료할 학습 세션이 없습니다")
                response = _request(client, "POST", f"/learning/sessions/{session_id}/complete",
                                    headers={"Idempotency-Key": str(uuid.uuid4())})
                session_id = None
            else:
                body = {"message": item["question"]}
                if action == "start_concept":
                    body["concept_id"] = item["concept_id"]
                response = _request(client, "POST", "/learning/messages", body=body)
                if response.get("session_id"):
                    session_id = response["session_id"]
            verdict, failures = check_expectations(item, response)
            results.append({"item": item, "response": response, "result": verdict,
                            "failures": failures, "seconds": time.perf_counter() - started})
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            results.append({"item": item, "response": {}, "result": "FAIL",
                            "failures": [str(exc)], "seconds": time.perf_counter() - started})
    return results


def render_report(results: list[dict], *, user_id: str, stage: str) -> str:
    passed = sum(row["result"] == "PASS" for row in results)
    lines = ["# 로컬 수동 점검", "", f"사용자: `{user_id}` · 스테이지: `{stage}`",
             f"결과: **PASS {passed} / FAIL {len(results) - passed} / 전체 {len(results)}**", ""]
    for index, row in enumerate(results, 1):
        item, response = row["item"], row["response"]
        lines += [f"## {index}. {item.get('question', item.get('action', ''))} — {row['result']}", "",
                  f"- 동작: {item.get('action', 'question')}",
                  f"- 응답 시간: {row['seconds']:.3f}초",
                  f"- 오류/기대값 불일치: {'; '.join(row['failures']) or '없음'}",
                  f"- notice: {response.get('notice')!r}",
                  f"- band: {response.get('band')!r} · top_score: {response.get('top_score')!r}",
                  f"- is_related: {response.get('is_related')!r} · session_started: {response.get('session_started')!r}",
                  f"- suggested_concept: {(response.get('suggested_concept') or {}).get('term')!r}",
                  "- display_sources (용어 · 점수): " + ", ".join(
                      f"{source.get('term')} · {source.get('score')}" for source in response.get('display_sources', [])),
                  "", "**답변 전문**", "", response.get("answer") or "(답변 없음)", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--user-id", default="manual-check-user")
    parser.add_argument("--stage", choices=[f"stage{i}" for i in range(1, 6)], default="stage1")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()
    print("주의: 지정한 사용자 기록은 초기화됩니다. 김아주 등 실제 통합테스트 계정을 사용하지 마세요.")
    items = json.loads(args.questions.read_text(encoding="utf-8"))
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=args.timeout,
                      headers={"X-User-Id": args.user_id}) as client:
        _request(client, "POST", "/learning/dev/reset")
        _request(client, "POST", "/learning/dev/stage", body={"stage": args.stage})
        results = run_checks(client, items)
    output = ROOT / "eval_outputs" / f"manual_check_{datetime.now():%Y%m%d_%H%M}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(results, user_id=args.user_id, stage=args.stage), encoding="utf-8")
    print(f"{output} (PASS {sum(row['result'] == 'PASS' for row in results)}, FAIL {sum(row['result'] == 'FAIL' for row in results)})")
    return int(any(row["result"] == "FAIL" for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
