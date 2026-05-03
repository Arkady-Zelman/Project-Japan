"""Load `seed/data_dictionary.yaml` into the `public.data_dictionary` table.

Idempotent — re-running re-syncs descriptions if the YAML has been edited. The AI
agent's `describe_schema` tool reads from this table at request time per
BUILD_SPEC §9.3 line 1004; agent answer quality depends directly on the YAML
being thorough and current.

Run from `apps/worker/`:
    ./.venv/bin/python -m seed.load_data_dictionary
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

import psycopg
import yaml
from dotenv import load_dotenv
from pydantic import ValidationError

from .models import DataDictionaryEntry

logger = logging.getLogger("seed.load_data_dictionary")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

YAML_PATH = Path(__file__).resolve().parent / "data_dictionary.yaml"


def load_yaml(path: Path) -> list[DataDictionaryEntry]:
    raw: list[dict[str, Any]] = yaml.safe_load(path.read_text())
    if not isinstance(raw, list):
        raise ValueError(f"{path}: expected a YAML list at top level")

    entries: list[DataDictionaryEntry] = []
    errors: list[str] = []
    for i, row in enumerate(raw):
        try:
            entries.append(DataDictionaryEntry.model_validate(row))
        except ValidationError as exc:
            errors.append(f"  entry {i} ({row.get('table')}.{row.get('column')}): {exc.errors()}")
    if errors:
        raise ValueError(
            f"{path}: {len(errors)} invalid entries\n" + "\n".join(errors)
        )
    return entries


def upsert(cur: psycopg.Cursor, entries: list[DataDictionaryEntry]) -> int:
    cur.executemany(
        """
        insert into data_dictionary (table_name, column_name, description, unit, notes)
        values (%s, %s, %s, %s, %s)
        on conflict (table_name, column_name) do update set
          description = excluded.description,
          unit = excluded.unit,
          notes = excluded.notes
        """,
        [(e.table, e.column, e.description, e.unit, e.notes) for e in entries],
    )
    return cur.rowcount


def main() -> int:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(env_path)

    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        logger.error(
            "SUPABASE_DB_URL not set in %s — needed to apply data dictionary. Aborting.",
            env_path,
        )
        return 1

    entries = load_yaml(YAML_PATH)
    seen: set[tuple[str, str]] = set()
    duplicates: list[tuple[str, str]] = []
    for e in entries:
        key = (e.table, e.column)
        if key in seen:
            duplicates.append(key)
        seen.add(key)
    if duplicates:
        logger.error("Duplicate (table, column) entries in YAML: %s", duplicates)
        return 1

    logger.info(
        "Loaded %d entries from %s spanning %d tables.",
        len(entries),
        YAML_PATH,
        len({e.table for e in entries}),
    )

    # prepare_threshold=None disables prepared statements — required when
    # connecting through Supabase's transaction pooler (port 6543), which
    # doesn't support PREPARE.
    with psycopg.connect(db_url, autocommit=False, prepare_threshold=None) as conn:
        with conn.cursor() as cur:
            n = upsert(cur, entries)
        conn.commit()

    logger.info("Data dictionary upsert complete: %d rows touched.", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
