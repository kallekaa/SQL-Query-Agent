from __future__ import annotations

import sqlite3

from sql_query_agent.cli import main


def test_cli_init_sample_creates_sqlite_file(tmp_path, capsys) -> None:
    db_path = tmp_path / "sample.db"

    exit_code = main(["init-sample", "--db", str(db_path)])

    assert exit_code == 0
    assert db_path.exists()
    assert "Created sample database" in capsys.readouterr().out
    with sqlite3.connect(db_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    assert count == 4
