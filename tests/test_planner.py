from __future__ import annotations

from pathlib import Path

from sql_query_agent import planner
from sql_query_agent.agent import AgentAnswer, AgentConfig


def _clear_model_env(monkeypatch) -> None:
    for name in [
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "OPENAI_BASE_URL",
        "OPENROUTER_API_KEY",
        "OPENROUTER_MODEL",
        "OPENROUTER_BASE_URL",
        "OPENROUTER_SITE_URL",
        "OPENROUTER_APP_NAME",
        "LOCAL_MODEL_BASE_URL",
        "LOCAL_MODEL_NAME",
        "LOCAL_MODEL_API_KEY",
        "SQL_PLANNER_MODEL_PROVIDER",
        "SQL_PLANNER_MODEL",
        "SQL_PLANNER_BASE_URL",
        "SQL_PLANNER_MAX_STEPS",
    ]:
        monkeypatch.delenv(name, raising=False)


def _sql_config() -> AgentConfig:
    return AgentConfig(
        db_path=Path("data/sample.db"),
        model="sql-model",
        provider="openai",
        base_url="https://sql.test/v1",
        api_key="sql-key",
        memory_enabled=False,
    )


def test_planner_config_falls_back_to_sql_agent_model(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_model_env(monkeypatch)

    config = planner.planner_config_from_env(_sql_config())

    assert config.provider == "openai"
    assert config.model == "sql-model"
    assert config.base_url == "https://sql.test/v1"
    assert config.api_key == "sql-key"
    assert config.max_steps == 25


def test_planner_config_uses_planner_env_overrides(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("SQL_PLANNER_MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("SQL_PLANNER_MODEL", "anthropic/claude-sonnet-4.5")
    monkeypatch.setenv("SQL_PLANNER_BASE_URL", "https://planner.test/v1/")
    monkeypatch.setenv("SQL_PLANNER_MAX_STEPS", "7")
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")

    config = planner.planner_config_from_env(_sql_config())

    assert config.provider == "openrouter"
    assert config.model == "anthropic/claude-sonnet-4.5"
    assert config.base_url == "https://planner.test/v1"
    assert config.api_key == "router-key"
    assert config.max_steps == 7


def test_ask_sql_agent_tool_returns_answer_data_and_enforces_cap(monkeypatch, capsys) -> None:
    query_result = {
        "columns": ["customer_count"],
        "rows": [{"customer_count": 4}],
        "row_count": 1,
        "truncated": False,
        "sql": "SELECT COUNT(*) AS customer_count FROM customers",
        "error": None,
    }
    calls = []

    def fake_ask(question, config, run_name="sql-agent ask", metadata=None):
        calls.append(
            {
                "question": question,
                "config": config,
                "run_name": run_name,
                "metadata": metadata,
            }
        )
        return AgentAnswer(
            answer="There are 4 customers.",
            sql_queries=[query_result["sql"]],
            query_results=[query_result],
        )

    monkeypatch.setattr(planner.sql_agent, "ask", fake_ask)
    config = planner.PlannerConfig(
        sql_config=_sql_config(),
        model="planner-model",
        provider="openai",
        api_key="planner-key",
        max_steps=1,
        show_steps=True,
    )
    ask_sql_agent = planner._make_tools(config, session_id="session-1", turn_number=2)[0]

    result = ask_sql_agent("How many customers are there?")
    limit_result = ask_sql_agent("What is revenue?")

    assert result["answer"] == "There are 4 customers."
    assert result["sql_queries"] == [query_result["sql"]]
    assert result["query_results"] == [query_result]
    assert result["call_number"] == 1
    assert result["error"] is None
    assert len(calls) == 1
    assert calls[0]["run_name"] == "sql-agent planner sql-tool"
    assert calls[0]["metadata"] == {
        "planner_session_id": "session-1",
        "planner_turn": 2,
        "planner_sql_call": 1,
    }
    assert limit_result["error"] == (
        "Planner SQL-agent call limit reached (1). "
        "Summarize partial progress or ask the user to narrow the goal."
    )
    assert limit_result["call_number"] == 2
    output = capsys.readouterr().out
    assert "Planner step 1: How many customers are there?" in output
    assert "Planner step 1 answer: There are 4 customers." in output


def test_planner_prompt_restricts_database_access_to_sql_agent_tool() -> None:
    config = planner.PlannerConfig(
        sql_config=_sql_config(),
        model="planner-model",
        provider="openai",
        api_key="planner-key",
        max_steps=4,
    )

    prompt = planner._system_prompt(config)

    assert "Use ask_sql_agent as your only source for database facts." in prompt
    assert "Do not write SQL yourself" in prompt
    assert "You may call ask_sql_agent up to 4 times" in prompt


def test_run_plan_chat_uses_fake_planner_agent(monkeypatch, capsys) -> None:
    built = []
    invocations = []

    class FakePlanner:
        def invoke(self, payload, config):
            invocations.append({"payload": payload, "config": config})
            return {"messages": [*payload["messages"], {"content": "Planner answer."}]}

    def fake_build_planner_agent(config, session_id="", turn_number=0):
        built.append(
            {
                "config": config,
                "session_id": session_id,
                "turn_number": turn_number,
            }
        )
        return FakePlanner()

    inputs = iter(["Find the best customers", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.setattr(planner, "build_planner_agent", fake_build_planner_agent)
    config = planner.PlannerConfig(
        sql_config=_sql_config(),
        model="planner-model",
        provider="openai",
        api_key="planner-key",
        max_steps=3,
    )

    planner.run_plan_chat(config)

    output = capsys.readouterr().out
    assert "SQL Planner Orchestrator. Type 'exit' or 'quit' to end." in output
    assert "Planner answer." in output
    assert built[0]["turn_number"] == 1
    assert invocations[0]["payload"]["messages"] == [
        {"role": "user", "content": "Find the best customers"}
    ]
    assert invocations[0]["config"]["run_name"] == "sql-agent planner chat"
    assert invocations[0]["config"]["metadata"]["planner_turn"] == 1
