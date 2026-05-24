from pathlib import Path

from common.retention import RETENTION_RULES, VACUUM_TABLES, RetentionRule


def _rule_by_table(table: str) -> RetentionRule:
    return next(rule for rule in RETENTION_RULES if rule.table == table)


def test_stack_retention_keeps_recent_window() -> None:
    assert _rule_by_table("stack_clearing_prices").days == 90
    assert _rule_by_table("stack_curves").days == 90


def test_stack_child_pruned_before_parent() -> None:
    tables = [rule.table for rule in RETENTION_RULES]

    assert tables.index("stack_clearing_prices") < tables.index("stack_curves")


def test_prune_old_data_does_not_truncate_stack_tables() -> None:
    modal_app_source = (Path(__file__).resolve().parents[1] / "modal_app.py").read_text()

    assert "truncate table stack_curves" not in modal_app_source.lower()
    assert "truncate table stack_clearing_prices" not in modal_app_source.lower()
    assert "stack_curves" in VACUUM_TABLES
    assert "stack_clearing_prices" in VACUUM_TABLES
