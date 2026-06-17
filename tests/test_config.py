from __future__ import annotations

from sql_query_agent.agent import config_from_env


def test_config_loads_openai_values_from_dotenv(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("SQL_AGENT_DB_PATH", raising=False)
    monkeypatch.delenv("DATABASE_FILE", raising=False)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=test-key",
                "OPENAI_MODEL=gpt-5.4-mini",
                "DATABASE_FILE=./data/sample.db",
            ]
        ),
        encoding="utf-8",
    )

    config = config_from_env()

    assert config.model == "gpt-5.4-mini"
    assert str(config.db_path).replace("\\", "/") == "data/sample.db"


def test_sql_agent_db_path_takes_precedence_over_database_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("SQL_AGENT_DB_PATH", raising=False)
    monkeypatch.delenv("DATABASE_FILE", raising=False)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=test-key",
                "OPENAI_MODEL=gpt-5.4-mini",
                "DATABASE_FILE=./data/from-database-file.db",
                "SQL_AGENT_DB_PATH=./data/from-sql-agent-db-path.db",
            ]
        ),
        encoding="utf-8",
    )

    config = config_from_env()

    assert str(config.db_path).replace("\\", "/") == "data/from-sql-agent-db-path.db"
