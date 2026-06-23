"""Planner/orchestrator chat for goal-directed database work."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from . import agent as sql_agent
from .agent import AgentConfig, ModelSettings, model_settings_from_env


_DEFAULT_PLANNER_MAX_STEPS = 25


@dataclass(frozen=True)
class PlannerConfig:
    # The planner has its own chat model but can only access data by calling the
    # original SQL agent through a tool bound to this SQL runtime config.
    sql_config: AgentConfig
    model: str
    provider: str = "openrouter"
    base_url: str | None = None
    api_key: str | None = None
    default_headers: dict[str, str] = field(default_factory=dict)
    max_steps: int = _DEFAULT_PLANNER_MAX_STEPS
    show_steps: bool = False


def planner_config_from_env(
    sql_config: AgentConfig,
    planner_model: str | None = None,
    planner_provider: str | None = None,
    planner_base_url: str | None = None,
    max_steps: int | None = None,
    show_steps: bool = False,
) -> PlannerConfig:
    # Load repo-local settings here too so tests and direct planner imports do
    # not have to rely on the CLI calling agent.config_from_env first.
    load_dotenv(dotenv_path=Path.cwd() / ".env")

    model_settings = model_settings_from_env(
        provider=planner_provider,
        model=planner_model,
        base_url=planner_base_url,
        provider_env_var="SQL_PLANNER_MODEL_PROVIDER",
        model_env_var="SQL_PLANNER_MODEL",
        base_url_env_var="SQL_PLANNER_BASE_URL",
        fallback=ModelSettings(
            model=sql_config.model,
            provider=sql_config.provider,
            base_url=sql_config.base_url,
            api_key=sql_config.api_key,
            default_headers=sql_config.default_headers,
        ),
    )
    resolved_max_steps = max_steps
    if resolved_max_steps is None:
        resolved_max_steps = int(
            os.environ.get("SQL_PLANNER_MAX_STEPS", str(_DEFAULT_PLANNER_MAX_STEPS))
        )

    return PlannerConfig(
        sql_config=sql_config,
        model=model_settings.model,
        provider=model_settings.provider,
        base_url=model_settings.base_url,
        api_key=model_settings.api_key,
        default_headers=model_settings.default_headers,
        max_steps=max(1, resolved_max_steps),
        show_steps=show_steps,
    )


def build_planner_agent(
    config: PlannerConfig,
    session_id: str = "",
    turn_number: int = 0,
):
    # Keep imports lazy for the same reason as the direct SQL agent: config,
    # parser, and pure unit tests should not initialize LangChain clients.
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent

    tools = _make_tools(config, session_id=session_id, turn_number=turn_number)
    model = ChatOpenAI(**_planner_model_kwargs(config))
    prompt = _system_prompt(config)

    try:
        return create_react_agent(model, tools=tools, prompt=prompt)
    except TypeError:
        return create_react_agent(model, tools=tools, state_modifier=prompt)


def run_plan_chat(config: PlannerConfig) -> None:
    # The planner keeps high-level chat history, but each SQL-agent tool call is
    # a fresh one-shot request so the original agent remains the data boundary.
    messages: list[dict[str, str]] = []
    session_id = str(uuid.uuid4())
    turn_number = 0

    print("SQL Planner Orchestrator. Type 'exit' or 'quit' to end.")
    while True:
        try:
            goal = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if not goal:
            continue
        if goal.lower() in {"exit", "quit"}:
            return

        messages.append({"role": "user", "content": goal})
        turn_number += 1
        print()

        planner = build_planner_agent(config, session_id=session_id, turn_number=turn_number)
        result = planner.invoke(
            {"messages": messages},
            config=_planner_runnable_config(
                config,
                run_name="sql-agent planner chat",
                metadata={
                    "planner_session_id": session_id,
                    "planner_turn": turn_number,
                },
            ),
        )
        print(_answer_from_result(result))
        print()
        messages = result.get("messages", messages)


def _make_tools(
    config: PlannerConfig,
    session_id: str = "",
    turn_number: int = 0,
):
    call_count = 0

    def ask_sql_agent(question: str) -> dict[str, Any]:
        """Ask the SQL agent one focused database question and return its answer."""
        nonlocal call_count
        attempted_call_number = call_count + 1
        if call_count >= config.max_steps:
            return {
                "question": question,
                "call_number": attempted_call_number,
                "max_steps": config.max_steps,
                "error": (
                    f"Planner SQL-agent call limit reached ({config.max_steps}). "
                    "Summarize partial progress or ask the user to narrow the goal."
                ),
            }

        call_count = attempted_call_number
        if config.show_steps:
            print(f"Planner step {call_count}: {question}")

        answer = sql_agent.ask(
            question,
            config.sql_config,
            run_name="sql-agent planner sql-tool",
            metadata={
                "planner_session_id": session_id,
                "planner_turn": turn_number,
                "planner_sql_call": call_count,
            },
        )
        payload = {
            "question": question,
            "call_number": call_count,
            "answer": answer.answer,
            "sql_queries": answer.sql_queries,
            "query_results": answer.query_results,
            "error": None,
        }

        if config.show_steps:
            print(f"Planner step {call_count} answer: {answer.answer}")
            print()

        return payload

    return [ask_sql_agent]


def _system_prompt(config: PlannerConfig) -> str:
    return f"""
You are a planner/orchestrator agent for a CLI SQL database assistant.
Today is {date.today().isoformat()}.

The user gives you a goal. Break that goal into the database facts and analysis needed to achieve it.
Use ask_sql_agent as your only source for database facts.
Do not write SQL yourself and do not claim database facts that were not returned by ask_sql_agent.
Call ask_sql_agent with one focused natural-language database question at a time.
The SQL agent owns schema lookup, read-only SQL generation, query execution, row limits, and database memory.
If an answer is incomplete, ask a narrower or follow-up database question.
Stop when the goal is achieved, impossible with the available data, or the SQL-agent call limit is reached.
You may call ask_sql_agent up to {config.max_steps} times for this user goal.
If the tool reports a call-limit error, summarize partial progress and explain what remains unknown.
Final answers should be concise, actionable, and explicit about data limitations.
""".strip()


def _planner_model_kwargs(config: PlannerConfig) -> dict[str, Any]:
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


def _planner_runnable_config(
    config: PlannerConfig,
    run_name: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trace_metadata: dict[str, Any] = {
        "database_file": str(config.sql_config.db_path),
        "sql_provider": config.sql_config.provider,
        "sql_model": config.sql_config.model,
        "planner_provider": config.provider,
        "planner_model": config.model,
        "max_rows": config.sql_config.max_rows,
        "planner_max_steps": config.max_steps,
        **(metadata or {}),
    }
    if config.sql_config.base_url:
        trace_metadata["sql_base_url"] = config.sql_config.base_url
    if config.base_url:
        trace_metadata["planner_base_url"] = config.base_url

    return {
        "run_name": run_name,
        "tags": ["sql-query-agent", "planner", "cli", "sqlite"],
        "metadata": trace_metadata,
        "recursion_limit": max(50, config.max_steps * 3 + 10),
    }


def _answer_from_result(result: dict[str, Any]) -> str:
    messages = result.get("messages", [])
    if not messages:
        return ""

    last_message = messages[-1]
    content = getattr(last_message, "content", None)
    if content is None and isinstance(last_message, dict):
        content = last_message.get("content", "")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    if isinstance(content, (dict, list)):
        return json.dumps(content, indent=2, default=str)
    return str(content or "")
