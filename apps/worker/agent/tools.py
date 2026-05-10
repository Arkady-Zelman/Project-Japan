"""Seven tools per BUILD_SPEC §9.2.

Each tool takes `(args: dict, ctx: ToolContext)` and returns a dict-like
result. The agent loop wraps each call in `compute_run("agent_tool_call")`.

Discipline:
- `query_data` opens a fresh `agent_readonly` Postgres connection per call.
- All other tools use the service-role connection only for writes
  (`create_chart` → `agent_artifacts`); reads go through `agent_readonly`.
- No tool may write to user-owned tables (`assets`, `valuations`, etc.).
- Outputs are JSON-serialisable.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
import numpy as np
import pandas as pd
import psycopg
from scipy import stats   # type: ignore[import-untyped]

from common.audit import compute_run
from common.db import connect

from .models import ToolName
from .safety import is_select_only

logger = logging.getLogger("agent.tools")

QUERY_TIMEOUT_SECONDS = 30
MAX_ROWS_RETURNED = 1_000


@dataclass
class ToolContext:
    """Per-request context handed to every tool. Never serialised to LLM."""

    user_id: UUID
    session_id: UUID


# ---------------------------------------------------------------------------
# 1. query_data — read-only SQL via agent_readonly role
# ---------------------------------------------------------------------------


def query_data(args: dict, ctx: ToolContext) -> dict:
    sql = str(args.get("sql", "")).strip()
    if not sql:
        return {"success": False, "error": "missing 'sql' argument"}
    ok, reason = is_select_only(sql)
    if not ok:
        return {"success": False, "error": f"SQL rejected: {reason}"}

    with compute_run("agent_tool_call") as run:
        run.set_input({"tool": "query_data", "sql": sql[:2000], "user_id": str(ctx.user_id)})
        try:
            with connect(env_var="SUPABASE_AGENT_READONLY_DB_URL") as conn, conn.cursor() as cur:
                cur.execute(f"set local statement_timeout = '{QUERY_TIMEOUT_SECONDS}s'")
                cur.execute(sql)
                desc = cur.description or ()
                cols = [d[0] for d in desc]
                rows = cur.fetchmany(MAX_ROWS_RETURNED + 1)
                truncated = len(rows) > MAX_ROWS_RETURNED
                rows = rows[:MAX_ROWS_RETURNED]
                # Normalise non-JSON types (Decimal, datetime, UUID).
                serialised: list[list[Any]] = []
                for r in rows:
                    serialised.append([_to_json(v) for v in r])
            output = {
                "success": True,
                "columns": cols, "rows": serialised,
                "n_rows": len(serialised), "truncated": truncated,
            }
            run.set_output({"n_rows": len(serialised), "truncated": truncated})
            return output
        except Exception as e:
            run.set_output({"error": repr(e)})
            return {"success": False, "error": f"query failed: {str(e)[:300]}"}


def _to_json(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (int, float, str, bool)):
        return v
    if isinstance(v, (list, dict)):
        return v
    return str(v)


# ---------------------------------------------------------------------------
# 2. describe_schema — pull from data_dictionary
# ---------------------------------------------------------------------------


def describe_schema(args: dict, ctx: ToolContext) -> dict:
    table_name = args.get("table_name")
    with compute_run("agent_tool_call") as run:
        run.set_input({"tool": "describe_schema", "table_name": table_name})
        with connect(env_var="SUPABASE_AGENT_READONLY_DB_URL") as conn, conn.cursor() as cur:
            if table_name:
                cur.execute(
                    """
                    select table_name, column_name, description, unit, notes
                    from data_dictionary where table_name = %s
                    order by column_name
                    """,
                    (str(table_name),),
                )
            else:
                cur.execute(
                    """
                    select table_name, column_name, description, unit, notes
                    from data_dictionary
                    order by table_name, column_name
                    """
                )
            rows = cur.fetchall()
        output = {
            "success": True,
            "rows": [
                {
                    "table": r[0], "column": r[1],
                    "description": r[2], "unit": r[3], "notes": r[4],
                }
                for r in rows
            ],
        }
        run.set_output({"n_rows": len(output["rows"])})
        return output


# ---------------------------------------------------------------------------
# 3. create_chart — Plotly figure spec → agent_artifacts row
# ---------------------------------------------------------------------------


def create_chart(args: dict, ctx: ToolContext) -> dict:
    title = str(args.get("title", "Untitled chart"))[:200]
    spec = args.get("spec")
    if not isinstance(spec, dict) or "data" not in spec or "layout" not in spec:
        return {
            "success": False,
            "error": "spec must be a dict with 'data' and 'layout' keys "
                     "(Plotly figure spec)",
        }

    with compute_run("agent_tool_call") as run:
        run.set_input({"tool": "create_chart", "title": title})
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                insert into agent_artifacts
                  (session_id, user_id, type, title, spec_jsonb)
                values (%s, %s, 'chart', %s, %s::jsonb)
                returning id::text
                """,
                (str(ctx.session_id), str(ctx.user_id), title, json.dumps(spec)),
            )
            row = cur.fetchone()
            artifact_id = row[0] if row else None
            conn.commit()
        run.set_output({"artifact_id": artifact_id})
        return {
            "success": True, "artifact_id": artifact_id, "title": title,
            "type": "chart",
        }


# ---------------------------------------------------------------------------
# 4. run_correlation — pearson / spearman + Fisher CI
# ---------------------------------------------------------------------------


def run_correlation(args: dict, ctx: ToolContext) -> dict:
    sql = str(args.get("sql", "")).strip()
    method = str(args.get("method", "pearson")).lower()
    if method not in ("pearson", "spearman"):
        return {"success": False, "error": "method must be 'pearson' or 'spearman'"}
    ok, reason = is_select_only(sql)
    if not ok:
        return {"success": False, "error": f"SQL rejected: {reason}"}

    with compute_run("agent_tool_call") as run:
        run.set_input({"tool": "run_correlation", "method": method, "sql": sql[:1000]})
        try:
            with connect(env_var="SUPABASE_AGENT_READONLY_DB_URL") as conn, conn.cursor() as cur:
                cur.execute(f"set local statement_timeout = '{QUERY_TIMEOUT_SECONDS}s'")
                cur.execute(sql)
                rows = cur.fetchall()
                cols = [d[0] for d in (cur.description or ())]
            if len(rows) < 5 or len(cols) != 2:
                return {
                    "success": False,
                    "error": (
                        f"need at least 5 rows and exactly 2 columns; "
                        f"got {len(rows)} rows × {len(cols)} cols"
                    ),
                }
            xs = np.array([float(r[0]) for r in rows if r[0] is not None and r[1] is not None])
            ys = np.array([float(r[1]) for r in rows if r[0] is not None and r[1] is not None])
            if method == "pearson":
                res = stats.pearsonr(xs, ys)
            else:
                res = stats.spearmanr(xs, ys)
            r = float(res.statistic)
            p = float(res.pvalue)
            n = int(len(xs))
            # Fisher z transform for 95% CI.
            if abs(r) < 0.999 and n > 3:
                fz = 0.5 * np.log((1 + r) / (1 - r))
                se = 1 / np.sqrt(n - 3)
                lo_z = fz - 1.96 * se
                hi_z = fz + 1.96 * se
                ci_lo = (np.exp(2 * lo_z) - 1) / (np.exp(2 * lo_z) + 1)
                ci_hi = (np.exp(2 * hi_z) - 1) / (np.exp(2 * hi_z) + 1)
            else:
                ci_lo = ci_hi = float("nan")
            output = {
                "success": True,
                "method": method,
                "x_column": cols[0], "y_column": cols[1],
                "n": n, "coefficient": round(r, 4),
                "p_value": round(p, 6),
                "ci_95_lower": round(float(ci_lo), 4) if not np.isnan(ci_lo) else None,
                "ci_95_upper": round(float(ci_hi), 4) if not np.isnan(ci_hi) else None,
            }
            run.set_output(output)
            return output
        except Exception as e:
            run.set_output({"error": repr(e)})
            return {"success": False, "error": f"correlation failed: {str(e)[:300]}"}


# ---------------------------------------------------------------------------
# 5. fit_quick_model — sklearn linear / ridge / random_forest
# ---------------------------------------------------------------------------


def fit_quick_model(args: dict, ctx: ToolContext) -> dict:
    sql = str(args.get("sql", "")).strip()
    target = str(args.get("target", ""))
    features = args.get("features", [])
    model_type = str(args.get("model_type", "linear")).lower()

    if not target or not isinstance(features, list) or not features:
        return {"success": False, "error": "target and features (list) are required"}
    if model_type not in ("linear", "ridge", "random_forest"):
        return {"success": False, "error": "model_type must be linear/ridge/random_forest"}
    ok, reason = is_select_only(sql)
    if not ok:
        return {"success": False, "error": f"SQL rejected: {reason}"}

    with compute_run("agent_tool_call") as run:
        run.set_input({
            "tool": "fit_quick_model", "target": target,
            "features": features, "model_type": model_type,
        })
        try:
            with connect(env_var="SUPABASE_AGENT_READONLY_DB_URL") as conn, conn.cursor() as cur:
                cur.execute(f"set local statement_timeout = '{QUERY_TIMEOUT_SECONDS}s'")
                cur.execute(sql)
                rows = cur.fetchall()
                cols = [d[0] for d in (cur.description or ())]
            df = pd.DataFrame(rows, columns=cols).apply(pd.to_numeric, errors="coerce").dropna()
            if target not in df.columns:
                return {"success": False, "error": f"target '{target}' not in query columns"}
            missing = [f for f in features if f not in df.columns]
            if missing:
                return {"success": False, "error": f"features missing in query: {missing}"}
            if len(df) < 50:
                return {"success": False, "error": f"need at least 50 non-null rows; got {len(df)}"}

            from sklearn.ensemble import RandomForestRegressor   # local for cold-start
            from sklearn.linear_model import LinearRegression, Ridge
            from sklearn.metrics import r2_score
            from sklearn.model_selection import train_test_split

            X = df[features].to_numpy()
            y = df[target].to_numpy()
            X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42)
            if model_type == "linear":
                model = LinearRegression()
            elif model_type == "ridge":
                model = Ridge(alpha=1.0)
            else:
                model = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
            model.fit(X_tr, y_tr)
            y_pred = model.predict(X_te)
            r2 = float(r2_score(y_te, y_pred))
            output: dict = {
                "success": True,
                "model_type": model_type,
                "n_train": int(len(X_tr)), "n_test": int(len(X_te)),
                "r2_holdout": round(r2, 4),
            }
            if hasattr(model, "coef_"):
                output["coef"] = {f: round(float(c), 6) for f, c in zip(features, model.coef_)}
                output["intercept"] = round(float(getattr(model, "intercept_", 0.0)), 6)
            elif hasattr(model, "feature_importances_"):
                output["feature_importances"] = {
                    f: round(float(c), 6)
                    for f, c in zip(features, model.feature_importances_)
                }
            run.set_output(output)
            return output
        except Exception as e:
            run.set_output({"error": repr(e)})
            return {"success": False, "error": f"fit failed: {str(e)[:300]}"}


# ---------------------------------------------------------------------------
# 6. value_what_if — call Modal LSM with override-mode payload
# ---------------------------------------------------------------------------


def value_what_if(args: dict, ctx: ToolContext) -> dict:
    """What-if BESS valuation. Clones the asset, applies overrides, queues a
    valuation, kicks Modal LSM, polls until done. Does NOT mutate the
    original asset row (per BUILD_SPEC §9.4 'no model promotion').
    """
    asset_id = args.get("asset_id")
    overrides = args.get("overrides", {})
    if not asset_id:
        return {"success": False, "error": "asset_id required"}
    if not isinstance(overrides, dict):
        return {"success": False, "error": "overrides must be a dict"}
    modal_lsm = os.environ.get("MODAL_LSM_ENDPOINT")
    if not modal_lsm:
        return {"success": False, "error": "MODAL_LSM_ENDPOINT not configured"}

    with compute_run("agent_tool_call") as run:
        run.set_input({
            "tool": "value_what_if", "asset_id": str(asset_id),
            "overrides": overrides,
        })
        try:
            # Clone the asset, apply overrides; queue a valuation; kick Modal.
            allowed_fields = {
                "power_mw", "energy_mwh", "round_trip_eff", "soc_min_pct",
                "soc_max_pct", "max_cycles_per_year", "degradation_jpy_mwh",
            }
            override_fields = {
                k: v for k, v in overrides.items() if k in allowed_fields
            }
            valuation_id: str | None = None
            with connect() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    select portfolio_id, area_id, name, asset_type, power_mw,
                           energy_mwh, round_trip_eff, soc_min_pct, soc_max_pct,
                           max_cycles_per_year, degradation_jpy_mwh, user_id
                    from assets where id = %s and user_id = %s
                    """,
                    (str(asset_id), str(ctx.user_id)),
                )
                row = cur.fetchone()
                if not row:
                    return {
                        "success": False,
                        "error": "asset not found or not owned by this user",
                    }
                (portfolio_id, area_id, name, asset_type, power_mw, energy_mwh,
                 eff, soc_min, soc_max, cycles, deg, user_id) = row
                # Apply overrides.
                spec = {
                    "power_mw": float(power_mw),
                    "energy_mwh": float(energy_mwh),
                    "round_trip_eff": float(eff),
                    "soc_min_pct": float(soc_min),
                    "soc_max_pct": float(soc_max),
                    "max_cycles_per_year": float(cycles or 365),
                    "degradation_jpy_mwh": float(deg or 0),
                }
                spec.update({k: float(v) for k, v in override_fields.items()})

                # Insert a clone asset row scoped to a sentinel name so we can
                # delete it after valuation. Persisted only briefly.
                cur.execute(
                    """
                    insert into assets
                      (portfolio_id, user_id, name, asset_type, area_id,
                       power_mw, energy_mwh, round_trip_eff, soc_min_pct,
                       soc_max_pct, max_cycles_per_year, degradation_jpy_mwh,
                       metadata)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            '{"what_if": true}'::jsonb)
                    returning id::text
                    """,
                    (
                        portfolio_id, user_id, f"[what-if] {name}",
                        asset_type, area_id,
                        spec["power_mw"], spec["energy_mwh"],
                        spec["round_trip_eff"], spec["soc_min_pct"],
                        spec["soc_max_pct"], spec["max_cycles_per_year"],
                        spec["degradation_jpy_mwh"],
                    ),
                )
                clone_row = cur.fetchone()
                clone_asset_id = clone_row[0] if clone_row else None
                if not clone_asset_id:
                    return {"success": False, "error": "failed to clone asset"}

                # Find latest forecast_run for that area.
                cur.execute(
                    """
                    select id::text, forecast_origin, horizon_slots
                    from forecast_runs where area_id = %s
                    order by forecast_origin desc limit 1
                    """,
                    (area_id,),
                )
                fr = cur.fetchone()
                if not fr:
                    return {
                        "success": False,
                        "error": "no forecast_runs for this area; run vlstm.forecast first",
                    }
                forecast_run_id, fo, hs = fr
                from datetime import timedelta
                horizon_end = fo + timedelta(minutes=30 * int(hs))
                cur.execute(
                    """
                    insert into valuations
                      (asset_id, user_id, forecast_run_id, method, status,
                       horizon_start, horizon_end, basis_functions, n_paths,
                       n_volume_grid)
                    values (%s, %s, %s, 'lsm', 'queued', %s, %s,
                            '{"basis": "power"}'::jsonb, 1000, 51)
                    returning id::text
                    """,
                    (clone_asset_id, str(user_id), forecast_run_id, fo, horizon_end),
                )
                v_row = cur.fetchone()
                valuation_id = v_row[0] if v_row else None
                conn.commit()

            if not valuation_id:
                return {"success": False, "error": "failed to queue valuation"}

            # Kick Modal LSM endpoint and poll.
            with httpx.Client(timeout=300.0) as client:
                client.post(modal_lsm, json={"valuation_id": valuation_id})
            # Poll up to 90s.
            deadline = time.time() + 90
            result_row: tuple | None = None
            while time.time() < deadline:
                with connect() as conn, conn.cursor() as cur:
                    cur.execute(
                        """select status, total_value_jpy, intrinsic_value_jpy,
                                  extrinsic_value_jpy, ci_lower_jpy, ci_upper_jpy
                           from valuations where id = %s""",
                        (valuation_id,),
                    )
                    row = cur.fetchone()
                if row and row[0] in ("done", "failed"):
                    result_row = row
                    break
                time.sleep(3)

            # Clean up the clone asset (RLS-bypass via service-role).
            try:
                with connect() as conn, conn.cursor() as cur:
                    cur.execute("delete from valuations where id = %s", (valuation_id,))
                    cur.execute("delete from assets where id = %s", (clone_asset_id,))
                    conn.commit()
            except Exception as ce:
                logger.warning("what_if cleanup failed: %s", ce)

            if result_row is None:
                return {"success": False, "error": "what-if valuation did not finish in 90s"}
            status, total, intrinsic, extrinsic, ci_lo, ci_hi = result_row
            if status != "done":
                return {"success": False, "error": f"valuation status={status}"}
            output = {
                "success": True,
                "asset_id": str(asset_id),
                "overrides": override_fields,
                "total_jpy": float(total) if total is not None else None,
                "intrinsic_jpy": float(intrinsic) if intrinsic is not None else None,
                "extrinsic_jpy": float(extrinsic) if extrinsic is not None else None,
                "ci_95_lower_jpy": float(ci_lo) if ci_lo is not None else None,
                "ci_95_upper_jpy": float(ci_hi) if ci_hi is not None else None,
            }
            run.set_output(output)
            return output
        except Exception as e:
            run.set_output({"error": repr(e)})
            return {"success": False, "error": f"what_if failed: {str(e)[:300]}"}


# ---------------------------------------------------------------------------
# 7. get_user_assets — RLS-scoped via explicit user_id check
# ---------------------------------------------------------------------------


def get_user_assets(args: dict, ctx: ToolContext) -> dict:
    with compute_run("agent_tool_call") as run:
        run.set_input({"tool": "get_user_assets", "user_id": str(ctx.user_id)})
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                select a.id::text, a.name, a.asset_type, ar.code as area,
                       a.power_mw, a.energy_mwh, a.round_trip_eff,
                       a.max_cycles_per_year, a.degradation_jpy_mwh,
                       a.soc_min_pct, a.soc_max_pct, a.created_at
                from assets a join areas ar on ar.id = a.area_id
                where a.user_id = %s
                  and not coalesce(a.metadata->>'what_if', 'false')::boolean
                order by a.created_at desc
                """,
                (str(ctx.user_id),),
            )
            rows = cur.fetchall()
        assets = [
            {
                "id": r[0], "name": r[1], "type": r[2], "area": r[3],
                "power_mw": float(r[4]), "energy_mwh": float(r[5]),
                "round_trip_eff": float(r[6]),
                "max_cycles_per_year": float(r[7]) if r[7] is not None else None,
                "degradation_jpy_mwh": float(r[8]) if r[8] is not None else 0.0,
                "soc_min_pct": float(r[9]), "soc_max_pct": float(r[10]),
                "created_at": r[11].isoformat() if r[11] else None,
            }
            for r in rows
        ]
        run.set_output({"n_assets": len(assets)})
        return {"success": True, "assets": assets}


# ---------------------------------------------------------------------------
# Registry + OpenAI tool schemas
# ---------------------------------------------------------------------------


TOOLS: dict[ToolName, Any] = {
    "query_data": query_data,
    "describe_schema": describe_schema,
    "create_chart": create_chart,
    "run_correlation": run_correlation,
    "fit_quick_model": fit_quick_model,
    "value_what_if": value_what_if,
    "get_user_assets": get_user_assets,
}


def openai_tool_schemas() -> list[dict]:
    """OpenAI function-calling tool definitions per §9.2."""
    return [
        {
            "type": "function",
            "function": {
                "name": "query_data",
                "description": (
                    "Run a read-only SQL query against the JEPX-Storage Postgres database. "
                    "Only SELECT and WITH-SELECT statements are accepted; mutations are "
                    "rejected. 30s timeout. Up to 1000 rows returned."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql": {
                            "type": "string",
                            "description": "A single SELECT or WITH-SELECT statement in PostgreSQL syntax.",
                        }
                    },
                    "required": ["sql"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "describe_schema",
                "description": (
                    "Return column descriptions and units from `data_dictionary` for one "
                    "or all tables. Use this to discover schema before query_data."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "table_name": {
                            "type": "string",
                            "description": "Optional — restrict output to one table.",
                        }
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "create_chart",
                "description": (
                    "Create a Plotly figure from a JSON spec and persist it to "
                    "`agent_artifacts`. The frontend renders it in the scratchpad. "
                    "Spec must include `data` (list of traces) and `layout` (object)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "spec": {
                            "type": "object",
                            "description": "Plotly figure spec: { data: [...], layout: {...} }",
                        },
                    },
                    "required": ["title", "spec"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_correlation",
                "description": (
                    "Compute Pearson or Spearman correlation between two columns of a "
                    "SQL query result. Returns coefficient, p-value, 95% CI."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql": {
                            "type": "string",
                            "description": "SELECT returning exactly two numeric columns (x, y).",
                        },
                        "method": {"type": "string", "enum": ["pearson", "spearman"]},
                    },
                    "required": ["sql", "method"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fit_quick_model",
                "description": (
                    "Fit a quick linear / ridge / random-forest model to predict "
                    "`target` from `features`. Returns coefficients + R² on a 20% "
                    "hold-out. Does NOT persist anywhere."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string"},
                        "target": {"type": "string"},
                        "features": {"type": "array", "items": {"type": "string"}},
                        "model_type": {
                            "type": "string",
                            "enum": ["linear", "ridge", "random_forest"],
                        },
                    },
                    "required": ["sql", "target", "features", "model_type"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "value_what_if",
                "description": (
                    "Run an LSM valuation on a hypothetical version of an asset. "
                    "Clones the asset, applies `overrides`, calls the LSM endpoint, "
                    "returns total/intrinsic/extrinsic. The original asset is "
                    "unchanged."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "asset_id": {"type": "string"},
                        "overrides": {
                            "type": "object",
                            "description": (
                                "Field overrides: any of power_mw, energy_mwh, "
                                "round_trip_eff, soc_min_pct, soc_max_pct, "
                                "max_cycles_per_year, degradation_jpy_mwh."
                            ),
                        },
                    },
                    "required": ["asset_id", "overrides"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_user_assets",
                "description": (
                    "List the calling user's storage assets. Filters out what-if "
                    "clones automatically."
                ),
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]
