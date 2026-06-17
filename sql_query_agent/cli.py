from __future__ import annotations

import argparse
import sys
from pathlib import Path

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
                max_rows=args.max_rows,
                show_sql=args.show_sql,
            )
            answer = ask(args.question, config)
            print(answer.answer)
            if args.show_sql and answer.sql_queries:
                for sql in answer.sql_queries:
                    print(f"SQL: {sql}")
            return 0

        if args.command == "chat":
            from .agent import config_from_env, run_chat

            config = config_from_env(
                db_path=args.db,
                model=args.model,
                max_rows=args.max_rows,
                show_sql=args.show_sql,
            )
            run_chat(config)
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
        help="SQLite database path. Defaults to SQL_AGENT_DB_PATH, then DATABASE_FILE.",
    )
    parser.add_argument("--model", default=None, help="OpenAI model. Defaults to OPENAI_MODEL.")
    parser.add_argument("--max-rows", type=int, default=None, help="Maximum rows returned from a query.")
    parser.add_argument("--show-sql", action="store_true", help="Print SQL queries used by the agent.")


if __name__ == "__main__":
    raise SystemExit(main())
