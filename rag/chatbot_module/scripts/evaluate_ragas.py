"""Prepare and score a read-only golden-set answer evaluation.

The existing retrieval and answer adapters are reused without creating chat
sessions. The local Qdrant SQLite file is opened read-only and copied into an
in-memory Qdrant collection; the source file is never modified.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
from datetime import datetime, timezone
import io
import json
import math
import pickle
import pickletools
import re
import sqlite3
import sys
from time import perf_counter
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chatbot.config import Settings
from chatbot.concepts import load_stage_catalog
from chatbot.llm import OpenAIAdapter, UpstageAdapter
from chatbot.prompts import build_answer_prompt
from chatbot.retrieval import ConceptCache, Retriever
from chatbot.service import _ensure_answer_suffixes, _message_notice
from chatbot.tone import low_band_notice

REQUIRED_GOLDEN_COLUMNS = {"qid", "질문유형", "질문", "정답_doc_ids"}
OUT_OF_DB_TYPE = "DB에 없음"
OUT_OF_SCOPE_TYPE = "범위 밖 용어"
NOTICE_TYPES = {OUT_OF_DB_TYPE, OUT_OF_SCOPE_TYPE}
SCORE_THRESHOLD = 0.7
UNSAFE_PICKLE_OPS = {"REDUCE", "NEWOBJ_EX", "EXT1", "EXT2", "EXT4", "PERSID", "BINPERSID"}
REFERENCE_SECOND_SENTENCE_ENDINGS = (
    "합성어.", "약자이다.", "나누어 진다.", "구성된다.",
    "타격을 입게 된다.", "있을 수 있다.", "제목이기도 하다.",
)


class _QdrantPointUnpickler(pickle.Unpickler):
    """Only the two Qdrant data classes used by local PointStruct rows."""

    def find_class(self, module: str, name: str) -> type[Any]:
        from qdrant_client import models

        if module == "qdrant_client.http.models.models" and name in {"PointStruct", "SparseVector"}:
            return getattr(models, name)
        raise ValueError(f"Unsupported class in Qdrant point: {module}.{name}")


def _decode_point(blob: bytes) -> Any:
    if any(op.name in UNSAFE_PICKLE_OPS for op, _, _ in pickletools.genops(blob)):
        raise ValueError("Unsupported pickle operation in Qdrant point")
    return _QdrantPointUnpickler(io.BytesIO(blob)).load()


def load_golden(path: Path) -> list[dict[str, Any]]:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook["골든셋"]
        rows = sheet.values
        headers = next(rows)
        missing = REQUIRED_GOLDEN_COLUMNS - set(headers)
        if missing:
            raise ValueError(f"골든셋에 필요한 열이 없습니다: {', '.join(sorted(missing))}")
        cases = [dict(zip(headers, row)) for row in rows if row[0]]
        if not cases or any(not row["질문"] for row in cases):
            raise ValueError("골든셋 질문이 비어 있습니다.")
        return cases
    finally:
        workbook.close()


def filter_cases(
    cases: list[dict[str, Any]], qids: list[str] | None, types: list[str] | None
) -> list[dict[str, Any]]:
    def values(raw: list[str] | None) -> set[str] | None:
        return {part.strip() for item in raw for part in item.split(",") if part.strip()} if raw else None

    wanted_qids, wanted_types = values(qids), values(types)
    available_qids = {str(row["qid"]) for row in cases}
    available_types = {str(row.get("질문유형", row.get("question_type"))) for row in cases}
    if wanted_qids and wanted_qids - available_qids:
        raise ValueError(f"없는 qid: {', '.join(sorted(wanted_qids - available_qids))}")
    if wanted_types and wanted_types - available_types:
        raise ValueError(f"없는 질문유형: {', '.join(sorted(wanted_types - available_types))}")
    selected = [
        row for row in cases
        if (wanted_qids is None or str(row["qid"]) in wanted_qids)
        and (wanted_types is None or str(row.get("질문유형", row.get("question_type"))) in wanted_types)
    ]
    if not selected:
        raise ValueError("조건에 맞는 문항이 없습니다.")
    return selected


def select_cases(cases: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    """Round-robin across question types, preserving order within each type."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in cases:
        groups.setdefault(str(row.get("질문유형", row.get("question_type"))), []).append(row)
    chosen: list[dict[str, Any]] = []
    while any(groups.values()) and (limit is None or len(chosen) < limit):
        for group in groups.values():
            if group and (limit is None or len(chosen) < limit):
                chosen.append(group.pop(0))
    return chosen


def load_local_collection(sqlite_path: Path, collection: str) -> Any:
    """Copy local Qdrant point rows to memory without opening its storage path for writing."""
    from qdrant_client import QdrantClient, models

    client = QdrantClient(":memory:")
    client.create_collection(
        collection_name=collection,
        vectors_config={"dense": models.VectorParams(size=1024, distance=models.Distance.COSINE)},
        sparse_vectors_config={"sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)},
    )
    connection = sqlite3.connect(f"file:{sqlite_path.as_posix()}?mode=ro", uri=True)
    try:
        batch = []
        for (blob,) in connection.execute("SELECT point FROM points"):
            batch.append(_decode_point(blob))
            if len(batch) == 64:
                client.upsert(collection_name=collection, points=batch, wait=True)
                batch.clear()
        if batch:
            client.upsert(collection_name=collection, points=batch, wait=True)
    finally:
        connection.close()
    return client


def _answer_adapter(settings: Settings, counter: list[int]) -> Any:
    import httpx
    from openai import OpenAI

    def count_request(_request: httpx.Request) -> None:
        counter[0] += 1

    transport = httpx.Client(event_hooks={"request": [count_request]})
    if settings.llm_provider == "upstage":
        client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url, http_client=transport)
        return UpstageAdapter(settings, client=client)
    if settings.llm_provider == "openai":
        client = OpenAI(api_key=settings.llm_api_key, http_client=transport)
        return OpenAIAdapter(settings, client=client)
    transport.close()
    if settings.llm_provider == "fake":
        raise ValueError("LLM_PROVIDER=fake 답변은 품질 평가에 사용할 수 없습니다.")
    raise ValueError(f"지원하지 않는 LLM_PROVIDER: {settings.llm_provider}")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def _first_reference_sentences(text: str) -> str:
    """Return one or two untouched dictionary sentences after the 설명 label."""
    if "설명:" not in text:
        raise ValueError("사전 payload에 설명: 구간이 없습니다.")
    description = text.split("설명:", 1)[1].strip()
    if not description:
        raise ValueError("사전 payload의 설명: 구간이 비었습니다.")
    endings = [match.end() for match in re.finditer(r"[.!?](?=\s|[가-힣]|[A-Z]{2})", description)]
    if not endings:
        return description
    first = description[:endings[0]]
    count = 2 if first.endswith(REFERENCE_SECOND_SENTENCE_ENDINGS) and len(endings) > 1 else 1
    return description[:endings[count - 1]].strip()


def build_references(args: argparse.Namespace) -> None:
    """Extract references from the first gold document without calling an LLM."""
    cases = [row for row in load_golden(args.golden) if row["질문유형"] != OUT_OF_DB_TYPE]
    wanted = {
        str(row["qid"]): re.split(r"[;,]", str(row["정답_doc_ids"]))[0].strip()
        for row in cases
    }
    if any(not doc_id or doc_id in {"(없음)", "없음"} for doc_id in wanted.values()):
        raise ValueError("정답 있는 문항의 첫 번째 정답_doc_id가 비었습니다.")
    texts: dict[str, str] = {}
    connection = sqlite3.connect(f"file:{args.sqlite.as_posix()}?mode=ro", uri=True)
    try:
        for (blob,) in connection.execute("SELECT point FROM points"):
            payload = _decode_point(blob).payload or {}
            doc_id = str(payload.get("concept_id") or payload.get("doc_id") or "")
            if doc_id in wanted.values():
                texts[doc_id] = str(payload.get("text") or "")
    finally:
        connection.close()
    missing = sorted(set(wanted.values()) - texts.keys())
    if missing:
        raise ValueError(f"Qdrant 원본에서 정답 문서를 찾지 못했습니다: {', '.join(missing)}")
    references = [
        {"qid": qid, "ref_doc_id": doc_id, "reference": _first_reference_sentences(texts[doc_id])}
        for qid, doc_id in wanted.items()
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["qid", "ref_doc_id", "reference"])
        writer.writeheader()
        writer.writerows(references)
    print(f"사전 원문 reference {len(references)}개 저장: {args.output}")


async def _score_reference_rows(rows: list[dict[str, Any]], references: dict[str, str],
                                output: Path, settings: Settings) -> int:
    """Score saved answers against verbatim dictionary references; never regenerate answers."""
    import httpx
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory
    from ragas.metrics.collections import FactualCorrectness

    completed = {str(row["qid"]) for row in _read_jsonl(output)}
    pending = [row for row in rows if str(row["qid"]) not in completed]
    if not pending:
        return 0
    if settings.llm_provider not in {"upstage", "openai"}:
        raise ValueError("RAGAS 평가는 Upstage 또는 OpenAI 판정 모델이 필요합니다.")
    requests = [0]

    async def count_request(_request: httpx.Request) -> None:
        requests[0] += 1

    transport = httpx.AsyncClient(event_hooks={"request": [count_request]})
    client = AsyncOpenAI(
        api_key=settings.llm_api_key,
        **({"base_url": settings.llm_base_url} if settings.llm_provider == "upstage" else {}),
        http_client=transport,
    )
    try:
        judge = llm_factory(settings.relevance_model, provider="openai", client=client,
                            temperature=0, max_tokens=4096)
        metric = FactualCorrectness(llm=judge, mode="recall")
        for row in pending:
            qid = str(row["qid"])
            before = requests[0]
            started = perf_counter()
            result = await metric.ascore(
                response=_answer_for_scoring(str(row["response_for_scoring"])),
                reference=references[qid],
            )
            value = float(result.value)
            if not math.isfinite(value):
                raise ValueError(f"{qid}: FactualCorrectness recall 결과가 유효한 수가 아닙니다.")
            _append_jsonl(output, {
                "qid": qid, "question_type": row["question_type"], "factual_recall": value,
                "judge_api_requests": requests[0] - before,
                "score_seconds": round(perf_counter() - started, 3),
            })
            print(f"{qid}: factual_recall={value}, judge_calls={requests[0] - before}", flush=True)
    finally:
        await client.close()
    return requests[0]


def score_references(args: argparse.Namespace) -> None:
    rows = [row for row in _read_jsonl(args.input) if row["question_type"] != OUT_OF_DB_TYPE]
    if len(rows) != 78 or len({str(row["qid"]) for row in rows}) != 78:
        raise ValueError(f"정답 있는 고유 78문항이 필요합니다: 현재 {len(rows)}행")
    with args.references.open(encoding="utf-8-sig", newline="") as stream:
        reference_rows = list(csv.DictReader(stream))
    references = {row["qid"]: row["reference"] for row in reference_rows}
    if len(reference_rows) != 78 or set(references) != {str(row["qid"]) for row in rows}:
        raise ValueError("reference CSV의 qid가 정답 있는 78문항과 일치하지 않습니다.")
    if any(not value.strip() for value in references.values()):
        raise ValueError("빈 reference가 있습니다.")
    already = _read_jsonl(args.output)
    if already and not args.resume:
        raise FileExistsError(f"점수 파일이 이미 있습니다: {args.output} (--resume 사용)")
    pending = len(rows) - len({str(row["qid"]) for row in already})
    print(f"저장된 답변 78개 사용; 신규 채점 {pending}개, 예상 판정 API 호출 {pending * 4}회(재시도 제외)")
    if not args.run:
        print("미리보기만 완료했습니다. 실제 판정은 --run에서 실행합니다.")
        return
    settings = Settings()
    started = perf_counter()
    calls = asyncio.run(_score_reference_rows(rows, references, args.output, settings))
    scored_by_qid = {str(row["qid"]): row for row in _read_jsonl(args.output)}
    if set(scored_by_qid) != {str(row["qid"]) for row in rows}:
        raise ValueError("일부 문항의 점수가 없습니다. --resume으로 다시 실행하세요.")
    scored = [scored_by_qid[str(row["qid"])] for row in rows]
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    with args.csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["qid", "question_type", "factual_recall", "below_0_7"])
        writer.writeheader()
        writer.writerows({"qid": row["qid"], "question_type": row["question_type"],
                          "factual_recall": row["factual_recall"],
                          "below_0_7": row["factual_recall"] < SCORE_THRESHOLD} for row in scored)
    groups: dict[str, list[float]] = {}
    for row in scored:
        groups.setdefault(str(row["question_type"]), []).append(float(row["factual_recall"]))
    below_qids = [str(row["qid"]) for row in scored if row["factual_recall"] < SCORE_THRESHOLD]
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    summary["factual_correctness_recall"] = {
        "reference_file": str(args.references), "judge_model": settings.relevance_model,
        "count": len(scored), "mean": mean(float(row["factual_recall"]) for row in scored),
        "by_type": {kind: {"count": len(values), "mean": mean(values)}
                    for kind, values in groups.items()},
        "below_0_7_count": len(below_qids), "below_0_7_qids": below_qids,
        "judge_api_requests_total": sum(int(row["judge_api_requests"]) for row in scored),
        "judge_api_requests_this_run": calls,
        "score_seconds_this_run": round(perf_counter() - started, 3),
    }
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["factual_correctness_recall"], ensure_ascii=False), flush=True)


def _answer_for_scoring(answer: str) -> str:
    """Remove attribution footers; score the explanatory answer itself."""
    lines = answer.strip().splitlines()
    while lines:
        candidate = lines[-1].strip().lstrip("* ")
        if not candidate or candidate.startswith(("핵심 정의 출처:", "출처:", "※ 보충 설명은")):
            lines.pop()
            continue
        break
    return "\n".join(lines).strip()


def _notice_fields(
    *, row: dict[str, Any], retrieval: Any, catalog: Any,
    cache: ConceptCache | None, tone: str,
) -> dict[str, Any]:
    question_type = row.get("질문유형", row.get("question_type"))
    if question_type not in NOTICE_TYPES:
        return {"notice": None, "low_band_pass": None, "notice_pass": None,
                "scope_notice_returned": None, "notice_checked": False}
    assert cache is not None
    notice = _message_notice(
        catalog=catalog, status_service=_FreshStatus(), cache=cache,
        user_id="ragas-evaluation", question=str(row.get("질문", row.get("user_input"))),
        retrieval=retrieval, chat_tone=tone,
    )
    return {
        "notice": notice,
        "low_band_pass": retrieval.band == "low" if question_type == OUT_OF_DB_TYPE else None,
        "notice_pass": notice == low_band_notice(tone) if question_type == OUT_OF_DB_TYPE else None,
        "scope_notice_returned": notice is not None if question_type == OUT_OF_SCOPE_TYPE else None,
        "notice_checked": True,
    }


class _FreshStatus:
    """Read-only Stage 1 state for free-question notice evaluation."""

    def get_current_stage(self, _user_id: str) -> str:
        return "stage1"

    def get_statuses(self, _user_id: str, _stage: str) -> dict[str, str]:
        return {}


def collect(args: argparse.Namespace) -> None:
    started = perf_counter()
    cases = select_cases(filter_cases(load_golden(args.golden), args.qids, args.types), args.limit)
    if not args.sqlite.is_file():
        raise FileNotFoundError(args.sqlite)
    print(f"선택 문항: {', '.join(str(row['qid']) for row in cases)}")
    if not args.run:
        print("미리보기만 완료했습니다. 실제 검색·답변 생성은 --run에서 실행합니다.")
        return
    if args.output.exists() and not args.resume:
        raise FileExistsError(f"결과 파일이 이미 있습니다: {args.output} (--resume 사용)")

    settings = Settings()
    if settings.qdrant_collection != "sisa_terms":
        raise ValueError("이 SQLite 파일은 sisa_terms 컬렉션용입니다. QDRANT_COLLECTION을 확인하세요.")
    from rag_common import DenseEncoder

    client = load_local_collection(args.sqlite, settings.qdrant_collection)
    dense = DenseEncoder(settings.dense_model)
    retriever = Retriever(client, dense, settings)
    counter = [0]
    llm = _answer_adapter(settings, counter)
    catalog = load_stage_catalog(settings.stages_json_path)
    cache = ConceptCache(client, settings.qdrant_collection, catalog.by_concept) if any(
        row["질문유형"] in NOTICE_TYPES for row in cases
    ) else None
    existing_rows = _read_jsonl(args.output)
    existing_by_qid = {str(row["qid"]): row for row in existing_rows}
    refreshed = new_count = 0
    for row in cases:
        qid = str(row["qid"])
        if qid in existing_by_qid:
            saved = existing_by_qid[qid]
            if row["질문유형"] in NOTICE_TYPES and not saved.get("notice_checked"):
                retrieval = retriever.search(str(row["질문"]))
                saved.update(_notice_fields(row=row, retrieval=retrieval, catalog=catalog, cache=cache, tone=settings.chat_tone))
                refreshed += 1
            continue
        row_started = perf_counter()
        requests_before = counter[0]
        question = str(row["질문"])
        retrieval = retriever.search(question)
        notice_fields = _notice_fields(
            row=row, retrieval=retrieval, catalog=catalog, cache=cache, tone=settings.chat_tone,
        )
        prompt = build_answer_prompt(
            question=question,
            current_concept=None,
            band=retrieval.band,
            sources=retrieval.sources,
            history=[],
            previous_attempt_history=[],
            stage=None,
            attempt=None,
            chat_tone=settings.chat_tone,
            knowledge_mode=settings.answer_knowledge_mode,
            chat_emoji=settings.chat_emoji,
        )
        generated = llm.generate(prompt)
        answer = _ensure_answer_suffixes(generated, retrieval, settings.answer_knowledge_mode)
        contexts = [source.text for source in retrieval.sources if source.text]
        _append_jsonl(
            args.output,
            {
                "qid": qid,
                "question_type": row["질문유형"],
                "user_input": question,
                "response": answer,
                "response_for_scoring": _answer_for_scoring(answer),
                "retrieved_contexts": contexts,
                "retrieved_doc_ids": [source.concept_id for source in retrieval.sources],
                "context_doc_ids": [source.concept_id for source in retrieval.sources if source.text],
                "gold_doc_ids": str(row["정답_doc_ids"]),
                "band": retrieval.band,
                "top_score": retrieval.top_score,
                **notice_fields,
                "answer_knowledge_mode": settings.answer_knowledge_mode,
                "generator_provider": settings.llm_provider,
                "generator_model": settings.llm_model,
                "answer_api_requests": counter[0] - requests_before,
                "collect_seconds": round(perf_counter() - row_started, 3),
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "golden_version": args.golden.stem,
            },
        )
        new_count += 1
        print(f"{qid}: band={retrieval.band}, contexts={len(contexts)}")
    llm._client.close()
    if refreshed:
        current_rows = _read_jsonl(args.output)
        temporary = args.output.with_suffix(".notice_tmp.jsonl")
        temporary.write_text(
            "".join(json.dumps(existing_by_qid.get(str(row["qid"]), row), ensure_ascii=False) + "\n"
                    for row in current_rows),
            encoding="utf-8",
        )
        temporary.replace(args.output)
    meta = {
        "selected_qids": [str(row["qid"]) for row in cases],
        "collect_wall_seconds": round(perf_counter() - started, 3),
        "answer_api_requests_this_run": counter[0],
        "notices_refreshed": refreshed,
    }
    meta_path = args.output.with_suffix(".collect_meta.json")
    if new_count or not meta_path.exists():
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False))


async def _score_rows(rows: list[dict[str, Any]], settings: Settings, output: Path) -> int:
    import httpx
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory
    from ragas.metrics.collections import AnswerRelevancy, Faithfulness
    from ragas.embeddings.base import BaseRagasEmbedding
    from rag_common import DenseEncoder

    class LocalDenseEmbeddings(BaseRagasEmbedding):
        def __init__(self, encoder: DenseEncoder):
            super().__init__()
            self.encoder = encoder

        def embed_text(self, value: str, **kwargs: Any) -> list[float]:
            return self.encoder.encode([value])[0].tolist()

        async def aembed_text(self, value: str, **kwargs: Any) -> list[float]:
            return await asyncio.to_thread(self.embed_text, value)

    completed = {str(row["qid"]) for row in _read_jsonl(output)}
    count = [0]
    async def count_request(_request: httpx.Request) -> None:
        count[0] += 1

    if settings.llm_provider not in {"upstage", "openai"}:
        raise ValueError("RAGAS 평가는 Upstage 또는 OpenAI 판정 모델이 필요합니다.")
    transport = httpx.AsyncClient(event_hooks={"request": [count_request]})
    judge_client = AsyncOpenAI(
        api_key=settings.llm_api_key,
        **({"base_url": settings.llm_base_url} if settings.llm_provider == "upstage" else {}),
        http_client=transport,
    )
    try:
        answer_rows = [row for row in rows if row["question_type"] != OUT_OF_DB_TYPE and str(row["qid"]) not in completed]
        if answer_rows:
            judge = llm_factory(
                settings.relevance_model, provider="openai", client=judge_client,
                temperature=0, max_tokens=4096,
            )
            faithfulness = Faithfulness(llm=judge)
            relevancy = AnswerRelevancy(llm=judge, embeddings=LocalDenseEmbeddings(DenseEncoder(settings.dense_model)))
        for row in rows:
            qid = str(row["qid"])
            if qid in completed:
                continue
            row_started = perf_counter()
            before = count[0]
            relevance_value = faithfulness_value = None
            if row["question_type"] != OUT_OF_DB_TYPE:
                question = str(row["user_input"])
                response = _answer_for_scoring(str(row["response_for_scoring"]))
                contexts = row["retrieved_contexts"]
                relevance_result = await relevancy.ascore(user_input=question, response=response)
                faithfulness_result = (
                    await faithfulness.ascore(user_input=question, response=response, retrieved_contexts=contexts)
                    if contexts else None
                )
                relevance_value = float(relevance_result.value)
                faithfulness_value = float(faithfulness_result.value) if faithfulness_result is not None else None
            _append_jsonl(output, {
                "qid": qid,
                "question_type": row["question_type"],
                "band": row["band"],
                "answer_relevancy": relevance_value,
                "faithfulness": faithfulness_value,
                "judge_api_requests": count[0] - before,
                "score_seconds": round(perf_counter() - row_started, 3),
            })
            print(f"{qid}: answer_relevancy={relevance_value}, faithfulness={faithfulness_value}, judge_calls={count[0] - before}")
    finally:
        await judge_client.close()
    return count[0]


async def _trace_faithfulness(row: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Expose RAGAS's parsed claims and NLI verdicts for one saved answer."""
    import httpx
    from openai import AsyncOpenAI
    from ragas.llms import llm_factory
    from ragas.metrics.collections import Faithfulness

    requests = [0]

    async def count_request(_request: httpx.Request) -> None:
        requests[0] += 1

    if settings.llm_provider not in {"upstage", "openai"}:
        raise ValueError("RAGAS 진단에는 Upstage 또는 OpenAI 판정 모델이 필요합니다.")
    transport = httpx.AsyncClient(event_hooks={"request": [count_request]})
    client = AsyncOpenAI(
        api_key=settings.llm_api_key,
        **({"base_url": settings.llm_base_url} if settings.llm_provider == "upstage" else {}),
        http_client=transport,
    )
    trace: dict[str, Any] = {
        "qid": row["qid"], "judge_model": settings.relevance_model,
        "contexts": row["retrieved_contexts"], "parsed": False,
    }
    try:
        judge = llm_factory(settings.relevance_model, provider="openai", client=client,
                            temperature=0, max_tokens=4096)
        metric = Faithfulness(llm=judge)
        response = _answer_for_scoring(str(row["response_for_scoring"]))
        claims = await metric._create_statements(str(row["user_input"]), response)
        trace["claims"] = claims
        verdicts = await metric._create_verdicts(claims, "\n".join(row["retrieved_contexts"]))
        trace["verdicts"] = [item.model_dump() for item in verdicts.statements]
        score = metric._compute_score(verdicts)
        trace["score"] = score if math.isfinite(score) else None
        trace["claim_count"] = len(claims)
        trace["verdict_count"] = len(verdicts.statements)
        trace["parsed"] = True
    except Exception as exc:
        trace["error_type"] = type(exc).__name__
    finally:
        trace["judge_api_requests"] = requests[0]
        await client.close()
    return trace


def trace(args: argparse.Namespace) -> None:
    rows = [row for row in _read_jsonl(args.input) if str(row.get("qid")) == args.qid]
    if len(rows) != 1:
        raise ValueError(f"입력에서 qid를 정확히 하나 찾을 수 없습니다: {args.qid}")
    if not args.run:
        print(f"진단 대상: {args.qid}; 판정 LLM 호출은 --run에서 실행합니다.")
        return
    result = asyncio.run(_trace_faithfulness(rows[0], Settings()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: result.get(key) for key in
                      ("qid", "parsed", "claim_count", "verdict_count", "score", "judge_api_requests", "error_type")},
                     ensure_ascii=False))


def _average(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return mean(present) if present else None


def _gold_in_contexts(sample: dict[str, Any]) -> bool | None:
    gold_ids = {
        part.strip() for part in re.split(r"[;,]", str(sample.get("gold_doc_ids", "")))
        if part.strip() not in {"", "(없음)", "없음"}
    }
    if not gold_ids:
        return None
    context_ids = sample.get("context_doc_ids")
    if context_ids is None:
        retrieved_ids = sample.get("retrieved_doc_ids", [])
        if len(retrieved_ids) != len(sample["retrieved_contexts"]):
            return None
        context_ids = retrieved_ids
    return bool(gold_ids.intersection(context_ids))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "qid", "question_type", "question", "answer", "faithfulness", "answer_relevancy",
        "band", "retrieved_doc_ids", "gold_in_contexts", "below_0_7", "low_band_pass",
        "notice_pass", "scope_notice_returned", "notice",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows({key: row.get(key) for key in columns} for row in rows)


def score(args: argparse.Namespace) -> None:
    started = perf_counter()
    rows = select_cases(filter_cases(_read_jsonl(args.input), args.qids, args.types), args.limit)
    if not rows:
        raise ValueError("평가할 입력 문항이 없습니다.")
    required = {"qid", "question_type", "user_input", "response", "response_for_scoring", "retrieved_contexts", "band"}
    for row in rows:
        if missing := required - set(row):
            raise ValueError(f"{row.get('qid', '?')} 필수 필드 누락: {', '.join(sorted(missing))}")
    print(f"평가 대상: {', '.join(str(row['qid']) for row in rows)}")
    if not args.run and not args.report_only:
        print("미리보기만 완료했습니다. RAGAS 판정 LLM 호출은 --run에서 실행합니다.")
        return
    if args.run and args.report_only:
        raise ValueError("--run과 --report-only는 함께 사용할 수 없습니다.")
    if args.report_only and not args.output.exists():
        raise FileNotFoundError(f"기존 점수 파일이 없습니다: {args.output}")
    if args.run and args.output.exists() and not args.resume:
        raise FileExistsError(f"점수 파일이 이미 있습니다: {args.output} (--resume 사용)")
    settings = Settings()
    calls_this_run = 0 if args.report_only else asyncio.run(_score_rows(rows, settings, args.output))
    scored_by_qid = {str(row["qid"]): row for row in _read_jsonl(args.output)}
    scored = [scored_by_qid[str(row["qid"])] for row in rows]
    answer_pairs = [(sample, result) for sample, result in zip(rows, scored) if sample["question_type"] != OUT_OF_DB_TYPE]
    missing = [sample for sample in rows if sample["question_type"] == OUT_OF_DB_TYPE]
    outside = [sample for sample in rows if sample["question_type"] == OUT_OF_SCOPE_TYPE]
    outside_checked = [sample for sample in outside if sample.get("scope_notice_returned") is not None]
    csv_rows = []
    for sample, result in zip(rows, scored):
        metrics = [result.get("faithfulness"), result.get("answer_relevancy")]
        below = any(value is not None and value < SCORE_THRESHOLD for value in metrics)
        csv_rows.append({
            "qid": sample["qid"], "question_type": sample["question_type"],
            "question": sample["user_input"], "answer": sample["response"],
            "faithfulness": result.get("faithfulness"),
            "answer_relevancy": result.get("answer_relevancy"), "band": sample["band"],
            "retrieved_doc_ids": "; ".join(sample.get("retrieved_doc_ids", [])),
            "gold_in_contexts": _gold_in_contexts(sample),
            "below_0_7": below if sample["question_type"] != OUT_OF_DB_TYPE else None,
            "low_band_pass": sample.get("low_band_pass"), "notice_pass": sample.get("notice_pass"),
            "scope_notice_returned": sample.get("scope_notice_returned"),
            "notice": sample.get("notice"),
        })
    _write_csv(args.csv, csv_rows)
    _write_csv(args.below_csv, [row for row in csv_rows if row["below_0_7"]])
    gold_rows = [row for row in csv_rows if row["gold_in_contexts"] is not None]
    low_faithfulness = [row for row in csv_rows if row["faithfulness"] is not None and row["faithfulness"] < SCORE_THRESHOLD]
    low_missing = [row["qid"] for row in low_faithfulness if row["gold_in_contexts"] is False]
    low_present = [row["qid"] for row in low_faithfulness if row["gold_in_contexts"] is True]
    low_unknown = [row["qid"] for row in low_faithfulness if row["gold_in_contexts"] is None]
    source_candidates = [
        row["qid"] for row in csv_rows
        if row["gold_in_contexts"] is False
        and "핵심 정의 출처: 시사경제용어사전" in row["answer"]
    ]
    by_type = {}
    for question_type in dict.fromkeys(sample["question_type"] for sample in rows):
        group = [(sample, result) for sample, result in answer_pairs if sample["question_type"] == question_type]
        if group:
            by_type[question_type] = {
                "count": len(group),
                "faithfulness_mean": _average([result.get("faithfulness") for _, result in group]),
                "answer_relevancy_mean": _average([result.get("answer_relevancy") for _, result in group]),
            }
            if question_type == OUT_OF_SCOPE_TYPE:
                by_type[question_type]["notice_return_rate"] = (
                    mean(sample["scope_notice_returned"] for sample in outside_checked)
                    if outside_checked else None
                )
    if missing:
        by_type[OUT_OF_DB_TYPE] = {"count": len(missing), "faithfulness_mean": None, "answer_relevancy_mean": None}
    meta_path = args.input.with_suffix(".collect_meta.json")
    collect_meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    selected_qids = [str(row["qid"]) for row in rows]
    collect_wall = collect_meta.get("collect_wall_seconds") if collect_meta.get("selected_qids") == selected_qids else None
    score_wall = round(perf_counter() - started, 3)
    summary = {
        "settings": {
            "generator_model": settings.llm_model,
            "judge_model": settings.relevance_model,
            "embedding_model": settings.dense_model,
            "chat_tone": settings.chat_tone,
            "answer_knowledge_mode": settings.answer_knowledge_mode,
            "llm_temperature": settings.llm_temperature,
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "golden_version": rows[0].get("golden_version", "unknown"),
            "report_only": args.report_only,
        },
        "selected_count": len(rows),
        "answer_cases": len(answer_pairs),
        "gold_in_contexts": {
            "evaluated_count": len(gold_rows),
            "included_count": sum(row["gold_in_contexts"] for row in gold_rows),
            "rate": mean(row["gold_in_contexts"] for row in gold_rows) if gold_rows else None,
            "not_evaluated_count": len(answer_pairs) - len(gold_rows),
        },
        "low_faithfulness_by_gold": {
            "threshold": SCORE_THRESHOLD,
            "retrieval_failure": {"count": len(low_missing), "qids": low_missing},
            "generation_stage": {"count": len(low_present), "qids": low_present},
            "unknown": {"count": len(low_unknown), "qids": low_unknown},
        },
        "source_misattribution_candidates": {
            "count": len(source_candidates), "qids": source_candidates,
        },
        "overall": {
            "faithfulness_mean": _average([result.get("faithfulness") for _, result in answer_pairs]),
            "answer_relevancy_mean": _average([result.get("answer_relevancy") for _, result in answer_pairs]),
        },
        "by_type": by_type,
        "out_of_db": {
            "count": len(missing),
            "low_band_pass_count": sum(sample.get("low_band_pass") is True for sample in missing),
            "low_band_pass_rate": mean(sample.get("low_band_pass") is True for sample in missing) if missing else None,
            "notice_pass_count": sum(sample.get("notice_pass") is True for sample in missing),
            "notice_pass_rate": mean(sample.get("notice_pass") is True for sample in missing) if missing else None,
            "both_pass_rate": mean(sample.get("low_band_pass") is True and sample.get("notice_pass") is True for sample in missing) if missing else None,
            "notice_state": "fresh_stage1",
        },
        "out_of_scope_terms": {
            "count": len(outside),
            "notice_evaluated_count": len(outside_checked),
            "notice_not_evaluated_count": len(outside) - len(outside_checked),
            "notice_return_count": sum(sample["scope_notice_returned"] for sample in outside_checked),
            "notice_return_rate": mean(sample["scope_notice_returned"] for sample in outside_checked) if outside_checked else None,
            "notice_state": "fresh_stage1",
        },
        "faithfulness_not_applicable": sum(result.get("faithfulness") is None for _, result in answer_pairs),
        "below_0_7_count": sum(row["below_0_7"] is True for row in csv_rows),
        "api_requests": {
            "answer": sum(sample.get("answer_api_requests", 0) for sample in rows),
            "judge": sum(result.get("judge_api_requests", 0) for result in scored),
            "judge_this_run": calls_this_run,
        },
        "elapsed_seconds": {
            "collect_wall": collect_wall,
            "score_wall_this_run": score_wall,
            "completed_score_rows": round(sum(result.get("score_seconds", 0) for result in scored), 3),
            "combined_wall": round(collect_wall + score_wall, 3) if collect_wall is not None and not args.resume and not args.report_only else None,
        },
    }
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("collect", help="기존 골든셋 질문으로 실제 답변과 검색 원문 수집")
    prepare.add_argument("--golden", type=Path, required=True)
    prepare.add_argument("--sqlite", type=Path, required=True)
    prepare.add_argument("--output", type=Path, default=Path("eval_outputs/ragas_v4_samples.jsonl"))
    prepare.add_argument("--limit", type=int, help="최대 문항 수; 미지정 시 필터 결과 전체")
    prepare.add_argument("--qids", action="append", help="쉼표로 구분한 qid; 여러 번 지정 가능")
    prepare.add_argument("--types", action="append", help="질문유형; 여러 번 지정 가능")
    prepare.add_argument("--run", action="store_true", help="LLM을 실제 호출")
    prepare.add_argument("--resume", action="store_true")
    prepare.set_defaults(func=collect)
    scoring = commands.add_parser("score", help="수집된 답변에 RAGAS 점수 계산")
    scoring.add_argument("--input", type=Path, default=Path("eval_outputs/ragas_v4_samples.jsonl"))
    scoring.add_argument("--output", type=Path, default=Path("eval_outputs/ragas_v4_scores.jsonl"))
    scoring.add_argument("--summary", type=Path, default=Path("eval_outputs/ragas_v4_summary.json"))
    scoring.add_argument("--csv", type=Path, default=Path("eval_outputs/ragas_v4_results.csv"))
    scoring.add_argument("--below-csv", type=Path, default=Path("eval_outputs/ragas_v4_below_0_7.csv"))
    scoring.add_argument("--limit", type=int, help="최대 문항 수; 미지정 시 입력 전체")
    scoring.add_argument("--qids", action="append", help="쉼표로 구분한 qid; 여러 번 지정 가능")
    scoring.add_argument("--types", action="append", help="질문유형; 여러 번 지정 가능")
    scoring.add_argument("--run", action="store_true", help="판정 LLM을 실제 호출")
    scoring.add_argument("--report-only", action="store_true", help="저장된 점수로 CSV·요약만 재생성; API 호출 없음")
    scoring.add_argument("--resume", action="store_true")
    scoring.set_defaults(func=score)
    tracing = commands.add_parser("trace", help="저장된 한 답변의 RAGAS claim·판정 추적")
    tracing.add_argument("--input", type=Path, default=Path("eval_outputs/ragas_v4_samples.jsonl"))
    tracing.add_argument("--qid", required=True)
    tracing.add_argument("--output", type=Path, default=Path("eval_outputs/ragas_faithfulness_trace.json"))
    tracing.add_argument("--run", action="store_true", help="판정 LLM을 실제 호출")
    tracing.set_defaults(func=trace)
    references = commands.add_parser("references", help="첫 정답 문서의 설명 원문으로 78개 reference CSV 작성")
    references.add_argument("--golden", type=Path, required=True)
    references.add_argument("--sqlite", type=Path, required=True)
    references.add_argument("--output", type=Path, default=Path("eval_outputs/ragas_v4_references.csv"))
    references.set_defaults(func=build_references)
    reference_score = commands.add_parser("score-reference", help="저장된 답변에 FactualCorrectness recall 채점")
    reference_score.add_argument("--input", type=Path, default=Path("eval_outputs/ragas_v4_low049_samples.jsonl"))
    reference_score.add_argument("--references", type=Path, default=Path("eval_outputs/ragas_v4_references.csv"))
    reference_score.add_argument("--output", type=Path, default=Path("eval_outputs/ragas_v4_low049_factual_recall_scores.jsonl"))
    reference_score.add_argument("--csv", type=Path, default=Path("eval_outputs/ragas_v4_low049_factual_recall_results.csv"))
    reference_score.add_argument("--summary", type=Path, default=Path("eval_outputs/ragas_v4_low049_summary.json"))
    reference_score.add_argument("--run", action="store_true", help="판정 LLM을 실제 호출")
    reference_score.add_argument("--resume", action="store_true")
    reference_score.set_defaults(func=score_references)
    args = parser.parse_args()
    if getattr(args, "limit", None) is not None and args.limit < 1:
        parser.error("--limit는 1 이상이어야 합니다.")
    args.func(args)


if __name__ == "__main__":
    main()
