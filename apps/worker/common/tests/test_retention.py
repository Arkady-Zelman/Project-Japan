from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from common.retention import delete_old_stack_rows, delete_older_than


class FakeConnection:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class FakeCursor:
    def __init__(self, rowcounts: list[int]) -> None:
        self._rowcounts = iter(rowcounts)
        self.rowcount = 0
        self.executed: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.executed.append((sql, params))
        self.rowcount = next(self._rowcounts, 0)


def test_delete_old_stack_rows_deletes_child_before_parent_without_truncate() -> None:
    cutoff = datetime(2026, 2, 22, tzinfo=UTC)
    cur = FakeCursor([12, 4])
    conn = FakeConnection()

    deleted = delete_old_stack_rows(cur, conn, cutoff=cutoff)

    assert deleted == {"stack_clearing_prices": 12, "stack_curves": 4}
    assert conn.commits == 2
    sqls = [sql.lower() for sql, _ in cur.executed]
    assert "delete from stack_clearing_prices" in sqls[0]
    assert "delete from stack_curves" in sqls[1]
    assert "truncate" not in "\n".join(sqls)
    assert [params for _, params in cur.executed] == [(cutoff,), (cutoff,)]


def test_delete_older_than_rejects_non_allowlisted_tables() -> None:
    cur = FakeCursor([1])
    conn = FakeConnection()

    try:
        delete_older_than(
            cur,
            conn,
            table="assets",
            column="created_at",
            cutoff=datetime(2026, 2, 22, tzinfo=UTC),
        )
    except ValueError as exc:
        assert "unsupported retention target" in str(exc)
    else:
        raise AssertionError("delete_older_than accepted a non-retention table")

    assert cur.executed == []
    assert conn.commits == 0


def test_modal_retention_does_not_truncate_stack_tables() -> None:
    modal_app = Path(__file__).resolve().parents[2] / "modal_app.py"
    text = modal_app.read_text(encoding="utf-8").lower()

    assert "truncate table stack_curves" not in text
    assert "truncate table stack_clearing_prices" not in text
