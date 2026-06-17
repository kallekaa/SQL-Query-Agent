from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot import expressions as exp


class DatabaseError(Exception):
    """Base exception for database access failures."""


class SQLValidationError(DatabaseError):
    """Raised when SQL is not safe to execute."""


class DatabaseNotFoundError(DatabaseError):
    """Raised when the configured SQLite database does not exist."""


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    sql: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": self.columns,
            "rows": self.rows,
            "row_count": self.row_count,
            "truncated": self.truncated,
            "sql": self.sql,
            "error": self.error,
        }


_FORBIDDEN_NODE_NAMES = {
    "alter",
    "analyze",
    "attach",
    "command",
    "commit",
    "create",
    "delete",
    "detach",
    "drop",
    "execute",
    "grant",
    "insert",
    "merge",
    "pragma",
    "replace",
    "rollback",
    "set",
    "transaction",
    "truncate",
    "update",
    "use",
}


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _readonly_connection(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path).expanduser().resolve()
    if not path.exists():
        raise DatabaseNotFoundError(f"SQLite database not found: {path}")

    uri = f"{path.as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def validate_read_only_sql(sql: str) -> None:
    if not sql or not sql.strip():
        raise SQLValidationError("SQL query is empty.")

    try:
        expressions = sqlglot.parse(sql, read="sqlite")
    except sqlglot.errors.ParseError as exc:
        raise SQLValidationError(f"SQL could not be parsed: {exc}") from exc

    if len(expressions) != 1:
        raise SQLValidationError("Only one SQL statement is allowed.")

    expression = expressions[0]
    if expression is None:
        raise SQLValidationError("SQL query is empty.")

    if not isinstance(expression, (exp.Select, exp.Union)):
        raise SQLValidationError("Only read-only SELECT or WITH queries are allowed.")

    for node in expression.walk():
        node_name = node.__class__.__name__.lower()
        if node_name in _FORBIDDEN_NODE_NAMES:
            raise SQLValidationError(f"Forbidden SQL operation detected: {node_name}.")


def get_schema(db_path: str | Path, table_names: list[str] | None = None) -> dict[str, Any]:
    try:
        with _readonly_connection(db_path) as connection:
            rows = connection.execute(
                """
                SELECT name, type
                FROM sqlite_schema
                WHERE type IN ('table', 'view')
                  AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()

            requested = set(table_names or [])
            tables = []
            for row in rows:
                table_name = row["name"]
                if requested and table_name not in requested:
                    continue

                quoted = _quote_identifier(table_name)
                columns = [
                    {
                        "name": column["name"],
                        "type": column["type"],
                        "not_null": bool(column["notnull"]),
                        "default": column["dflt_value"],
                        "primary_key": bool(column["pk"]),
                    }
                    for column in connection.execute(f"PRAGMA table_info({quoted})").fetchall()
                ]
                foreign_keys = [
                    {
                        "from": key["from"],
                        "to_table": key["table"],
                        "to_column": key["to"],
                    }
                    for key in connection.execute(f"PRAGMA foreign_key_list({quoted})").fetchall()
                ]
                tables.append(
                    {
                        "name": table_name,
                        "type": row["type"],
                        "columns": columns,
                        "foreign_keys": foreign_keys,
                    }
                )

            missing = sorted(requested - {table["name"] for table in tables}) if requested else []
            return {"tables": tables, "missing_tables": missing, "error": None}
    except DatabaseError as exc:
        return {"tables": [], "missing_tables": table_names or [], "error": str(exc)}
    except sqlite3.Error as exc:
        return {"tables": [], "missing_tables": table_names or [], "error": f"SQLite error: {exc}"}


def get_table_names(db_path: str | Path) -> dict[str, Any]:
    try:
        with _readonly_connection(db_path) as connection:
            rows = connection.execute(
                """
                SELECT name
                FROM sqlite_schema
                WHERE type IN ('table', 'view')
                  AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
            return {"tables": [row["name"] for row in rows], "error": None}
    except DatabaseError as exc:
        return {"tables": [], "error": str(exc)}
    except sqlite3.Error as exc:
        return {"tables": [], "error": f"SQLite error: {exc}"}


def query_database(db_path: str | Path, sql: str, max_rows: int = 100) -> dict[str, Any]:
    max_rows = max(1, int(max_rows))

    try:
        validate_read_only_sql(sql)
        with _readonly_connection(db_path) as connection:
            cursor = connection.execute(sql)
            rows = cursor.fetchmany(max_rows + 1)
            visible_rows = rows[:max_rows]
            columns = [description[0] for description in cursor.description or []]
            result_rows = [
                {column: _json_safe_value(row[column]) for column in columns}
                for row in visible_rows
            ]

            return QueryResult(
                columns=columns,
                rows=result_rows,
                row_count=len(result_rows),
                truncated=len(rows) > max_rows,
                sql=sql,
            ).to_dict()
    except DatabaseError as exc:
        return QueryResult([], [], 0, False, sql, str(exc)).to_dict()
    except sqlite3.Error as exc:
        return QueryResult([], [], 0, False, sql, f"SQLite error: {exc}").to_dict()


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.hex()
    return value
