"""Agent orchestration for the SQL Query Agent CLI.

This module connects configuration, model setup, LangGraph tool calling,
answer extraction, optional CLI debug output, and persistent markdown memory.
The database safety checks live in ``db.py``; this file decides when and how
the model can call those database helpers.
"""

from __future__ import annotations

import ast
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from .db import get_schema as inspect_schema
from .db import get_table_names
from .db import query_database as execute_query


# Supported model backends and provider-specific defaults used while building
# the OpenAI-compatible chat client.
_VALID_MODEL_PROVIDERS = {"openai", "local", "openrouter"}
_DEFAULT_LOCAL_MODEL_BASE_URL = "http://localhost:1234/v1"
_DEFAULT_LOCAL_MODEL_API_KEY = "local"
_DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_MEMORY_HEADER = "# SQL Agent Memory\n\nShort reusable notes about this database for future SQL queries.\n"


@dataclass(frozen=True)
class AgentConfig:
    # One immutable object carries all runtime settings from the CLI/.env into
    # the agent, tools, tracing metadata, and memory helpers.
    db_path: Path
    model: str
    provider: str = "openrouter"
    base_url: str | None = None
    api_key: str | None = None
    default_headers: dict[str, str] = field(default_factory=dict)
    max_rows: int = 100
    show_sql: bool = False
    show_table: bool = False
    memory_enabled: bool = True
    memory_path: Path | None = None
    audit_log_path: Path | None = None


@dataclass(frozen=True)
class AgentAnswer:
    # Normalized agent output returned to the CLI. The raw LangGraph result
    # contains many messages, but callers only need the final answer plus any
    # SQL/query data used for display or memory decisions.
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
    memory_enabled: bool | None = None,
    memory_file: str | Path | None = None,
    audit_log_file: str | Path | None = None,
) -> AgentConfig:
    # Load repo-local settings before reading environment variables. CLI arguments
    # still take precedence because they are passed into this function directly.
    load_dotenv(dotenv_path=Path.cwd() / ".env")

    # Database path precedence: explicit CLI value, documented env var, legacy
    # compatibility env var, then the sample database path.
    resolved_db_path = Path(
        db_path
        or os.environ.get("DATABASE_FILE")
        or os.environ.get("SQL_AGENT_DB_PATH")
        or "./data/sample.db"
    )

    resolved_provider = (provider or os.environ.get("SQL_AGENT_MODEL_PROVIDER") or "openrouter").strip().lower()
    if resolved_provider not in _VALID_MODEL_PROVIDERS:
        raise RuntimeError("Model provider must be 'openai', 'local', or 'openrouter'.")

    # Provider selection determines which API key, base URL, model name, and
    # optional default headers are passed to ChatOpenAI later.
    if resolved_provider == "local":
        # Local providers are OpenAI-compatible servers. If no model is set, ask
        # the server for /models and use the first advertised model id.
        resolved_base_url = _normalize_base_url(
            base_url or os.environ.get("LOCAL_MODEL_BASE_URL") or _DEFAULT_LOCAL_MODEL_BASE_URL
        )
        resolved_api_key = os.environ.get("LOCAL_MODEL_API_KEY") or _DEFAULT_LOCAL_MODEL_API_KEY
        resolved_model = model or os.environ.get("LOCAL_MODEL_NAME") or _detect_local_model(
            resolved_base_url,
            resolved_api_key,
        )
        resolved_default_headers: dict[str, str] = {}
    elif resolved_provider == "openrouter":
        # OpenRouter uses the OpenAI chat protocol plus optional attribution
        # headers, so it can still be driven through ChatOpenAI.
        resolved_base_url = _normalize_base_url(
            base_url or os.environ.get("OPENROUTER_BASE_URL") or _DEFAULT_OPENROUTER_BASE_URL
        )
        resolved_model = model or os.environ.get("OPENROUTER_MODEL")
        if not resolved_model:
            raise RuntimeError("OPENROUTER_MODEL must be set or passed with --model.")

        resolved_api_key = os.environ.get("OPENROUTER_API_KEY")
        if not resolved_api_key:
            raise RuntimeError("OPENROUTER_API_KEY must be set before using the OpenRouter provider.")

        resolved_default_headers = _openrouter_headers()
    else:
        # Native OpenAI keeps the default SDK endpoint unless OPENAI_BASE_URL or
        # --base-url is provided for a compatible proxy.
        resolved_base_url = _normalize_base_url(base_url or os.environ.get("OPENAI_BASE_URL"))
        resolved_model = model or os.environ.get("OPENAI_MODEL")
        if not resolved_model:
            raise RuntimeError("OPENAI_MODEL must be set or passed with --model.")

        resolved_api_key = os.environ.get("OPENAI_API_KEY")
        if not resolved_api_key:
            raise RuntimeError("OPENAI_API_KEY must be set before using the OpenAI provider.")
        resolved_default_headers = {}

    resolved_max_rows = max_rows
    if resolved_max_rows is None:
        resolved_max_rows = int(os.environ.get("SQL_AGENT_MAX_ROWS", "100"))

    # Memory can be disabled per run. When enabled, notes default to a markdown
    # sidecar next to the selected database file.
    resolved_memory_enabled = _resolve_bool(
        memory_enabled,
        os.environ.get("SQL_AGENT_MEMORY_ENABLED"),
        default=True,
    )
    resolved_memory_path = None
    if resolved_memory_enabled:
        configured_memory_file = memory_file or os.environ.get("SQL_AGENT_MEMORY_FILE")
        resolved_memory_path = (
            Path(configured_memory_file)
            if configured_memory_file
            else _default_memory_path(resolved_db_path)
        )

    configured_audit_log_file = audit_log_file or os.environ.get("SQL_AGENT_AUDIT_LOG_FILE")
    resolved_audit_log_path = Path(configured_audit_log_file) if configured_audit_log_file else None

    return AgentConfig(
        db_path=resolved_db_path,
        model=resolved_model,
        provider=resolved_provider,
        base_url=resolved_base_url,
        api_key=resolved_api_key,
        default_headers=resolved_default_headers,
        max_rows=max(1, resolved_max_rows),
        show_sql=show_sql,
        show_table=show_table,
        memory_enabled=resolved_memory_enabled,
        memory_path=resolved_memory_path,
        audit_log_path=resolved_audit_log_path,
    )


def build_agent(config: AgentConfig):
    # Build the LangGraph ReAct agent that can decide between answering
    # directly, inspecting schema, and running a read-only SQL query.
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
    # One-shot mode builds an agent, sends a single user message, normalizes the
    # LangGraph output, then optionally updates persistent memory.
    agent = build_agent(config)
    result = agent.invoke(
        {"messages": [{"role": "user", "content": question}]},
        config=_runnable_config(config, run_name="sql-agent ask"),
    )
    answer = _answer_from_result(result)
    _remember_after_answer(question, answer, config)
    return answer


def run_chat(config: AgentConfig) -> None:
    # Interactive mode keeps the conversation messages in memory so follow-up
    # questions can refer to previous turns during the same terminal session.
    # Chat history is process-local. Persistent database notes are stored
    # separately in markdown and loaded into each turn's system prompt.
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

        # Rebuild the agent each turn so prompt context can include any memory
        # note written after a previous database-backed answer.
        messages.append({"role": "user", "content": question})
        turn_number += 1
        print()
        agent = build_agent(config)
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
        print()
        _remember_after_answer(question, answer, config)
        messages = result.get("messages", messages)


def _make_tools(config: AgentConfig):
    # Tool closures bind the selected DB path and row cap for this run, while
    # exposing simple function signatures to the ReAct agent.
    def get_schema(table_names: list[str] | None = None) -> dict[str, Any]:
        """Return SQLite tables, columns, primary keys, and foreign keys."""
        return inspect_schema(config.db_path, table_names)

    def query_database(sql: str) -> dict[str, Any]:
        """Execute one read-only SQLite SELECT or WITH query and return rows."""
        started_at = time.perf_counter()
        result = execute_query(config.db_path, sql, max_rows=config.max_rows)
        duration_ms = (time.perf_counter() - started_at) * 1000
        _write_query_audit_event(sql, result, duration_ms, config)
        _print_intermediate_query_output(sql, result, config)
        return result

    return [get_schema, query_database]


def _write_query_audit_event(
    sql: str,
    result: dict[str, Any],
    duration_ms: float,
    config: AgentConfig,
) -> None:
    if config.audit_log_path is None:
        return

    event = {
        "event": "query_database",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database_file": str(config.db_path),
        "provider": config.provider,
        "model": config.model,
        "max_rows": config.max_rows,
        "sql": sql,
        "duration_ms": round(duration_ms, 3),
        "row_count": result.get("row_count", 0),
        "truncated": bool(result.get("truncated")),
        "status": "error" if result.get("error") else "ok",
        "error_type": result.get("error_type"),
        "error": result.get("error"),
    }
    _append_jsonl(config.audit_log_path, event)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, default=str, ensure_ascii=False) + "\n")


def _print_intermediate_query_output(sql: str, result: dict[str, Any], config: AgentConfig) -> None:
    # When --show-sql or --show-table is active, print the tool output as soon
    # as the query runs instead of waiting for final answer extraction.
    if not config.show_sql and not config.show_table:
        return

    if config.show_sql:
        print(f"SQL: {sql}")

    if config.show_table:
        from .cli import print_query_result_tables

        if config.show_sql:
            print()
        print_query_result_tables([result])

    print()


def _system_prompt(config: AgentConfig) -> str:
    # The prompt gives the model the decision policy; the query tool still
    # enforces read-only behavior independently as a runtime safety layer.
    context_sections = [_table_context(config)]
    memory_context = _memory_context(config)
    if memory_context:
        context_sections.append(memory_context)
    context = "\n\n".join(context_sections)
    return f"""
You are a CLI SQL database assistant.
Today is {date.today().isoformat()}.

{context}

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


def _memory_context(config: AgentConfig) -> str:
    # Memory is loaded into the system prompt as plain markdown context. If the
    # file is missing or unreadable, the agent simply runs without it.
    memory = _read_memory(config)
    if not memory:
        return ""

    memory_path = _resolved_memory_path(config)
    location = f" from {memory_path}" if memory_path else ""
    return f"Persistent database notes{location}:\n{memory}"


def _read_memory(config: AgentConfig) -> str:
    # Keep memory reads best-effort because the query answer should not fail due
    # to a missing, locked, or temporarily unreadable notes file.
    memory_path = _resolved_memory_path(config)
    if memory_path is None or not memory_path.exists():
        return ""

    try:
        return memory_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _remember_after_answer(question: str, answer: AgentAnswer, config: AgentConfig) -> None:
    try:
        _maybe_update_memory(question, answer, config)
    except Exception:
        # Persistent memory is helpful context, not part of answer delivery.
        return


def _maybe_update_memory(question: str, answer: AgentAnswer, config: AgentConfig) -> None:
    # Only successful database-backed answers can produce new memory. Direct
    # answers and failed queries do not contain reusable database knowledge.
    memory_path = _resolved_memory_path(config)
    if memory_path is None or not _has_successful_query_result(answer):
        return

    # Ask the same configured model for exactly one reusable markdown note, then
    # normalize and dedupe it before writing to disk.
    existing_memory = _read_memory(config)
    note = _normalize_memory_note(
        _generate_memory_note(question, answer, existing_memory, config)
    )
    if not note or _memory_has_note(existing_memory, note):
        return

    _append_memory_note(memory_path, note)


def _has_successful_query_result(answer: AgentAnswer) -> bool:
    return any(
        result.get("error") is None and isinstance(result.get("sql"), str)
        for result in answer.query_results
    )


def _generate_memory_note(
    question: str,
    answer: AgentAnswer,
    existing_memory: str,
    config: AgentConfig,
) -> str:
    # This second model call is intentionally small: it sees the existing notes,
    # the recent question/answer, generated SQL, and a short query-result sample.
    from langchain_openai import ChatOpenAI

    model = ChatOpenAI(**_chat_model_kwargs(config))
    payload = {
        "question": question,
        "answer": answer.answer,
        "sql_queries": answer.sql_queries,
        "query_results": [
            _memory_query_summary(result)
            for result in answer.query_results
            if result.get("error") is None
        ],
    }
    response = model.invoke(
        [
            {
                "role": "system",
                "content": _memory_decision_prompt(),
            },
            {
                "role": "user",
                "content": (
                    "Existing memory:\n"
                    f"{existing_memory or '(none)'}\n\n"
                    "Recent database-backed interaction:\n"
                    f"{json.dumps(payload, indent=2, default=str)}"
                ),
            },
        ],
        config=_runnable_config(config, run_name="sql-agent memory"),
    )
    return _message_content_to_text(response)


def _memory_decision_prompt() -> str:
    return """
You decide whether a SQL assistant should append one persistent markdown note.
Write a note only if it may help generate future SQL for this same database.
Useful notes include table relationships, business term mappings, useful joins, date/status semantics, or reusable metric definitions.
Do not write one-off answers, raw counts, secrets, personal data, failed-query details, or notes that duplicate existing memory.
Respond with exactly one short markdown bullet beginning with "- ", or respond with "NONE".
""".strip()


def _memory_query_summary(result: dict[str, Any]) -> dict[str, Any]:
    rows = result.get("rows")
    sample_rows = rows[:3] if isinstance(rows, list) else []
    return {
        "sql": result.get("sql"),
        "columns": result.get("columns", []),
        "row_count": result.get("row_count"),
        "truncated": result.get("truncated"),
        "sample_rows": sample_rows,
    }


def _message_content_to_text(message: Any) -> str:
    # LangChain message content can be a string, a list of content blocks, or a
    # dict-like test double. Convert those shapes into plain text.
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content", "")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content or "")


def _normalize_memory_note(note: str | None) -> str | None:
    # Accept the model's first meaningful line, convert it to a markdown bullet,
    # and cap the length so memory remains concise over time.
    if not note:
        return None

    for raw_line in note.strip().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.casefold() in {"none", "no note", "no memory"}:
            return None
        if line.startswith(("-", "*")):
            line = line.lstrip("-* ").strip()
        if not line:
            return None
        normalized = f"- {line}"
        if len(normalized) > 300:
            normalized = normalized[:297].rstrip() + "..."
        return normalized
    return None


def _memory_has_note(existing_memory: str, note: str) -> bool:
    target = note.casefold()
    for line in existing_memory.splitlines():
        existing_note = _normalize_memory_note(line)
        if existing_note and existing_note.casefold() == target:
            return True
    return False


def _append_memory_note(memory_path: Path, note: str) -> None:
    # Create the sidecar file on first write and preserve any existing notes.
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = memory_path.read_text(encoding="utf-8") if memory_path.exists() else ""
    except OSError:
        existing = ""

    content = existing if existing.strip() else _MEMORY_HEADER
    if not content.endswith("\n"):
        content += "\n"
    memory_path.write_text(content + note + "\n", encoding="utf-8")


def _resolved_memory_path(config: AgentConfig) -> Path | None:
    if not config.memory_enabled:
        return None
    return config.memory_path or _default_memory_path(config.db_path)


def _default_memory_path(db_path: str | Path) -> Path:
    path = Path(db_path)
    if path.suffix:
        return path.with_suffix(".memory.md")
    return path.with_name(f"{path.name}.memory.md")


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
    # ChatOpenAI accepts OpenAI, OpenRouter, and local OpenAI-compatible server
    # settings through the same keyword arguments.
    kwargs: dict[str, Any] = {
        "model": config.model,
        "temperature": 0,
    }
    if config.base_url:
        kwargs["base_url"] = config.base_url
    if config.api_key:
        kwargs["api_key"] = config.api_key
    if config.default_headers:
        kwargs["default_headers"] = config.default_headers
    return kwargs


def _normalize_base_url(base_url: str | None) -> str | None:
    if not base_url:
        return None
    return base_url.rstrip("/")


def _openrouter_headers() -> dict[str, str]:
    # OpenRouter accepts optional attribution headers; omit empty values so local
    # development does not send placeholder metadata.
    headers: dict[str, str] = {}
    site_url = os.environ.get("OPENROUTER_SITE_URL")
    app_name = os.environ.get("OPENROUTER_APP_NAME")
    if site_url:
        headers["HTTP-Referer"] = site_url
    if app_name:
        headers["X-Title"] = app_name
    return headers


def _resolve_bool(value: bool | None, env_value: str | None, default: bool) -> bool:
    # CLI flags pass real booleans. Environment variables arrive as strings, so
    # accept common truthy/falsy spellings and fail loudly on typos.
    if value is not None:
        return value
    if env_value is None or not env_value.strip():
        return default

    normalized = env_value.strip().casefold()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise RuntimeError("SQL_AGENT_MEMORY_ENABLED must be true or false.")


def _detect_local_model(base_url: str, api_key: str) -> str:
    # Local model servers may expose different loaded model ids. Probe /models
    # only when the user did not configure a model explicitly.
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
