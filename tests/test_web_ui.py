from __future__ import annotations

import json
import threading
from importlib.resources import files
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from sql_query_agent.agent import AgentAnswer, AgentConfig
from sql_query_agent.web_ui import create_server


def test_web_ui_serves_html_with_static_asset_references(tmp_path) -> None:
    config = AgentConfig(db_path=tmp_path / "sample.db", model="test-model", memory_enabled=False)
    server = create_server(config, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        url = _server_url(server)
        with urlopen(url, timeout=5) as response:
            body = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert response.status == 200
    assert response.headers["Content-Type"].startswith("text/html")
    assert "SQL Query Agent" in body
    assert 'href="/styles.css"' in body
    assert 'src="/vendor/marked.min.js"' in body
    assert 'src="/vendor/purify.min.js"' in body
    assert 'src="/app.js"' in body


@pytest.mark.parametrize(
    ("path", "content_type", "expected_text"),
    [
        ("styles.css", "text/css", ".markdown"),
        ("app.js", "application/javascript", "DOMPurify"),
        ("vendor/marked.min.js", "application/javascript", "marked"),
        ("vendor/purify.min.js", "application/javascript", "DOMPurify"),
    ],
)
def test_web_ui_serves_static_assets(tmp_path, path: str, content_type: str, expected_text: str) -> None:
    config = AgentConfig(db_path=tmp_path / "sample.db", model="test-model", memory_enabled=False)
    server = create_server(config, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with urlopen(f"{_server_url(server)}{path}", timeout=5) as response:
            body = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert response.status == 200
    assert response.headers["Content-Type"].startswith(content_type)
    assert expected_text in body


def test_web_ui_unknown_static_path_returns_404(tmp_path) -> None:
    config = AgentConfig(db_path=tmp_path / "sample.db", model="test-model", memory_enabled=False)
    server = create_server(config, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with pytest.raises(HTTPError) as exc_info:
            urlopen(f"{_server_url(server)}missing.css", timeout=5)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert exc_info.value.code == 404


def test_web_ui_ask_endpoint_returns_agent_answer(tmp_path, monkeypatch) -> None:
    captured = {}

    def fake_ask(question: str, config: AgentConfig) -> AgentAnswer:
        captured["question"] = question
        captured["config"] = config
        return AgentAnswer(
            answer="There are 4 customers.",
            sql_queries=["SELECT COUNT(*) AS customer_count FROM customers"],
            query_results=[
                {
                    "columns": ["customer_count"],
                    "rows": [{"customer_count": 4}],
                    "row_count": 1,
                    "truncated": False,
                    "sql": "SELECT COUNT(*) AS customer_count FROM customers",
                    "error": None,
                }
            ],
        )

    monkeypatch.setattr("sql_query_agent.web_ui.ask", fake_ask)
    config = AgentConfig(db_path=tmp_path / "sample.db", model="test-model", memory_enabled=False)
    server = create_server(config, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        request = Request(
            f"{_server_url(server)}api/ask",
            data=json.dumps({"question": "How many customers?"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert response.status == 200
    assert captured == {"question": "How many customers?", "config": config}
    assert payload["answer"] == "There are 4 customers."
    assert payload["sql_queries"] == ["SELECT COUNT(*) AS customer_count FROM customers"]
    assert payload["query_results"][0]["rows"] == [{"customer_count": 4}]


def test_web_ui_static_assets_are_package_resources() -> None:
    package = files("sql_query_agent")

    assert package.joinpath("static", "index.html").is_file()
    assert package.joinpath("static", "styles.css").is_file()
    assert package.joinpath("static", "app.js").is_file()


def _server_url(server) -> str:
    host, port = server.server_address[:2]
    return f"http://{host}:{port}/"
