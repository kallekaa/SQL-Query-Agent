from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from .sample_data import init_sample_database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sql-agent",
        description="Ask natural-language questions about a SQLite database.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-sample", help="Create the sample SQLite database.")
    init_parser.add_argument("--db", default="./data/sample.db", help="SQLite database path to create.")
    init_parser.add_argument("--overwrite", action="store_true", help="Replace the database if it exists.")

    ask_parser = subparsers.add_parser("ask", help="Ask one question and print the answer.")
    ask_parser.add_argument("question", help="Natural-language question.")
    _add_agent_options(ask_parser)

    chat_parser = subparsers.add_parser("chat", help="Start an interactive session.")
    _add_agent_options(chat_parser)

    ui_parser = subparsers.add_parser("ui", help="Start a lightweight browser UI.")
    _add_agent_options(ui_parser)
    ui_parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind.")
    ui_parser.add_argument("--port", type=int, default=8000, help="Port to bind.")
    ui_parser.add_argument(
        "--no-open",
        dest="open_browser",
        action="store_false",
        default=True,
        help="Do not open the browser automatically.",
    )

    plan_parser = subparsers.add_parser("plan", help="Start an interactive planner/orchestrator session.")
    _add_agent_options(plan_parser)
    _add_planner_options(plan_parser)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "init-sample":
            path = init_sample_database(args.db, overwrite=args.overwrite)
            print(f"Created sample database: {path}")
            return 0

        if args.command == "ask":
            from .agent import ask, config_from_env

            config = config_from_env(
                db_path=args.db,
                model=args.model,
                provider=args.provider,
                base_url=args.base_url,
                max_rows=args.max_rows,
                show_sql=args.show_sql,
                show_table=args.show_table,
                memory_enabled=args.memory_enabled,
                memory_file=args.memory_file,
                audit_log_file=args.audit_log_file,
            )
            answer = ask(args.question, config)
            print(answer.answer)
            return 0

        if args.command == "chat":
            from .agent import config_from_env, run_chat

            config = config_from_env(
                db_path=args.db,
                model=args.model,
                provider=args.provider,
                base_url=args.base_url,
                max_rows=args.max_rows,
                show_sql=args.show_sql,
                show_table=args.show_table,
                memory_enabled=args.memory_enabled,
                memory_file=args.memory_file,
                audit_log_file=args.audit_log_file,
            )
            run_chat(config)
            return 0

        if args.command == "ui":
            from .agent import config_from_env
            from .web_ui import run_ui

            config = config_from_env(
                db_path=args.db,
                model=args.model,
                provider=args.provider,
                base_url=args.base_url,
                max_rows=args.max_rows,
                show_sql=args.show_sql,
                show_table=args.show_table,
                memory_enabled=args.memory_enabled,
                memory_file=args.memory_file,
                audit_log_file=args.audit_log_file,
            )
            run_ui(config, host=args.host, port=args.port, open_browser=args.open_browser)
            return 0

        if args.command == "plan":
            from .agent import config_from_env
            from .planner import planner_config_from_env, run_plan_chat

            sql_config = config_from_env(
                db_path=args.db,
                model=args.model,
                provider=args.provider,
                base_url=args.base_url,
                max_rows=args.max_rows,
                show_sql=args.show_sql,
                show_table=args.show_table,
                memory_enabled=args.memory_enabled,
                memory_file=args.memory_file,
                audit_log_file=args.audit_log_file,
            )
            planner_config = planner_config_from_env(
                sql_config,
                planner_model=args.planner_model,
                planner_provider=args.planner_provider,
                planner_base_url=args.planner_base_url,
                max_steps=args.max_steps,
                show_steps=args.show_steps,
            )
            run_plan_chat(planner_config)
            return 0

        parser.error(f"Unknown command: {args.command}")
        return 2
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _add_agent_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db",
        default=None,
        help="SQLite database path. Defaults to DATABASE_FILE, then legacy SQL_AGENT_DB_PATH.",
    )
    parser.add_argument(
        "--provider",
        choices=["openai", "local", "openrouter"],
        default=None,
        help="Model provider. Defaults to SQL_AGENT_MODEL_PROVIDER, then openrouter.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Model name. Defaults to OPENAI_MODEL for OpenAI, OPENROUTER_MODEL "
            "for OpenRouter, or LOCAL_MODEL_NAME/local auto-detection."
        ),
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="OpenAI-compatible base URL. Overrides the selected provider's configured base URL.",
    )
    parser.add_argument("--max-rows", type=int, default=None, help="Maximum rows returned from a query.")
    parser.add_argument("--show-sql", action="store_true", help="Print SQL queries used by the agent.")
    parser.add_argument("--show-table", action="store_true", help="Print SQL query results as formatted tables.")
    parser.add_argument(
        "--memory-file",
        default=None,
        help="Markdown file for persistent database notes. Defaults to a sidecar next to --db.",
    )
    parser.add_argument(
        "--no-memory",
        dest="memory_enabled",
        action="store_false",
        default=None,
        help="Disable persistent markdown memory for this run.",
    )
    parser.add_argument(
        "--audit-log",
        dest="audit_log_file",
        default=None,
        help="Append query audit events as JSON Lines to this file.",
    )


def _add_planner_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--planner-provider",
        choices=["openai", "local", "openrouter"],
        default=None,
        help="Planner model provider. Defaults to SQL_PLANNER_MODEL_PROVIDER, then the SQL agent provider.",
    )
    parser.add_argument(
        "--planner-model",
        default=None,
        help="Planner model name. Defaults to SQL_PLANNER_MODEL, then the SQL agent model.",
    )
    parser.add_argument(
        "--planner-base-url",
        default=None,
        help="Planner OpenAI-compatible base URL. Defaults to SQL_PLANNER_BASE_URL, then the SQL agent base URL.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help="Maximum SQL-agent calls per planner turn. Defaults to SQL_PLANNER_MAX_STEPS or 25.",
    )
    parser.add_argument(
        "--show-steps",
        action="store_true",
        help="Print planner-to-SQL-agent call summaries during a planner run.",
    )


def print_query_result_tables(query_results: list[dict[str, Any]]) -> None:
    for index, result in enumerate(query_results, start=1):
        if len(query_results) > 1:
            print(f"Result table {index}:")
        print(format_query_result_table(result))


def format_query_result_table(result: dict[str, Any]) -> str:
    error = result.get("error")
    sql = result.get("sql")
    if error:
        return f"Query failed{f' for SQL: {sql}' if sql else ''}\n{error}"

    columns = [str(column) for column in result.get("columns", [])]
    rows = result.get("rows", [])
    if not columns:
        return "(no columns)"
    if not rows:
        return _format_empty_table(columns, bool(result.get("truncated")))

    table_rows = [
        ["" if row.get(column) is None else str(row.get(column)) for column in columns]
        for row in rows
        if isinstance(row, dict)
    ]
    widths = [
        max(len(column), *(len(row[index]) for row in table_rows))
        for index, column in enumerate(columns)
    ]

    border = _table_border(widths)
    header = _table_row(columns, widths)
    separator = _table_border(widths)
    body = [_table_row(row, widths) for row in table_rows]
    lines = [border, header, separator, *body, border]
    if result.get("truncated"):
        lines.append("Result truncated; showing returned rows only.")
    return "\n".join(lines)


def _format_empty_table(columns: list[str], truncated: bool) -> str:
    widths = [len(column) for column in columns]
    lines = [
        _table_border(widths),
        _table_row(columns, widths),
        _table_border(widths),
        "(no rows)",
    ]
    if truncated:
        lines.append("Result truncated; showing returned rows only.")
    return "\n".join(lines)


def _table_border(widths: list[int]) -> str:
    return "+" + "+".join("-" * (width + 2) for width in widths) + "+"


def _table_row(values: list[str], widths: list[int]) -> str:
    padded = [value.ljust(widths[index]) for index, value in enumerate(values)]
    return "| " + " | ".join(padded) + " |"


if __name__ == "__main__":
    raise SystemExit(main())
