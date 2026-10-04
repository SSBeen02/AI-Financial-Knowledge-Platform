from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from chatbot.concepts import STATUS_IN_PROGRESS, STATUS_PASSED, load_stage_catalog
from chatbot.integrations import DevConceptStatusRow, DevConceptStatusService
from tests.conftest import STAGES_PATH
from tests.test_concepts import HEADERS, USER


def test_progress_counts_passed_in_progress_and_remaining(
    client: TestClient,
    dev_status: DevConceptStatusService,
) -> None:
    stage1 = load_stage_catalog(STAGES_PATH).stages["stage1"]
    now = datetime.now(timezone.utc)
    with Session(dev_status._engine) as session:
        for concept in stage1.concepts[:3]:
            session.add(
                DevConceptStatusRow(
                    user_id=USER,
                    concept_id=concept.concept_id,
                    stage_id="stage1",
                    status=STATUS_PASSED,
                    updated_at=now,
                )
            )
        session.add(
            DevConceptStatusRow(
                user_id=USER,
                concept_id=stage1.concepts[3].concept_id,
                stage_id="stage1",
                status=STATUS_IN_PROGRESS,
                updated_at=now,
            )
        )
        session.commit()

    response = client.get("/learning/progress", headers=HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["current"] == {
        "stage_id": "stage1",
        "name_ko": stage1.name_ko,
        "total_count": 30,
        "passed_count": 3,
        "in_progress_count": 1,
        "not_started_count": 26,
        "remaining_count": 27,
        "percent": 10,
    }
    assert len(body["stages"]) == 5
    assert body["stages"][0]["unlocked"] is True
    assert body["stages"][0]["completed"] is False
    assert body["stages"][1]["unlocked"] is False
    assert body["stages"][4]["total_count"] == 70
    assert client.get("/learning/current", headers=HEADERS).json()["progress"] == body["current"]

    other = client.get("/learning/progress", headers={"X-User-Id": "other-user"}).json()
    assert other["current"]["passed_count"] == 0
    assert other["current"]["in_progress_count"] == 0


def test_completed_stage1_makes_stage2_current_progress(
    client: TestClient,
    dev_status: DevConceptStatusService,
) -> None:
    dev_status.pass_stage(USER, "stage1")

    body = client.get("/learning/progress", headers=HEADERS).json()

    assert body["current"]["stage_id"] == "stage2"
    assert body["stages"][0]["completed"] is True
    assert body["stages"][0]["percent"] == 100
    assert body["stages"][0]["remaining_count"] == 0
    assert body["stages"][1]["unlocked"] is True
    assert body["stages"][2]["unlocked"] is False


def test_progress_requires_user_header(client: TestClient) -> None:
    assert client.get("/learning/progress").status_code == 401
