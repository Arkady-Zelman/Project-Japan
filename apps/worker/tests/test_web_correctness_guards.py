"""Static guards for high-impact public analytics API contracts."""

from pathlib import Path


REPO_ROOT = Path(__file__).parents[3]
BOS_ROUTE = (
    REPO_ROOT / "apps/web/src/app/api/bos-strategy/route.ts"
).read_text(encoding="utf-8")
FORECAST_ROUTE = (
    REPO_ROOT / "apps/web/src/app/api/forecast-paths/route.ts"
).read_text(encoding="utf-8")


def test_demo_asset_uses_fractional_soc_bounds() -> None:
    assert "soc_min_pct: 0.1" in BOS_ROUTE
    assert "soc_max_pct: 0.9" in BOS_ROUTE
    assert "soc_min_pct: 10," not in BOS_ROUTE
    assert "soc_max_pct: 90," not in BOS_ROUTE


def test_bos_reports_realised_source_after_forecast_fallback() -> None:
    assert "let resolvedSource = source;" in BOS_ROUTE
    assert 'resolvedSource = "realised";' in BOS_ROUTE
    assert "source: resolvedSource" in BOS_ROUTE


def test_forecast_pagination_has_a_unique_order() -> None:
    for route in (BOS_ROUTE, FORECAST_ROUTE):
        assert '.select("path_id, slot_start, price_jpy_kwh")' in route
        assert '.order("slot_start", { ascending: true })' in route
        assert '.order("path_id", { ascending: true })' in route


def test_bos_rejects_partial_forecast_ensembles() -> None:
    assert "const expectedRows = Number(run.n_paths) * usedHorizon;" in BOS_ROUTE
    assert "if (all.length !== expectedRows) return [];" in BOS_ROUTE
