from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .db import get_schema as inspect_schema
from .db import query_database as execute_query


@dataclass(frozen=True)
class AgentConfig:
    db_path: Path
    model: str
    max_rows: int = 100
    show_sql: bool = False


@dataclass(frozen=True)
class AgentAnswer:
    answer: str
    sql_queries: list[str] = field(default_factory=list)


def config_from_env(
    db_path: str | Path | None = None,
    model: str | None = None,
    max_rows: int | None = None,
    show_sql: bool = False,
) -> AgentConfig:
    load_dotenv(dotenv_path=Path.cwd() / ".env")

    resolved_db_path = Path(
        db_path
        or os.environ.get("SQL_AGENT_DB_PATH")
        or os.environ.get("DATABASE_FILE")
        or "./data/sample.db"
    )
    resolved_model = model or os.environ.get("OPENAI_MODEL")
    if not resolved_model:
        raise RuntimeError("OPENAI_MODEL must be set or passed with --model.")

    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY must be set before using the agent.")

    resolved_max_rows = max_rows
    if resolved_max_rows is None:
        resolved_max_rows = int(os.environ.get("SQL_AGENT_MAX_ROWS", "100"))

    return AgentConfig(
        db_path=resolved_db_path,
        model=resolved_model,
        max_rows=max(1, resolved_max_rows),
        show_sql=show_sql,
    )


def build_agent(config: AgentConfig):
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent

    tools = _make_tools(config)
    model = ChatOpenAI(model=config.model, temperature=0)
    prompt = _system_prompt(config)

    try:
        return create_react_agent(model, tools=tools, prompt=prompt)
    except TypeError:
        return create_react_agent(model, tools=tools, state_modifier=prompt)


def ask(question: str, config: AgentConfig) -> AgentAnswer:
    agent = build_agent(config)
    result = agent.invoke({"messages": [{"role": "user", "content": question}]})
    return _answer_from_result(result)


def run_chat(config: AgentConfig) -> None:
    agent = build_agent(config)
    messages: list[dict[str, str]] = []

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
        result = agent.invoke({"messages": messages})
        answer = _answer_from_result(result)
        print(answer.answer)
        if config.show_sql and answer.sql_queries:
            for sql in answer.sql_queries:
                print(f"SQL: {sql}")
        messages = result.get("messages", messages)


def _make_tools(config: AgentConfig):
    def get_schema(table_names: list[str] | None = None) -> dict[str, Any]:
        """Return SQLite tables, columns, primary keys, and foreign keys."""
        return inspect_schema(config.db_path, table_names)

    def query_database(sql: str) -> dict[str, Any]:
        """Execute one read-only SQLite SELECT or WITH query and return rows."""
        return execute_query(config.db_path, sql, max_rows=config.max_rows)

    return [get_schema, query_database]


def _system_prompt(config: AgentConfig) -> str:
    return f"""
You are a CLI SQL database assistant.
Today is {date.today().isoformat()}.

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


def _answer_from_result(result: dict[str, Any]) -> AgentAnswer:
    messages = result.get("messages", [])
    if not messages:
        return AgentAnswer(answer="")

    sql_queries = _extract_sql_queries(messages)
    last_message = messages[-1]
    content = getattr(last_message, "content", None)
    if content is None and isinstance(last_message, dict):
        content = last_message.get("content", "")

    if isinstance(content, list):
        content = "\n".join(str(part) for part in content)

    return AgentAnswer(answer=str(content or ""), sql_queries=sql_queries)


def _extract_sql_queries(messages: list[Any]) -> list[str]:
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
