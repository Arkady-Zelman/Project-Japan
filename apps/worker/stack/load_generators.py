"""Load `generators_seed.yaml` into the `generators` table.

Idempotent: re-runs UPSERT on (name, area_id, operator). Adjust efficiency
or capacity in the YAML and re-run to push updates.

Usage from `apps/worker/`:

    ./.venv/bin/python -m stack.load_generators

Reads `SUPABASE_DB_URL` from `apps/worker/.env` via `common.db.connect()`.
"""

from __future__ import annotations

import logging
from pathlib import Path

import psycopg
import yaml

from common.audit import compute_run
from common.db import connect

from .models import Generator

logger = logging.getLogger("stack.load_generators")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

_SEED_PATH = Path(__file__).parent / "generators_seed.yaml"


def _load_yaml() -> list[Generator]:
    with _SEED_PATH.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    raw = data.get("generators", [])
    return [Generator.model_validate(item) for item in raw]


def _upsert(cur: psycopg.Cursor, gens: list[Generator]) -> int:
    """UPSERT keyed on (name, area_id, operator). Returns rows affected."""
    cur.execute("select code, id from areas")
    code_to_area_id: dict[str, object] = dict(cur.fetchall())
    cur.execute("select code, id from fuel_types")
    code_to_fuel_id: dict[str, object] = dict(cur.fetchall())
    cur.execute("select code, id from unit_types")
    code_to_unit_type_id: dict[str, object] = dict(cur.fetchall())

    written = 0
    for g in gens:
        area_id = code_to_area_id.get(g.area_code)
        fuel_id = code_to_fuel_id.get(g.fuel_type_code)
        unit_type_id = (
            code_to_unit_type_id.get(g.unit_type_code) if g.unit_type_code else None
        )
        if not area_id or not fuel_id:
            logger.warning(
                "skipping %s: unknown area=%s or fuel=%s", g.name, g.area_code, g.fuel_type_code
            )
            continue

        # Schema has no UNIQUE constraint on (name, area_id, operator) so
        # we do upsert manually: lookup → update / insert.
        cur.execute(
            "select id from generators where name=%s and area_id=%s "
            "and operator is not distinct from %s::text",
            (g.name, area_id, g.operator),
        )
        existing = cur.fetchone()
        # availability_factor lives in metadata JSONB (no column yet — schema
        # has `metadata jsonb default '{}'`). build_curve.py reads it from there.
        import json as _json
        metadata = (
            _json.dumps({"availability_factor": g.availability_factor})
            if g.availability_factor is not None
            else _json.dumps({})
        )

        if existing:
            cur.execute(
                """
                update generators set
                  unit_type_id=%s, fuel_type_id=%s, capacity_mw=%s,
                  efficiency=%s, heat_rate_kj_kwh=%s,
                  variable_om_jpy_mwh=%s, co2_intensity_t_mwh=%s,
                  commissioned=%s, retired=%s, notes=%s, metadata=%s
                where id=%s
                """,
                (
                    unit_type_id, fuel_id, g.capacity_mw,
                    g.efficiency, g.heat_rate_kj_kwh,
                    g.variable_om_jpy_mwh, g.co2_intensity_t_mwh,
                    g.commissioned, g.retired, g.notes, metadata,
                    existing[0],
                ),
            )
        else:
            cur.execute(
                """
                insert into generators
                  (name, operator, area_id, unit_type_id, fuel_type_id,
                   capacity_mw, efficiency, heat_rate_kj_kwh,
                   variable_om_jpy_mwh, co2_intensity_t_mwh,
                   commissioned, retired, notes, metadata)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    g.name, g.operator, area_id, unit_type_id, fuel_id,
                    g.capacity_mw, g.efficiency, g.heat_rate_kj_kwh,
                    g.variable_om_jpy_mwh, g.co2_intensity_t_mwh,
                    g.commissioned, g.retired, g.notes, metadata,
                ),
            )
        written += 1
    return written


def main() -> int:
    gens = _load_yaml()
    logger.info("loaded %d generators from %s", len(gens), _SEED_PATH)

    with compute_run("stack_load_generators") as run:
        run.set_input({"yaml": str(_SEED_PATH), "count": len(gens)})

        with connect() as conn:
            with conn.cursor() as cur:
                written = _upsert(cur, gens)
            conn.commit()

        logger.info("wrote %d generators", written)
        run.set_output({"written": written})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
