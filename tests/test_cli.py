from __future__ import annotations

import sqlite3
from pathlib import Path

from sql_query_agent.agent import AgentConfig
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

def test_cli_accepts_audit_log_for_agent_commands() -> None:
    parser = build_parser()

    ask_args = parser.parse_args(["ask", "How many customers?", "--audit-log", "./logs/audit.jsonl"])
    chat_args = parser.parse_args(["chat", "--audit-log", "./logs/chat-audit.jsonl"])
    ui_args = parser.parse_args(["ui", "--audit-log", "./logs/ui-audit.jsonl"])
    plan_args = parser.parse_args(["plan", "--audit-log", "./logs/plan-audit.jsonl"])

    assert ask_args.audit_log_file == "./logs/audit.jsonl"
    assert chat_args.audit_log_file == "./logs/chat-audit.jsonl"
    assert ui_args.audit_log_file == "./logs/ui-audit.jsonl"
    assert plan_args.audit_log_file == "./logs/plan-audit.jsonl"


def test_cli_accepts_ui_command_options() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "ui",
            "--db",
            "./data/sample.db",
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
            "--no-open",
        ]
    )

    assert args.command == "ui"
    assert args.db == "./data/sample.db"
    assert args.host == "127.0.0.1"
    assert args.port == 8765
    assert args.open_browser is False


def test_cli_accepts_plan_options() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "plan",
            "--planner-provider",
            "openai",
            "--planner-model",
            "gpt-5.4-mini",
            "--planner-base-url",
            "https://planner.test/v1",
            "--max-steps",
            "12",
            "--show-steps",
            "--show-sql",
            "--show-table",
        ]
    )

    assert args.command == "plan"
    assert args.planner_provider == "openai"
    assert args.planner_model == "gpt-5.4-mini"
    assert args.planner_base_url == "https://planner.test/v1"
    assert args.max_steps == 12
    assert args.show_steps is True
    assert args.show_sql is True
    assert args.show_table is True


def test_cli_plan_builds_sql_and_planner_configs(monkeypatch) -> None:
    captured = {}

    def fake_config_from_env(**kwargs):
        captured["sql_kwargs"] = kwargs
        return AgentConfig(
            db_path=Path("data/sample.db"),
            model="sql-model",
            provider="openai",
            api_key="sql-key",
            memory_enabled=False,
        )

    def fake_run_plan_chat(config):
        captured["planner_config"] = config

    monkeypatch.setattr("sql_query_agent.agent.config_from_env", fake_config_from_env)
    monkeypatch.setattr("sql_query_agent.planner.run_plan_chat", fake_run_plan_chat)

    exit_code = main(
        [
            "plan",
            "--db",
            "./data/custom.db",
            "--planner-model",
            "planner-model",
            "--max-steps",
            "3",
            "--show-steps",
        ]
    )

    assert exit_code == 0
    assert captured["sql_kwargs"]["db_path"] == "./data/custom.db"
    assert captured["planner_config"].model == "planner-model"
    assert captured["planner_config"].max_steps == 3
    assert captured["planner_config"].show_steps is True


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
