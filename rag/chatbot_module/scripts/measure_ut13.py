"""Measure UT-13 end-to-end time to the first visible SSE answer text.

This script sends real requests to a running chatbot server. Each request uses a
fresh user ID so learning state and conversation history cannot skew later runs.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from openpyxl import load_workbook


def load_cases(path: Path, qids: list[str] | None) -> list[tuple[str, str]]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        rows = workbook.active.iter_rows(values_only=True)
        header = next(rows)
        columns = {str(name): index for index, name in enumerate(header)}
        if not {"qid", "질문유형", "질문", "정답_doc_ids"} <= columns.keys():
            raise ValueError("골든셋에 qid, 질문유형, 질문, 정답_doc_ids 열이 필요합니다.")
        cases = {
            str(row[columns["qid"]]): str(row[columns["질문"]]).strip()
            for row in rows
            if row[columns["qid"]] and row[columns["질문"]]
            and row[columns["정답_doc_ids"]] and row[columns["질문유형"]] != "DB에 없음"
        }
        if qids is None:
            return list(cases.items())
        missing = [qid for qid in qids if qid not in cases]
        if missing:
            raise ValueError(f"골든셋에 없는 qid: {', '.join(missing)}")
        return [(qid, cases[qid]) for qid in qids]
    finally:
        workbook.close()


def measure(base_url: str, question: str, timeout: float) -> dict[str, object]:
    request = Request(
        base_url.rstrip("/") + "/learning/messages/stream",
        data=json.dumps({"message": question}, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "text/event-stream",
            "X-User-Id": f"ut13-{uuid.uuid4().hex}",
        },
        method="POST",
    )
    start = time.perf_counter()
    first_text_seconds = None
    done_seconds = None
    event = None
    data_lines: list[str] = []
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        for raw_line in response:
            line = raw_line.decode("utf-8").rstrip("\r\n")
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
            elif not line:
                if event and data_lines:
                    payload = json.loads("\n".join(data_lines))
                    if event == "token" and first_text_seconds is None and payload.get("delta", "").strip():
                        first_text_seconds = time.perf_counter() - start
                    elif event == "error":
                        raise RuntimeError(f"SSE error: {payload.get('code', 'unknown')}")
                    elif event == "done":
                        done_seconds = time.perf_counter() - start
                        break
                event = None
                data_lines = []
    if first_text_seconds is None or done_seconds is None:
        raise RuntimeError("첫 글자 token 또는 done 이벤트가 누락되었습니다.")
    return {"first_text_seconds": round(first_text_seconds, 3), "done_seconds": round(done_seconds, 3)}


def main() -> int:
    parser = argparse.ArgumentParser(description="UT-13 골든셋 첫 글자 응답 시간 반복 측정")
    parser.add_argument("--golden", type=Path, required=True, help="RAG_골든셋_v4.xlsx 경로")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--qids", nargs="+", help="측정할 골든셋 qid")
    selection.add_argument("--all-answered", action="store_true", help="정답 문서가 있는 모든 문항")
    parser.add_argument("--runs", type=int, default=3, help="문항당 반복 횟수 (기본 3)")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--limit-seconds", type=float, default=20)
    parser.add_argument("--output", type=Path, help="결과 JSON 저장 경로")
    parser.add_argument("--resume", action="store_true", help="기존 output의 완료된 문항·반복 회차 건너뛰기")
    parser.add_argument("--retry-failed", action="store_true", help="resume 시 실패 회차만 재측정하고 이전 실패를 보존")
    args = parser.parse_args()
    if args.runs < 1 or args.timeout <= 0 or args.limit_seconds <= 0:
        parser.error("runs, timeout, limit-seconds는 양수여야 합니다.")
    if args.resume and not args.output:
        parser.error("--resume에는 --output이 필요합니다.")
    if args.retry_failed and not args.resume:
        parser.error("--retry-failed에는 --resume이 필요합니다.")
    cases = load_cases(args.golden, None if args.all_answered else args.qids)
    qids = [qid for qid, _ in cases]
    results = []
    if args.resume and args.output.exists():
        previous = json.loads(args.output.read_text(encoding="utf-8"))
        if previous["summary"]["qids"] != qids or previous["summary"]["runs_per_qid"] != args.runs:
            parser.error("기존 output의 qids 또는 runs가 현재 실행과 다릅니다.")
        results = previous["results"]
    row_positions = {(row["qid"], row["run"]): index for index, row in enumerate(results)}
    completed_pairs = {
        (row["qid"], row["run"])
        for row in results if not args.retry_failed or row["pass"] is True
    }

    def build_report() -> dict[str, object]:
        times = [float(row["first_text_seconds"]) for row in results if "first_text_seconds" in row]
        ordered = sorted(times)
        summary = {
            "measured_at_utc": datetime.now(timezone.utc).isoformat(),
            "golden_file": args.golden.name,
            "qids": qids,
            "runs_per_qid": args.runs,
            "limit_seconds": args.limit_seconds,
            "measurement": "HTTP POST start to first non-whitespace SSE token delta",
            "attempts": len(results),
            "completed": len(times),
            "passed": sum(row["pass"] is True for row in results),
            "retried_after_failure": sum(bool(row.get("prior_results")) for row in results),
            "all_pass": len(results) == len(cases) * args.runs and all(row["pass"] is True for row in results),
            "median_seconds": round(statistics.median(times), 3) if times else None,
            "p95_seconds": round(ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)], 3) if times else None,
            "max_seconds": round(max(times), 3) if times else None,
        }
        return {"summary": summary, "results": results}

    for qid, question in cases:
        for run in range(1, args.runs + 1):
            if (qid, run) in completed_pairs:
                continue
            row: dict[str, object] = {"qid": qid, "run": run}
            try:
                row.update(measure(args.base_url, question, args.timeout))
                row["pass"] = row["first_text_seconds"] <= args.limit_seconds
            except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError) as exc:
                row["pass"] = False
                row["error"] = f"{type(exc).__name__}: {getattr(exc, 'code', str(exc))}"
            position = row_positions.get((qid, run))
            if position is None:
                row_positions[(qid, run)] = len(results)
                results.append(row)
            else:
                previous = results[position]
                row["prior_results"] = [*previous.get("prior_results", []),
                                        {key: value for key, value in previous.items() if key != "prior_results"}]
                results[position] = row
            print(json.dumps(row, ensure_ascii=False), flush=True)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(build_report(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = build_report()
    print(json.dumps(report["summary"], ensure_ascii=False), flush=True)
    return 0 if report["summary"]["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
