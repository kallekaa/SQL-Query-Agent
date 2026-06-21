from __future__ import annotations

from sql_query_agent.agent import config_from_env


def _clear_agent_env(monkeypatch) -> None:
    for name in [
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "OPENAI_BASE_URL",
        "OPENROUTER_API_KEY",
        "OPENROUTER_MODEL",
        "OPENROUTER_BASE_URL",
        "OPENROUTER_SITE_URL",
        "OPENROUTER_APP_NAME",
        "SQL_AGENT_MODEL_PROVIDER",
        "SQL_AGENT_DB_PATH",
        "DATABASE_FILE",
        "SQL_AGENT_MAX_ROWS",
        "SQL_AGENT_MEMORY_ENABLED",
        "SQL_AGENT_MEMORY_FILE",
        "LOCAL_MODEL_BASE_URL",
        "LOCAL_MODEL_NAME",
        "LOCAL_MODEL_API_KEY",
    ]:
        monkeypatch.delenv(name, raising=False)


def test_config_loads_openai_values_from_dotenv(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_agent_env(monkeypatch)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "SQL_AGENT_MODEL_PROVIDER=openai",
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
    assert str(config.memory_path).replace("\\", "/") == "data/sample.memory.md"


def test_database_file_takes_precedence_over_legacy_sql_agent_db_path(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_agent_env(monkeypatch)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "SQL_AGENT_MODEL_PROVIDER=openai",
                "OPENAI_API_KEY=test-key",
                "OPENAI_MODEL=gpt-5.4-mini",
                "DATABASE_FILE=./data/from-database-file.db",
                "SQL_AGENT_DB_PATH=./data/from-sql-agent-db-path.db",
            ]
        ),
        encoding="utf-8",
    )

    config = config_from_env()

    assert str(config.db_path).replace("\\", "/") == "data/from-database-file.db"


def test_legacy_sql_agent_db_path_is_used_when_database_file_is_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_agent_env(monkeypatch)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "SQL_AGENT_MODEL_PROVIDER=openai",
                "OPENAI_API_KEY=test-key",
                "OPENAI_MODEL=gpt-5.4-mini",
                "SQL_AGENT_DB_PATH=./data/from-sql-agent-db-path.db",
            ]
        ),
        encoding="utf-8",
    )

    config = config_from_env()

    assert str(config.db_path).replace("\\", "/") == "data/from-sql-agent-db-path.db"


def test_memory_file_can_be_overridden_from_env(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_agent_env(monkeypatch)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "SQL_AGENT_MODEL_PROVIDER=openai",
                "OPENAI_API_KEY=test-key",
                "OPENAI_MODEL=gpt-5.4-mini",
                "DATABASE_FILE=./data/sample.db",
                "SQL_AGENT_MEMORY_FILE=./notes/database-memory.md",
            ]
        ),
        encoding="utf-8",
    )

    config = config_from_env()

    assert str(config.memory_path).replace("\\", "/") == "notes/database-memory.md"


def test_memory_can_be_disabled_from_env(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_agent_env(monkeypatch)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "SQL_AGENT_MODEL_PROVIDER=openai",
                "OPENAI_API_KEY=test-key",
                "OPENAI_MODEL=gpt-5.4-mini",
                "DATABASE_FILE=./data/sample.db",
                "SQL_AGENT_MEMORY_ENABLED=false",
            ]
        ),
        encoding="utf-8",
    )

    config = config_from_env()

    assert config.memory_enabled is False
    assert config.memory_path is None


def test_config_loads_openrouter_values_from_dotenv(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_agent_env(monkeypatch)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "SQL_AGENT_MODEL_PROVIDER=openrouter",
                "OPENROUTER_API_KEY=test-openrouter-key",
                "OPENROUTER_MODEL=openai/gpt-5.4-mini",
                "DATABASE_FILE=./data/sample.db",
            ]
        ),
        encoding="utf-8",
    )

    config = config_from_env()

    assert config.provider == "openrouter"
    assert config.model == "openai/gpt-5.4-mini"
    assert config.base_url == "https://openrouter.ai/api/v1"
    assert config.api_key == "test-openrouter-key"


def test_openrouter_is_default_provider(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_agent_env(monkeypatch)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "OPENROUTER_API_KEY=test-openrouter-key",
                "OPENROUTER_MODEL=openai/gpt-5.4-mini",
            ]
        ),
        encoding="utf-8",
    )

    config = config_from_env()

    assert config.provider == "openrouter"
    assert config.model == "openai/gpt-5.4-mini"


def test_openrouter_base_url_and_headers_can_be_configured(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _clear_agent_env(monkeypatch)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "SQL_AGENT_MODEL_PROVIDER=openrouter",
                "OPENROUTER_API_KEY=test-openrouter-key",
                "OPENROUTER_MODEL=anthropic/claude-sonnet-4.5",
                "OPENROUTER_BASE_URL=https://example.test/api/v1/",
                "OPENROUTER_SITE_URL=https://example.test",
                "OPENROUTER_APP_NAME=SQL Query Agent",
            ]
        ),
        encoding="utf-8",
    )

    config = config_from_env()

    assert config.base_url == "https://example.test/api/v1"
    assert config.default_headers == {
        "HTTP-Referer": "https://example.test",
        "X-Title": "SQL Query Agent",
    }
