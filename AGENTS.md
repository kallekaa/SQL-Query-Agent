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
DATABASE_FILE=./data/sample.db
```

## Commands

```powershell
sql-agent init-sample --db ./data/sample.db
sql-agent ask "How many customers do we have?" --show-sql
sql-agent chat
pytest
```

## Conventions

- Keep dependencies minimal. Prefer stdlib unless there is a clear reason to add a package.
- Preserve read-only runtime database access. Query execution must reject writes before SQLite execution.
- Keep model-backed tests optional; normal tests should not require `OPENAI_API_KEY`.
- Use `DATABASE_FILE` for the main documented DB path and keep `SQL_AGENT_DB_PATH` as a compatible alias.
- Do not commit `.env`, local SQLite databases, pytest temp folders, or virtual environments.
