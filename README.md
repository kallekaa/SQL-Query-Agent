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

Then edit `.env`. For OpenAI, set `OPENAI_API_KEY`. For a local OpenAI-compatible model server, set `SQL_AGENT_MODEL_PROVIDER=local`.

Example:

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5.4-mini
SQL_AGENT_MODEL_PROVIDER=openai
DATABASE_FILE=./data/sample.db
SQL_AGENT_MAX_ROWS=100
LOCAL_MODEL_BASE_URL=http://localhost:1234/v1
LOCAL_MODEL_NAME=
LOCAL_MODEL_API_KEY=local
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=sql-query-agent
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

Use a local OpenAI-compatible model server:

```powershell
sql-agent ask "How many customers do we have?" --provider local --show-sql --show-table
```

Use `--db` on `ask` or `chat` to override the database path for a single run.

## CLI Commands

| Command | Description |
| --- | --- |
| `sql-agent init-sample --db ./data/sample.db` | Creates the sample SQLite database with customers, products, orders, and order items. |
| `sql-agent init-sample --db ./data/sample.db --overwrite` | Recreates the sample database if it already exists. |
| `sql-agent ask "How many customers do we have?"` | Runs one question through the agent and prints one answer. Uses the database path from `.env` unless `--db` is passed. |
| `sql-agent ask "How many customers do we have?" --show-sql` | Runs one question and also prints any SQL query the agent used. |
| `sql-agent ask "How many customers do we have?" --show-table` | Runs one question and also prints SQL query results as formatted CLI tables. |
| `sql-agent ask "How many customers do we have?" --show-sql --show-table` | Prints both the generated SQL and the returned SQL result table. |
| `sql-agent ask "..." --db ./data/sample.db` | Runs one question against a specific SQLite database file. |
| `sql-agent ask "..." --model gpt-5.4-mini` | Runs one question with a specific OpenAI model instead of `OPENAI_MODEL` from `.env`. |
| `sql-agent ask "..." --provider local` | Runs one question using a local OpenAI-compatible model server. If no model is configured, the app uses the first model from `/models`. |
| `sql-agent ask "..." --provider local --base-url http://localhost:11434/v1` | Runs one question against a specific local OpenAI-compatible base URL, such as an Ollama-compatible endpoint. |
| `sql-agent ask "..." --max-rows 50` | Limits the number of rows returned by the SQL query tool for that run. |
| `sql-agent chat` | Starts an interactive single-user terminal session. Uses `.env` for model and database settings. |
| `sql-agent chat --show-sql` | Starts interactive mode and prints SQL queries used for each answer. |
| `sql-agent chat --show-table` | Starts interactive mode and prints SQL query result tables after each answer. |
| `sql-agent chat --provider local --show-sql --show-table` | Starts interactive mode with a local OpenAI-compatible model server and prints SQL plus result tables. |
| `sql-agent chat --db ./data/sample.db` | Starts interactive mode against a specific SQLite database file. |
| `sql-agent --help` | Shows top-level CLI help. |
| `sql-agent <command> --help` | Shows help for a specific command, such as `ask`, `chat`, or `init-sample`. |

## Agentic Workflow

The app uses a ReAct-style LangGraph agent: the model receives the user question, decides whether it needs database context, calls tools when needed, then produces a final natural-language answer from the tool results.

Key steps in the code:

1. `sql_query_agent/cli.py` parses `init-sample`, `ask`, and `chat` commands.
2. `sql_query_agent/agent.py` loads `.env`, resolves the database path and model, and builds the LangGraph agent.
3. During agent setup, the prompt is initialized with table names only so the model knows the database shape without loading column metadata.
4. The agent prompt tells the model when to answer directly, when to inspect detailed schema, and when to query data.
5. `get_schema` in `sql_query_agent/db.py` returns columns, primary keys, and foreign keys only when the agent needs that detail.
6. `query_database` in `sql_query_agent/db.py` validates generated SQL, opens SQLite in read-only mode, executes the query, and returns rows.
7. `sql_query_agent/agent.py` extracts the final model response, generated SQL for `--show-sql`, and query result payloads for `--show-table`.

In short:

```text
User question
  -> CLI command
  -> LangGraph ReAct agent
  -> startup table-name context
  -> optional detailed schema lookup
  -> read-only SQL validation
  -> SQLite query execution
  -> natural-language answer
```

## Configuration

Values are loaded from `.env` in the current working directory. CLI flags take precedence over environment variables.

| Variable | Purpose |
| --- | --- |
| `SQL_AGENT_MODEL_PROVIDER` | Model provider: `openai` or `local`. Defaults to `openai`. |
| `OPENAI_API_KEY` | OpenAI API key used when `SQL_AGENT_MODEL_PROVIDER=openai`. |
| `OPENAI_MODEL` | Tool-capable model used by the agent. Defaults to `gpt-5.4-mini` in `.env.example`. |
| `OPENAI_BASE_URL` | Optional OpenAI-compatible base URL for OpenAI/proxy usage. |
| `LOCAL_MODEL_BASE_URL` | OpenAI-compatible local model server base URL. Defaults to `http://localhost:1234/v1`. |
| `LOCAL_MODEL_NAME` | Optional local model name. If empty, the app uses the first model returned by `LOCAL_MODEL_BASE_URL/models`. |
| `LOCAL_MODEL_API_KEY` | API key sent to the local model server. Defaults to `local`. |
| `DATABASE_FILE` | Default SQLite database path. |
| `SQL_AGENT_DB_PATH` | Backward-compatible SQLite database path. Takes precedence over `DATABASE_FILE`. |
| `SQL_AGENT_MAX_ROWS` | Maximum rows returned by the query tool. Defaults to `100`. |
| `LANGSMITH_TRACING` | Set to `true` to send LangGraph/LangChain traces to LangSmith. |
| `LANGSMITH_API_KEY` | LangSmith API key used when tracing is enabled. |
| `LANGSMITH_PROJECT` | LangSmith project name for traces. Defaults to `sql-query-agent` in `.env.example`. |
| `LANGSMITH_ENDPOINT` | Optional LangSmith endpoint for non-default regions. |

Database path precedence:

1. `--db`
2. `SQL_AGENT_DB_PATH`
3. `DATABASE_FILE`
4. `./data/sample.db`

## Local Models

The `local` provider works with local servers that expose OpenAI-compatible `/v1/chat/completions` and `/v1/models` endpoints. The selected local model must support tool/function calling because the SQL agent uses tools for schema lookup and query execution.

Common local base URLs:

- LM Studio: `http://localhost:1234/v1`
- Ollama: `http://localhost:11434/v1`

If `LOCAL_MODEL_NAME` and `--model` are omitted, the app calls `{LOCAL_MODEL_BASE_URL}/models` and uses the first returned model id.

## LangSmith Monitoring

LangSmith tracing is opt-in. To monitor agent actions, update `.env`:

```env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=ls_...
LANGSMITH_PROJECT=sql-query-agent
```

When tracing is enabled, LangChain/LangGraph automatically sends model calls, tool calls, and graph steps to LangSmith. The app also attaches metadata to each run:

- `database_file`
- `provider`
- `model`
- `base_url`
- `max_rows`
- chat `session_id` and `turn` for interactive runs

If your LangSmith account is outside the default US region, also set `LANGSMITH_ENDPOINT`.

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
