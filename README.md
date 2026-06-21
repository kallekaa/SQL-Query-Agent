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

Then edit `.env`. OpenRouter is the default provider, so set `OPENROUTER_API_KEY` and `OPENROUTER_MODEL`. For OpenAI, set `SQL_AGENT_MODEL_PROVIDER=openai` and `OPENAI_API_KEY`. For a local OpenAI-compatible model server, set `SQL_AGENT_MODEL_PROVIDER=local`.

Example:

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
SQL_AGENT_MAX_ROWS=100
SQL_AGENT_MEMORY_ENABLED=true
SQL_AGENT_MEMORY_FILE=
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

OpenRouter is the default provider, so this is equivalent to passing `--provider openrouter`:

```powershell
sql-agent ask "How many customers do we have?" --model openai/gpt-5.4-mini --show-sql
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
| `sql-agent ask "..." --model openai/gpt-5.4-mini` | Runs one question with a specific OpenRouter model instead of `OPENROUTER_MODEL` from `.env`. |
| `sql-agent ask "..." --provider openai --model gpt-5.4-mini` | Runs one question using OpenAI with a specific OpenAI model. |
| `sql-agent ask "..." --provider openrouter --model openai/gpt-5.4-mini` | Runs one question using OpenRouter with a specific OpenRouter model slug. |
| `sql-agent ask "..." --provider local` | Runs one question using a local OpenAI-compatible model server. If no model is configured, the app uses the first model from `/models`. |
| `sql-agent ask "..." --provider local --base-url http://localhost:11434/v1` | Runs one question against a specific local OpenAI-compatible base URL, such as an Ollama-compatible endpoint. |
| `sql-agent ask "..." --max-rows 50` | Limits the number of rows returned by the SQL query tool for that run. |
| `sql-agent ask "..." --memory-file ./data/custom-memory.md` | Uses a specific markdown file for persistent database notes. |
| `sql-agent ask "..." --no-memory` | Disables persistent markdown memory for that run. |
| `sql-agent chat` | Starts an interactive single-user terminal session. Uses `.env` for model and database settings. |
| `sql-agent chat --show-sql` | Starts interactive mode and prints SQL queries used for each answer. |
| `sql-agent chat --show-table` | Starts interactive mode and prints SQL query result tables after each answer. |
| `sql-agent chat --provider openrouter --show-sql --show-table` | Starts interactive mode using OpenRouter and prints SQL plus result tables. |
| `sql-agent chat --provider local --show-sql --show-table` | Starts interactive mode with a local OpenAI-compatible model server and prints SQL plus result tables. |
| `sql-agent chat --db ./data/sample.db` | Starts interactive mode against a specific SQLite database file. |
| `sql-agent chat --no-memory` | Starts interactive mode without loading or writing persistent memory. |
| `sql-agent --help` | Shows top-level CLI help. |
| `sql-agent <command> --help` | Shows help for a specific command, such as `ask`, `chat`, or `init-sample`. |

## Agentic Workflow

The app uses a ReAct-style LangGraph agent: the model receives the user question, decides whether it needs database context, calls tools when needed, then produces a final natural-language answer from the tool results.

### Key Code Path

These are the main steps the code follows when you run `sql-agent ask` or `sql-agent chat`:

1. `sql_query_agent/cli.py` parses `init-sample`, `ask`, and `chat` commands.
2. `config_from_env` in `sql_query_agent/agent.py` loads `.env`, applies CLI overrides, validates the provider, resolves the model settings, and chooses the database path.
3. `build_agent` creates a LangGraph ReAct agent with a `ChatOpenAI` client and two tools: `get_schema` and `query_database`.
4. `_system_prompt` builds the instruction prompt. It includes today's date, the available table names, optional persistent memory notes, and the rules for read-only SQL.
5. `_table_context` loads table names only. Detailed columns, keys, and relationships are left out until the model explicitly calls `get_schema`.
6. When schema detail is needed, `get_schema` calls `sql_query_agent/db.py` to return columns, primary keys, and foreign keys for selected tables.
7. When data is needed, `query_database` sends generated SQL to `sql_query_agent/db.py`, where the SQL is validated as read-only before SQLite executes it.
8. `_print_intermediate_query_output` prints generated SQL or result tables during the run when `--show-sql` or `--show-table` is enabled.
9. `_answer_from_result` reads the LangGraph message trace and returns a clean `AgentAnswer` containing the final text, generated SQL, and query result payloads.
10. If persistent memory is enabled and the answer used successful query results, `_remember_after_answer` asks the model whether one short reusable database note should be appended to markdown.

### How One Question Is Answered

1. You run a command such as `sql-agent ask "How many customers do we have?" --show-sql`.
2. The CLI turns that command into an `AgentConfig`, including the database path, model provider, row limit, display flags, and memory settings.
3. The agent starts with lightweight database context: table names and any saved memory notes. This keeps the prompt small and lets the model request more detail only when needed.
4. The model chooses the next action. It can answer directly, call `get_schema` for database structure, or call `query_database` for actual rows.
5. If SQL is generated, `db.py` rejects write/admin statements and only allows one read-only SQLite `SELECT` or `WITH` query.
6. The query result goes back to the model, and the model writes the final answer in natural language.
7. The CLI prints the final answer. If requested, it also prints the generated SQL and result table.
8. After a successful database-backed answer, memory may append a reusable note such as a table relationship or business term mapping for future questions.

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
| `SQL_AGENT_MODEL_PROVIDER` | Model provider: `openrouter`, `openai`, or `local`. Defaults to `openrouter`. |
| `OPENAI_API_KEY` | OpenAI API key used when `SQL_AGENT_MODEL_PROVIDER=openai`. |
| `OPENAI_MODEL` | Tool-capable model used by the agent. Defaults to `gpt-5.4-mini` in `.env.example`. |
| `OPENAI_BASE_URL` | Optional OpenAI-compatible base URL for OpenAI/proxy usage. |
| `OPENROUTER_API_KEY` | OpenRouter API key used when `SQL_AGENT_MODEL_PROVIDER=openrouter`. |
| `OPENROUTER_MODEL` | OpenRouter model slug used by the agent, such as `openai/gpt-5.4-mini`. |
| `OPENROUTER_BASE_URL` | OpenRouter-compatible base URL. Defaults to `https://openrouter.ai/api/v1`. |
| `OPENROUTER_SITE_URL` | Optional OpenRouter attribution site URL sent as `HTTP-Referer`. |
| `OPENROUTER_APP_NAME` | Optional OpenRouter attribution app name sent as `X-Title`. |
| `LOCAL_MODEL_BASE_URL` | OpenAI-compatible local model server base URL. Defaults to `http://localhost:1234/v1`. |
| `LOCAL_MODEL_NAME` | Optional local model name. If empty, the app uses the first model returned by `LOCAL_MODEL_BASE_URL/models`. |
| `LOCAL_MODEL_API_KEY` | API key sent to the local model server. Defaults to `local`. |
| `DATABASE_FILE` | Default SQLite database path. |
| `SQL_AGENT_DB_PATH` | Legacy SQLite database path alias. Used only when `DATABASE_FILE` is not set. |
| `SQL_AGENT_MAX_ROWS` | Maximum rows returned by the query tool. Defaults to `100`. |
| `SQL_AGENT_MEMORY_ENABLED` | Enables persistent markdown memory when true. Defaults to `true`. |
| `SQL_AGENT_MEMORY_FILE` | Optional markdown memory file path. Defaults to a per-database sidecar such as `./data/sample.memory.md`. |
| `LANGSMITH_TRACING` | Set to `true` to send LangGraph/LangChain traces to LangSmith. |
| `LANGSMITH_API_KEY` | LangSmith API key used when tracing is enabled. |
| `LANGSMITH_PROJECT` | LangSmith project name for traces. Defaults to `sql-query-agent` in `.env.example`. |
| `LANGSMITH_ENDPOINT` | Optional LangSmith endpoint for non-default regions. |

Database path precedence:

1. `--db`
2. `DATABASE_FILE`
3. `SQL_AGENT_DB_PATH`
4. `./data/sample.db`

## Persistent Memory

The agent can keep short reusable notes about the database in a markdown file. Memory is enabled by default and is loaded into the system prompt before each `ask` run and each `chat` turn.

By default, the memory file is a sidecar next to the configured database. For `DATABASE_FILE=./data/sample.db`, the memory file is `./data/sample.memory.md`.

After a database-backed answer, the model gets a small follow-up prompt asking whether one short note should be appended. Notes should help future SQL generation, such as remembering table relationships, business term mappings, useful joins, status meanings, date semantics, or reusable metric definitions. One-off answers and raw counts should not be written.

Use `SQL_AGENT_MEMORY_FILE` or `--memory-file` to choose a different file. Use `SQL_AGENT_MEMORY_ENABLED=false` or `--no-memory` to disable loading and writing memory.

## Local Models

The `local` provider works with local servers that expose OpenAI-compatible `/v1/chat/completions` and `/v1/models` endpoints. The selected local model must support tool/function calling because the SQL agent uses tools for schema lookup and query execution.

Common local base URLs:

- LM Studio: `http://localhost:1234/v1`
- Ollama: `http://localhost:11434/v1`

If `LOCAL_MODEL_NAME` and `--model` are omitted, the app calls `{LOCAL_MODEL_BASE_URL}/models` and uses the first returned model id.

## OpenRouter

The `openrouter` provider is the default. It uses OpenRouter's OpenAI-compatible chat API at `https://openrouter.ai/api/v1`. Set an OpenRouter API key and model slug in `.env`:

```env
SQL_AGENT_MODEL_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=openai/gpt-5.4-mini
```

OpenRouter model names include the provider prefix, such as `openai/...`, `anthropic/...`, or another slug from the OpenRouter model list. You can also pass the model per run:

```powershell
sql-agent ask "How many customers do we have?" --provider openrouter --model openai/gpt-5.4-mini
```

`OPENROUTER_SITE_URL` and `OPENROUTER_APP_NAME` are optional attribution headers.

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
