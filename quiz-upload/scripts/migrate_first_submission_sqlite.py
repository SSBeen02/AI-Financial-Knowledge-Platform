"""Offline SQLite migration. Default is read-only; --apply requires a backup path."""
import argparse
from contextlib import closing
import sqlite3
from pathlib import Path

def migrate(database: Path, *, apply=False, backup: Path | None = None):
    database = database.resolve(strict=True)
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro', uri=True)) as conn:
        duplicates = conn.execute('select quiz_set_id,count(*) from quiz_submissions group by quiz_set_id having count(*)>1').fetchall()
    if duplicates:
        raise RuntimeError(f'{len(duplicates)} quiz sets have multiple submissions. No rows changed; review references manually.')
    if not apply:
        return 'Read-only check passed; rerun offline with --apply --backup PATH to add the constraint.'
    if backup is None:
        raise ValueError('--backup is required')
    backup=backup.resolve()
    if backup == database or backup.exists():
        raise ValueError('Backup must be a new, different path')
    backup.parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as source, closing(sqlite3.connect(backup)) as target:
        source.backup(target)
    with closing(sqlite3.connect(database)) as conn:
        conn.execute('begin immediate')
        conn.execute('create unique index if not exists uq_quiz_submissions_quiz_set on quiz_submissions(quiz_set_id)')
        conn.commit()
    return 'Unique index added; original database backup retained.'

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database',type=Path)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--backup',type=Path)
    args=parser.parse_args()
    print(migrate(args.database,apply=args.apply,backup=args.backup))
