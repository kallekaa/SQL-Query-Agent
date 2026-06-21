from __future__ import annotations

import sqlite3

from sql_query_agent.cli import build_parser, format_query_result_table, main


def test_cli_init_sample_creates_sqlite_file(tmp_path, capsys) -> None:
    db_path = tmp_path / "sample.db"

    exit_code = main(["init-sample", "--db", str(db_path)])

    assert exit_code == 0
    assert db_path.exists()
    assert "Created sample database" in capsys.readouterr().out
    with sqlite3.connect(db_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    assert count == 4


def test_cli_accepts_show_table_for_ask_and_chat() -> None:
    parser = build_parser()

    ask_args = parser.parse_args(["ask", "How many customers?", "--show-table"])
    chat_args = parser.parse_args(["chat", "--show-table"])

    assert ask_args.show_table is True
    assert chat_args.show_table is True


def test_cli_accepts_openrouter_provider() -> None:
    parser = build_parser()

    ask_args = parser.parse_args(["ask", "How many customers?", "--provider", "openrouter"])
    chat_args = parser.parse_args(["chat", "--provider", "openrouter"])

    assert ask_args.provider == "openrouter"
    assert chat_args.provider == "openrouter"


def test_cli_accepts_memory_options_for_ask_and_chat() -> None:
    parser = build_parser()

    ask_args = parser.parse_args(
        ["ask", "How many customers?", "--memory-file", "./notes.md", "--no-memory"]
    )
    chat_args = parser.parse_args(["chat", "--memory-file", "./chat-memory.md"])

    assert ask_args.memory_file == "./notes.md"
    assert ask_args.memory_enabled is False
    assert chat_args.memory_file == "./chat-memory.md"
    assert chat_args.memory_enabled is None


def test_format_query_result_table_formats_rows() -> None:
    output = format_query_result_table(
        {
            "columns": ["name", "orders"],
            "rows": [{"name": "Alice", "orders": 12}, {"name": "Bo", "orders": 3}],
            "row_count": 2,
            "truncated": False,
            "sql": "SELECT name, orders FROM customers",
            "error": None,
        }
    )

    assert "| name  | orders |" in output
    assert "| Alice | 12     |" in output
    assert "| Bo    | 3      |" in output


def test_format_query_result_table_handles_empty_rows() -> None:
    output = format_query_result_table(
        {
            "columns": ["name"],
            "rows": [],
            "row_count": 0,
            "truncated": False,
            "sql": "SELECT name FROM customers WHERE 1 = 0",
            "error": None,
        }
    )

    assert "| name |" in output
    assert "(no rows)" in output


def test_format_query_result_table_handles_error_and_truncation() -> None:
    error_output = format_query_result_table(
        {
            "columns": [],
            "rows": [],
            "row_count": 0,
            "truncated": False,
            "sql": "DELETE FROM customers",
            "error": "Only read-only SELECT or WITH queries are allowed.",
        }
    )
    truncated_output = format_query_result_table(
        {
            "columns": ["id"],
            "rows": [{"id": 1}],
            "row_count": 1,
            "truncated": True,
            "sql": "SELECT id FROM customers",
            "error": None,
        }
    )

    assert "Query failed for SQL: DELETE FROM customers" in error_output
    assert "Only read-only SELECT or WITH queries are allowed." in error_output
    assert "Result truncated; showing returned rows only." in truncated_output
