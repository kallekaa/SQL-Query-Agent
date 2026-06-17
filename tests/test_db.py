from __future__ import annotations

import pytest

from sql_query_agent.db import SQLValidationError, query_database, validate_read_only_sql
from sql_query_agent.sample_data import init_sample_database


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO customers (name) VALUES ('bad')",
        "UPDATE customers SET name = 'bad'",
        "DELETE FROM customers",
        "DROP TABLE customers",
        "SELECT 1; SELECT 2",
    ],
)
def test_sql_guard_rejects_writes_and_multiple_statements(sql: str) -> None:
    with pytest.raises(SQLValidationError):
        validate_read_only_sql(sql)


def test_query_database_runs_valid_aggregate(tmp_path) -> None:
    db_path = init_sample_database(tmp_path / "sample.db")

    result = query_database(
        db_path,
        """
        SELECT COUNT(*) AS customer_count
        FROM customers
        """,
    )

    assert result["error"] is None
    assert result["columns"] == ["customer_count"]
    assert result["rows"] == [{"customer_count": 4}]
    assert result["truncated"] is False


def test_query_database_rejects_write_sql(tmp_path) -> None:
    db_path = init_sample_database(tmp_path / "sample.db")

    result = query_database(db_path, "DELETE FROM customers")

    assert result["error"]
    assert result["row_count"] == 0
