from __future__ import annotations

from pathlib import Path

from sql_query_agent.agent import AgentConfig, _runnable_config


def test_runnable_config_adds_langsmith_trace_metadata() -> None:
    config = AgentConfig(db_path=Path("data/sample.db"), model="gpt-5.4-mini", max_rows=25)

    runnable_config = _runnable_config(
        config,
        run_name="sql-agent ask",
        metadata={"chat_session_id": "session-1", "turn": 2},
    )

    assert runnable_config["run_name"] == "sql-agent ask"
    assert "sql-query-agent" in runnable_config["tags"]
    assert runnable_config["metadata"] == {
        "database_file": "data\\sample.db" if "\\" in str(Path("data/sample.db")) else "data/sample.db",
        "provider": "openrouter",
        "model": "gpt-5.4-mini",
        "max_rows": 25,
        "chat_session_id": "session-1",
        "turn": 2,
    }
