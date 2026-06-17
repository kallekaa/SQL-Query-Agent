from __future__ import annotations

from sql_query_agent.db import get_schema
from sql_query_agent.sample_data import init_sample_database


def test_schema_contains_sample_tables_and_columns(tmp_path) -> None:
    db_path = init_sample_database(tmp_path / "sample.db")

    schema = get_schema(db_path)

    assert schema["error"] is None
    tables = {table["name"]: table for table in schema["tables"]}
    assert {"customers", "orders", "order_items", "products"} <= set(tables)
    assert {"id", "name", "email", "signup_date"} <= {
        column["name"] for column in tables["customers"]["columns"]
    }
    assert tables["order_items"]["foreign_keys"]
