"""운영 PostgreSQL 게임 스키마와 본인 조회 정책을 재현 가능한 SQL로 출력한다."""
from sqlalchemy import MetaData
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from game.models import Base


def render_schema() -> str:
    metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(metadata, schema="public")
    dialect = postgresql.dialect()
    statements = ["-- Game tables only. Apply once as a transactional migration."]
    for table in metadata.sorted_tables:
        statements.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
        for index in sorted(table.indexes, key=lambda i: i.name):
            statements.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")
    for table in metadata.sorted_tables:
        name = f'public."{table.name}"'
        if "user_id" in table.c:
            predicate = "user_id = (select auth.uid())::text"
        else:
            predicate = ("character_id in (select character_id from public.game_characters "
                         "where user_id = (select auth.uid())::text)")
        statements.extend([
            f"alter table {name} enable row level security;",
            f"revoke all on table {name} from public, anon, authenticated;",
            f"grant select on table {name} to authenticated;",
            f"create policy game_select_own on {name} for select to authenticated using ({predicate});",
        ])
    return "\n\n".join(statements) + "\n"


if __name__ == "__main__":
    print(render_schema(), end="")
