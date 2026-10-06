"""Seed stages and concepts from data/stages.json without starting the API."""

from __future__ import annotations

import argparse
from pathlib import Path

from chatbot.learning_management import (
    LearningManagementBase,
    create_database_engine,
    list_seeded_stage_ids,
    seed_learning_catalog,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-url", default="sqlite:///chat.db")
    parser.add_argument("--stages-json", type=Path, default=Path("data/stages.json"))
    args = parser.parse_args()

    engine = create_database_engine(args.db_url)
    try:
        LearningManagementBase.metadata.create_all(engine)
        seed_learning_catalog(engine, args.stages_json)
        stage_ids = list_seeded_stage_ids(engine)
    finally:
        engine.dispose()
    print(f"Seeded {len(stage_ids)} stages: {', '.join(stage_ids)}")


if __name__ == "__main__":
    main()
