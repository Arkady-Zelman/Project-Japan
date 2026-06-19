"""Retention policy shared by Modal maintenance jobs.

The nightly sweep runs immediately after the daily stack build, so stack-model
tables must be pruned by age instead of truncated wholesale.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetentionRule:
    table: str
    days: int
    column: str


# Child tables before parents where foreign keys can exist.
RETENTION_RULES: tuple[RetentionRule, ...] = (
    RetentionRule("regime_states", 30, "slot_start"),
    RetentionRule("stack_clearing_prices", 90, "slot_start"),
    RetentionRule("stack_curves", 90, "slot_start"),
    RetentionRule("generation_mix_actuals", 90, "slot_start"),
    RetentionRule("demand_actuals", 90, "slot_start"),
    RetentionRule("jepx_spot_prices", 90, "slot_start"),
    RetentionRule("weather_obs", 14, "ts"),
)

VACUUM_TABLES: tuple[str, ...] = tuple(rule.table for rule in RETENTION_RULES)
