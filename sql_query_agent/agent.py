from __future__ import annotations

import ast
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from .db import get_schema as inspect_schema
from .db import get_table_names
from .db import query_database as execute_query


_VALID_MODEL_PROVIDERS = {"openai", "local"}
_DEFAULT_LOCAL_MODEL_BASE_URL = "http://localhost:1234/v1"
_DEFAULT_LOCAL_MODEL_API_KEY = "local"


@dataclass(frozen=True)
class AgentConfig:
    db_path: Path
    model: str
    provider: str = "openai"
    base_url: str | None = None
    api_key: str | None = None
    max_rows: int = 100
    show_sql: bool = False
    show_table: bool = False


@dataclass(frozen=True)
class AgentAnswer:
    answer: str
    sql_queries: list[str] = field(default_factory=list)
    query_results: list[dict[str, Any]] = field(default_factory=list)


def config_from_env(
    db_path: str | Path | None = None,
    model: str | None = None,
    provider: str | None = None,
    base_url: str | None = None,
    max_rows: int | None = None,
    show_sql: bool = False,
    show_table: bool = False,
) -> AgentConfig:
    # Load repo-local settings before reading environment variables. CLI arguments
    # still take precedence because they are passed into this function directly.
    load_dotenv(dotenv_path=Path.cwd() / ".env")

    # Database path precedence: explicit CLI value, legacy env var, documented
    # env var, then the sample database path.
    resolved_db_path = Path(
        db_path
        or os.environ.get("SQL_AGENT_DB_PATH")
        or os.environ.get("DATABASE_FILE")
        or "./data/sample.db"
    )

    resolved_provider = (provider or os.environ.get("SQL_AGENT_MODEL_PROVIDER") or "openai").strip().lower()
    if resolved_provider not in _VALID_MODEL_PROVIDERS:
        raise RuntimeError("Model provider must be 'openai' or 'local'.")

    if resolved_provider == "local":
        resolved_base_url = _normalize_base_url(
            base_url or os.environ.get("LOCAL_MODEL_BASE_URL") or _DEFAULT_LOCAL_MODEL_BASE_URL
        )
        resolved_api_key = os.environ.get("LOCAL_MODEL_API_KEY") or _DEFAULT_LOCAL_MODEL_API_KEY
        resolved_model = model or os.environ.get("LOCAL_MODEL_NAME") or _detect_local_model(
            resolved_base_url,
            resolved_api_key,
        )
    else:
        resolved_base_url = _normalize_base_url(base_url or os.environ.get("OPENAI_BASE_URL"))
        resolved_model = model or os.environ.get("OPENAI_MODEL")
        if not resolved_model:
            raise RuntimeError("OPENAI_MODEL must be set or passed with --model.")

        resolved_api_key = os.environ.get("OPENAI_API_KEY")
        if not resolved_api_key:
            raise RuntimeError("OPENAI_API_KEY must be set before using the OpenAI provider.")

    resolved_max_rows = max_rows
    if resolved_max_rows is None:
        resolved_max_rows = int(os.environ.get("SQL_AGENT_MAX_ROWS", "100"))

    return AgentConfig(
        db_path=resolved_db_path,
        model=resolved_model,
        provider=resolved_provider,
        base_url=resolved_base_url,
        api_key=resolved_api_key,
        max_rows=max(1, resolved_max_rows),
        show_sql=show_sql,
        show_table=show_table,
    )


def build_agent(config: AgentConfig):
    # Keep LangGraph/OpenAI imports lazy so tests for config and database safety
    # do not need model packages to initialize clients at import time.
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent

    # These are the only model-visible tools. The database module enforces
    # read-only SQL validation before anything reaches SQLite.
    tools = _make_tools(config)
    model = ChatOpenAI(**_chat_model_kwargs(config))
    prompt = _system_prompt(config)

    try:
        # Newer LangGraph versions accept the system prompt through `prompt`.
        return create_react_agent(model, tools=tools, prompt=prompt)
    except TypeError:
        # Older versions used `state_modifier`; keep this fallback small so the
        # app remains usable across nearby LangGraph releases.
        return create_react_agent(model, tools=tools, state_modifier=prompt)


def ask(question: str, config: AgentConfig) -> AgentAnswer:
    agent = build_agent(config)
    result = agent.invoke(
        {"messages": [{"role": "user", "content": question}]},
        config=_runnable_config(config, run_name="sql-agent ask"),
    )
    return _answer_from_result(result)


def run_chat(config: AgentConfig) -> None:
    agent = build_agent(config)
    # Chat history is intentionally process-local. The MVP has no persistent
    # memory, database writes, or multi-user session store.
    messages: list[dict[str, str]] = []
    session_id = str(uuid.uuid4())
    turn_number = 0

    print("SQL Query Agent. Type 'exit' or 'quit' to end.")
    while True:
        try:
            question = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if not question:
            continue
        if question.lower() in {"exit", "quit"}:
            return

        messages.append({"role": "user", "content": question})
        turn_number += 1
        result = agent.invoke(
            {"messages": messages},
            config=_runnable_config(
                config,
                run_name="sql-agent chat",
                metadata={"chat_session_id": session_id, "turn": turn_number},
            ),
        )
        answer = _answer_from_result(result)
        print(answer.answer)
        if config.show_sql and answer.sql_queries:
            for sql in answer.sql_queries:
                print(f"SQL: {sql}")
        if config.show_table and answer.query_results:
            from .cli import print_query_result_tables

            print_query_result_tables(answer.query_results)
        messages = result.get("messages", messages)


def _make_tools(config: AgentConfig):
    # Tool closures bind the selected DB path and row cap for this run, while
    # exposing simple function signatures to the ReAct agent.
    def get_schema(table_names: list[str] | None = None) -> dict[str, Any]:
        """Return SQLite tables, columns, primary keys, and foreign keys."""
        return inspect_schema(config.db_path, table_names)

    def query_database(sql: str) -> dict[str, Any]:
        """Execute one read-only SQLite SELECT or WITH query and return rows."""
        return execute_query(config.db_path, sql, max_rows=config.max_rows)

    return [get_schema, query_database]


def _system_prompt(config: AgentConfig) -> str:
    # The prompt gives the model the decision policy; the query tool still
    # enforces read-only behavior independently as a runtime safety layer.
    table_context = _table_context(config)
    return f"""
You are a CLI SQL database assistant.
Today is {date.today().isoformat()}.

{table_context}

Answer directly when the user's question does not require database access.
Use get_schema when table or column information is unclear.
Use query_database when data retrieval is required.
Generate only one read-only SQLite SELECT or WITH query at a time.
Never attempt INSERT, UPDATE, DELETE, DROP, ALTER, PRAGMA, or any write/admin operation.
Base database answers only on query results returned by query_database.
If a tool returns an error, explain what could not be completed and why.
If results are truncated at {config.max_rows} rows, say that the answer is based on the returned rows.
Keep final answers concise and natural.
""".strip()


def _table_context(config: AgentConfig) -> str:
    # Give the model only table names at startup. Column names, types, keys, and
    # relationships stay out of the prompt until the model explicitly calls
    # get_schema for the relevant database details.
    result = get_table_names(config.db_path)
    if result["error"]:
        return f"Available database tables could not be loaded: {result['error']}"
    if not result["tables"]:
        return "Available database tables: none found."
    return "Available database tables: " + ", ".join(result["tables"]) + "."


def _runnable_config(
    config: AgentConfig,
    run_name: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # LangSmith reads LANGSMITH_* settings from the environment. This config
    # adds searchable context to each trace without exposing credentials.
    trace_metadata: dict[str, Any] = {
        "database_file": str(config.db_path),
        "provider": config.provider,
        "model": config.model,
        "max_rows": config.max_rows,
        **(metadata or {}),
    }
    if config.base_url:
        trace_metadata["base_url"] = config.base_url

    return {
        "run_name": run_name,
        "tags": ["sql-query-agent", "cli", "sqlite"],
        "metadata": trace_metadata,
    }


def _answer_from_result(result: dict[str, Any]) -> AgentAnswer:
    # LangGraph returns the full message trace. The final message is the answer,
    # while earlier AI messages may contain tool calls with generated SQL.
    messages = result.get("messages", [])
    if not messages:
        return AgentAnswer(answer="")

    sql_queries = _extract_sql_queries(messages)
    query_results = _extract_query_results(messages)
    last_message = messages[-1]
    content = getattr(last_message, "content", None)
    if content is None and isinstance(last_message, dict):
        content = last_message.get("content", "")

    if isinstance(content, list):
        content = "\n".join(str(part) for part in content)

    return AgentAnswer(
        answer=str(content or ""),
        sql_queries=sql_queries,
        query_results=query_results,
    )


def _chat_model_kwargs(config: AgentConfig) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": config.model,
        "temperature": 0,
    }
    if config.base_url:
        kwargs["base_url"] = config.base_url
    if config.api_key:
        kwargs["api_key"] = config.api_key
    return kwargs


def _normalize_base_url(base_url: str | None) -> str | None:
    if not base_url:
        return None
    return base_url.rstrip("/")


def _detect_local_model(base_url: str, api_key: str) -> str:
    endpoint = f"{base_url}/models"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        with urlopen(Request(endpoint, headers=headers), timeout=5) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(_local_model_detection_error(endpoint, f"HTTP {exc.code}")) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(_local_model_detection_error(endpoint, str(exc))) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(_local_model_detection_error(endpoint, "response was not valid JSON")) from exc

    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]:
                return item["id"]
            if isinstance(item, str) and item:
                return item

    raise RuntimeError(
        f"No local models were returned by {endpoint}. "
        "Start your OpenAI-compatible local model server, load a tool-capable model, "
        "or set LOCAL_MODEL_NAME/--model."
    )


def _local_model_detection_error(endpoint: str, detail: str) -> str:
    return (
        f"Could not auto-detect a local model from {endpoint}. "
        "Start your OpenAI-compatible local model server or set LOCAL_MODEL_NAME/--model. "
        f"Details: {detail}"
    )


def _extract_sql_queries(messages: list[Any]) -> list[str]:
    # Messages can be LangChain objects or plain dicts depending on the caller
    # and version, so handle both shapes when collecting SQL for --show-sql.
    queries: list[str] = []
    for message in messages:
        tool_calls = getattr(message, "tool_calls", None)
        if not tool_calls and isinstance(message, dict):
            tool_calls = message.get("tool_calls")
        for tool_call in tool_calls or []:
            name = tool_call.get("name") if isinstance(tool_call, dict) else getattr(tool_call, "name", None)
            if name != "query_database":
                continue
            args = tool_call.get("args") if isinstance(tool_call, dict) else getattr(tool_call, "args", {})
            if isinstance(args, dict) and isinstance(args.get("sql"), str):
                queries.append(args["sql"])
    return queries


def _extract_query_results(messages: list[Any]) -> list[dict[str, Any]]:
    # Query result payloads come back through ToolMessage objects in live runs,
    # but tests and nearby LangChain versions may expose plain dicts instead.
    results: list[dict[str, Any]] = []
    for message in messages:
        name = _message_name(message)
        if name not in {None, "query_database"}:
            continue

        payload = _query_result_payload(message)
        if payload is not None:
            results.append(payload)
    return results


def _message_name(message: Any) -> str | None:
    if isinstance(message, dict):
        return message.get("name")
    return getattr(message, "name", None)


def _query_result_payload(message: Any) -> dict[str, Any] | None:
    candidates: list[Any] = []
    if isinstance(message, dict):
        candidates.extend([message.get("content"), message.get("artifact")])
    else:
        candidates.extend([getattr(message, "content", None), getattr(message, "artifact", None)])

    for candidate in candidates:
        parsed = _parse_tool_payload(candidate)
        if _is_query_result(parsed):
            return parsed
    return None


def _parse_tool_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        if "text" in payload:
            return _parse_tool_payload(payload["text"])
        if "json" in payload:
            return _parse_tool_payload(payload["json"])
        return payload
    if isinstance(payload, list):
        for item in payload:
            parsed = _parse_tool_payload(item)
            if _is_query_result(parsed):
                return parsed
        return None
    if not isinstance(payload, str):
        return None

    text = payload.strip()
    if not text:
        return None

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    try:
        return ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return None


def _is_query_result(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and isinstance(payload.get("columns"), list)
        and isinstance(payload.get("rows"), list)
        and "sql" in payload
        and "error" in payload
    )
