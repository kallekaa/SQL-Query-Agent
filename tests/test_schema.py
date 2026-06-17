from __future__ import annotations

from pathlib import Path

from sql_query_agent.agent import AgentConfig, _system_prompt
from sql_query_agent.db import get_schema, get_table_names
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


def test_table_names_contains_no_column_metadata(tmp_path) -> None:
    db_path = init_sample_database(tmp_path / "sample.db")

    result = get_table_names(db_path)

    assert result["error"] is None
    assert result["tables"] == ["customers", "order_items", "orders", "products"]
    assert "columns" not in result


def test_system_prompt_includes_table_names_without_columns(tmp_path) -> None:
    db_path = init_sample_database(tmp_path / "sample.db")
    config = AgentConfig(db_path=Path(db_path), model="gpt-5.4-mini")

    prompt = _system_prompt(config)

    assert "Available database tables: customers, order_items, orders, products." in prompt
    assert "signup_date" not in prompt
    assert "customer_id" not in prompt
