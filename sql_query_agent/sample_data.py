from __future__ import annotations

import sqlite3
from pathlib import Path


def init_sample_database(db_path: str | Path, overwrite: bool = False) -> Path:
    path = Path(db_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        if not overwrite:
            raise FileExistsError(f"Database already exists: {path}")
        path.unlink()

    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                signup_date TEXT NOT NULL
            );

            CREATE TABLE products (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                price REAL NOT NULL
            );

            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                order_date TEXT NOT NULL,
                status TEXT NOT NULL,
                FOREIGN KEY (customer_id) REFERENCES customers(id)
            );

            CREATE TABLE order_items (
                id INTEGER PRIMARY KEY,
                order_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(id),
                FOREIGN KEY (product_id) REFERENCES products(id)
            );
            """
        )

        connection.executemany(
            "INSERT INTO customers (id, name, email, signup_date) VALUES (?, ?, ?, ?)",
            [
                (1, "Ava Carter", "ava@example.com", "2025-11-08"),
                (2, "Noah Kim", "noah@example.com", "2026-01-19"),
                (3, "Mia Lopez", "mia@example.com", "2026-03-04"),
                (4, "Ethan Singh", "ethan@example.com", "2026-04-11"),
            ],
        )
        connection.executemany(
            "INSERT INTO products (id, name, category, price) VALUES (?, ?, ?, ?)",
            [
                (1, "Analytics Notebook", "Software", 49.00),
                (2, "Data Pipeline Guide", "Books", 29.00),
                (3, "SQL Workshop Seat", "Training", 299.00),
                (4, "Dashboard Template", "Software", 79.00),
            ],
        )
        connection.executemany(
            "INSERT INTO orders (id, customer_id, order_date, status) VALUES (?, ?, ?, ?)",
            [
                (1, 1, "2026-05-03", "paid"),
                (2, 2, "2026-05-14", "paid"),
                (3, 1, "2026-05-21", "paid"),
                (4, 3, "2026-06-02", "paid"),
                (5, 4, "2026-04-27", "refunded"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO order_items (id, order_id, product_id, quantity, unit_price)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (1, 1, 1, 2, 49.00),
                (2, 1, 2, 1, 29.00),
                (3, 2, 3, 1, 299.00),
                (4, 2, 4, 2, 79.00),
                (5, 3, 1, 1, 49.00),
                (6, 3, 4, 1, 79.00),
                (7, 4, 2, 3, 29.00),
                (8, 5, 3, 1, 299.00),
            ],
        )

    return path
