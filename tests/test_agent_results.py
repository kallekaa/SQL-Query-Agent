from __future__ import annotations

import json

from sql_query_agent import agent
from sql_query_agent.agent import AgentConfig
from sql_query_agent.agent import _answer_from_result, _extract_query_results
from sql_query_agent.sample_data import init_sample_database


def test_extract_query_results_from_dict_tool_message() -> None:
    result = {
        "columns": ["customer_count"],
        "rows": [{"customer_count": 4}],
        "row_count": 1,
        "truncated": False,
        "sql": "SELECT COUNT(*) AS customer_count FROM customers",
        "error": None,
    }

    extracted = _extract_query_results([{"name": "query_database", "content": result}])

    assert extracted == [result]


def test_extract_query_results_from_json_tool_message() -> None:
    result = {
        "columns": ["name"],
        "rows": [{"name": "Alice"}],
        "row_count": 1,
        "truncated": False,
        "sql": "SELECT name FROM customers",
        "error": None,
    }

    extracted = _extract_query_results(
        [{"name": "query_database", "content": json.dumps(result)}]
    )

    assert extracted == [result]


def test_extract_query_results_from_unnamed_content_block_message() -> None:
    result = {
        "columns": ["name"],
        "rows": [{"name": "Alice"}],
        "row_count": 1,
        "truncated": False,
        "sql": "SELECT name FROM customers",
        "error": None,
    }

    extracted = _extract_query_results(
        [{"content": [{"type": "text", "text": json.dumps(result)}]}]
    )

    assert extracted == [result]


def test_answer_from_result_includes_sql_and_query_results() -> None:
    query_result = {
        "columns": ["customer_count"],
        "rows": [{"customer_count": 4}],
        "row_count": 1,
        "truncated": False,
        "sql": "SELECT COUNT(*) AS customer_count FROM customers",
        "error": None,
    }
    messages = [
        {
            "tool_calls": [
                {
                    "name": "query_database",
                    "args": {"sql": query_result["sql"]},
                }
            ]
        },
        {"name": "query_database", "content": query_result},
        {"content": "There are 4 customers."},
    ]

    answer = _answer_from_result({"messages": messages})

    assert answer.answer == "There are 4 customers."
    assert answer.sql_queries == [query_result["sql"]]
    assert answer.query_results == [query_result]


def test_query_tool_prints_sql_and_table_immediately(tmp_path, capsys) -> None:
    db_path = init_sample_database(tmp_path / "sample.db")
    config = AgentConfig(
        db_path=db_path,
        model="gpt-5.4-mini",
        show_sql=True,
        show_table=True,
        memory_enabled=False,
    )
    query_database = agent._make_tools(config)[1]

    result = query_database("SELECT COUNT(*) AS customer_count FROM customers")

    output = capsys.readouterr().out
    assert result["error"] is None
    assert output.index("SQL: SELECT COUNT(*) AS customer_count FROM customers") < output.index(
        "| customer_count |"
    )
    assert output.endswith("\n\n")


def test_query_tool_writes_audit_event_for_successful_query(tmp_path) -> None:
    db_path = init_sample_database(tmp_path / "sample.db")
    audit_log_path = tmp_path / "logs" / "query-audit.jsonl"
    config = AgentConfig(
        db_path=db_path,
        model="gpt-5.4-mini",
        provider="openai",
        max_rows=25,
        memory_enabled=False,
        audit_log_path=audit_log_path,
    )
    query_database = agent._make_tools(config)[1]

    result = query_database("SELECT COUNT(*) AS customer_count FROM customers")

    event = json.loads(audit_log_path.read_text(encoding="utf-8").strip())
    assert result["error"] is None
    assert event["event"] == "query_database"
    assert event["database_file"] == str(db_path)
    assert event["provider"] == "openai"
    assert event["model"] == "gpt-5.4-mini"
    assert event["max_rows"] == 25
    assert event["sql"] == "SELECT COUNT(*) AS customer_count FROM customers"
    assert event["row_count"] == 1
    assert event["truncated"] is False
    assert event["status"] == "ok"
    assert event["error_type"] is None
    assert event["error"] is None
    assert isinstance(event["duration_ms"], float)
    assert "timestamp" in event


def test_query_tool_writes_audit_event_for_rejected_query(tmp_path) -> None:
    db_path = init_sample_database(tmp_path / "sample.db")
    audit_log_path = tmp_path / "query-audit.jsonl"
    config = AgentConfig(
        db_path=db_path,
        model="gpt-5.4-mini",
        memory_enabled=False,
        audit_log_path=audit_log_path,
    )
    query_database = agent._make_tools(config)[1]

    result = query_database("DELETE FROM customers")

    event = json.loads(audit_log_path.read_text(encoding="utf-8").strip())
    assert result["error"]
    assert result["error_type"] == "SQLValidationError"
    assert event["status"] == "error"
    assert event["error_type"] == "SQLValidationError"
    assert event["error"] == result["error"]
