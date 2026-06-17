# SQL Query Agent

A minimal CLI LangGraph ReAct agent that answers natural-language questions about a SQLite database.

The agent can inspect database schema, generate read-only SQL, execute queries, and summarize results in plain English from the terminal.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Create a `.env` file before using `ask` or `chat`:

```powershell
Copy-Item .env.example .env
```

Then edit `.env` and set `OPENAI_API_KEY`.

Example:

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5.4-mini
DATABASE_FILE=./data/sample.db
SQL_AGENT_MAX_ROWS=100
```

## Quick Start

Create a sample database:

```powershell
sql-agent init-sample --db ./data/sample.db
```

If your `.env` contains `DATABASE_FILE=./data/sample.db`, you can also run:

```powershell
sql-agent init-sample --db $env:DATABASE_FILE
```

Ask one question:

```powershell
sql-agent ask "How many customers do we have?" --show-sql
```

Start an interactive session:

```powershell
sql-agent chat
```

Use `--db` on `ask` or `chat` to override the database path for a single run.

## Configuration

Values are loaded from `.env` in the current working directory. CLI flags take precedence over environment variables.

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | OpenAI API key used by `langchain-openai`. |
| `OPENAI_MODEL` | Tool-capable model used by the agent. Defaults to `gpt-5.4-mini` in `.env.example`. |
| `DATABASE_FILE` | Default SQLite database path. |
| `SQL_AGENT_DB_PATH` | Backward-compatible SQLite database path. Takes precedence over `DATABASE_FILE`. |
| `SQL_AGENT_MAX_ROWS` | Maximum rows returned by the query tool. Defaults to `100`. |

Database path precedence:

1. `--db`
2. `SQL_AGENT_DB_PATH`
3. `DATABASE_FILE`
4. `./data/sample.db`

## Safety

The agent runtime only executes read-only SQL. Queries are parsed with `sqlglot`, only one `SELECT` or `WITH` statement is accepted, and SQLite is opened with a read-only connection URI.

The sample database initializer writes a demo database, but that command is separate from agent query execution.

Rejected SQL returns a tool error instead of running against the database.

## Tests

```powershell
pytest
```

## Project Layout

```text
sql_query_agent/
  agent.py        LangGraph agent setup and .env-backed config.
  cli.py          argparse command-line interface.
  db.py           SQLite schema/query tools and read-only SQL validation.
  sample_data.py  Sample database initializer.
tests/            Minimal pytest coverage for config, SQL safety, schema, and CLI setup.
```
