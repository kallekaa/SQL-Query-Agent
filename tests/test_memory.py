from __future__ import annotations

from pathlib import Path

from sql_query_agent import agent
from sql_query_agent.agent import AgentAnswer, AgentConfig
from sql_query_agent.sample_data import init_sample_database


def _successful_answer() -> AgentAnswer:
    sql = "SELECT customers.name, orders.status FROM customers JOIN orders ON orders.customer_id = customers.id"
    return AgentAnswer(
        answer="Ava Carter has paid orders.",
        sql_queries=[sql],
        query_results=[
            {
                "columns": ["name", "status"],
                "rows": [{"name": "Ava Carter", "status": "paid"}],
                "row_count": 1,
                "truncated": False,
                "sql": sql,
                "error": None,
            }
        ],
    )


def test_system_prompt_includes_persistent_memory_when_enabled(tmp_path) -> None:
    db_path = init_sample_database(tmp_path / "sample.db")
    memory_path = tmp_path / "sample.memory.md"
    memory_path.write_text(
        "# SQL Agent Memory\n\n- Orders join customers on orders.customer_id = customers.id.\n",
        encoding="utf-8",
    )
    config = AgentConfig(
        db_path=Path(db_path),
        model="gpt-5.4-mini",
        memory_path=memory_path,
    )

    prompt = agent._system_prompt(config)

    assert "Persistent database notes" in prompt
    assert "Orders join customers on orders.customer_id = customers.id." in prompt


def test_memory_is_not_considered_without_successful_query_results(tmp_path, monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("memory note generation should not run")

    monkeypatch.setattr(agent, "_generate_memory_note", fail_if_called)
    config = AgentConfig(
        db_path=tmp_path / "sample.db",
        model="gpt-5.4-mini",
        memory_path=tmp_path / "sample.memory.md",
    )

    agent._maybe_update_memory("Hello", AgentAnswer(answer="Hello."), config)
    agent._maybe_update_memory(
        "How many customers?",
        AgentAnswer(
            answer="The query failed.",
            query_results=[
                {
                    "columns": [],
                    "rows": [],
                    "row_count": 0,
                    "truncated": False,
                    "sql": "SELECT COUNT(*) FROM customers",
                    "error": "SQLite error: no such table: customers",
                }
            ],
        ),
        config,
    )

    assert not config.memory_path.exists()


def test_memory_appends_one_note_and_skips_exact_duplicates(tmp_path, monkeypatch) -> None:
    note = "- Orders join customers on orders.customer_id = customers.id."

    monkeypatch.setattr(agent, "_generate_memory_note", lambda *args, **kwargs: note)
    memory_path = tmp_path / "sample.memory.md"
    config = AgentConfig(
        db_path=tmp_path / "sample.db",
        model="gpt-5.4-mini",
        memory_path=memory_path,
    )
    answer = _successful_answer()

    agent._maybe_update_memory("Which customers have paid orders?", answer, config)
    agent._maybe_update_memory("Which customers have paid orders?", answer, config)

    memory = memory_path.read_text(encoding="utf-8")
    assert memory.startswith("# SQL Agent Memory")
    assert memory.count(note) == 1


def test_memory_disabled_does_not_read_or_write(tmp_path, monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("memory note generation should not run")

    monkeypatch.setattr(agent, "_generate_memory_note", fail_if_called)
    memory_path = tmp_path / "sample.memory.md"
    config = AgentConfig(
        db_path=tmp_path / "sample.db",
        model="gpt-5.4-mini",
        memory_enabled=False,
        memory_path=memory_path,
    )

    agent._maybe_update_memory("Which customers have paid orders?", _successful_answer(), config)

    assert not memory_path.exists()
