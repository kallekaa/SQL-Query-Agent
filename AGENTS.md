# Codex Agent Notes

This project is a minimal Python CLI app for a LangGraph SQL query agent.

## Setup

Use a virtual environment from the repo root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Runtime config is loaded from `.env` in the current working directory via `python-dotenv`.

Required for live agent calls:

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5.4-mini
SQL_AGENT_MODEL_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=openai/gpt-5.4-mini
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_SITE_URL=
OPENROUTER_APP_NAME=SQL Query Agent
DATABASE_FILE=./data/sample.db
LOCAL_MODEL_BASE_URL=http://localhost:1234/v1
LOCAL_MODEL_NAME=
LOCAL_MODEL_API_KEY=local
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=sql-query-agent
```

## Commands

```powershell
sql-agent init-sample --db ./data/sample.db
sql-agent ask "How many customers do we have?" --show-sql --show-table
sql-agent chat
pytest
```

## Conventions

- Keep dependencies minimal. Prefer stdlib unless there is a clear reason to add a package.
- Preserve read-only runtime database access. Query execution must reject writes before SQLite execution.
- Keep model-backed tests optional; normal tests should not require `OPENAI_API_KEY`.
- Keep local model support generic as `provider=local`; do not hard-code one local model app in code identifiers.
- Keep LangSmith tracing opt-in through `.env`; never print or commit `LANGSMITH_API_KEY`.
- Use `DATABASE_FILE` for the main documented DB path and keep `SQL_AGENT_DB_PATH` as a compatible alias.
- Do not commit `.env`, local SQLite databases, pytest temp folders, or virtual environments.
