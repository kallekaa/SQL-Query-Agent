from __future__ import annotations

import json
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from typing import Any
from urllib.parse import urlparse

from .agent import AgentConfig, ask


_MAX_REQUEST_BYTES = 64 * 1024
_STATIC_ROUTES = {
    "/": ("static/index.html", "text/html; charset=utf-8"),
    "/index.html": ("static/index.html", "text/html; charset=utf-8"),
    "/styles.css": ("static/styles.css", "text/css; charset=utf-8"),
    "/app.js": ("static/app.js", "application/javascript; charset=utf-8"),
    "/vendor/marked.min.js": ("static/vendor/marked.min.js", "application/javascript; charset=utf-8"),
    "/vendor/purify.min.js": ("static/vendor/purify.min.js", "application/javascript; charset=utf-8"),
}


class SQLAgentHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], config: AgentConfig) -> None:
        super().__init__(server_address, SQLAgentRequestHandler)
        self.agent_config = config


class SQLAgentRequestHandler(BaseHTTPRequestHandler):
    server: SQLAgentHTTPServer

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        static_route = _STATIC_ROUTES.get(path)
        if static_route is not None:
            self._send_static(*static_route)
            return

        if path == "/health":
            self._send_json(HTTPStatus.OK, {"ok": True})
            return

        if path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/ask":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found."})
            return

        try:
            payload = self._read_json_body()
            question = str(payload.get("question", "")).strip()
            if not question:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Question is required."})
                return

            answer = ask(question, self.server.agent_config)
            self._send_json(
                HTTPStatus.OK,
                {
                    "answer": answer.answer,
                    "sql_queries": answer.sql_queries,
                    "query_results": answer.query_results,
                },
            )
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json_body(self) -> dict[str, Any]:
        length_header = self.headers.get("Content-Length")
        if length_header is None:
            raise ValueError("Request body is required.")

        try:
            length = int(length_header)
        except ValueError as exc:
            raise ValueError("Content-Length must be an integer.") from exc

        if length > _MAX_REQUEST_BYTES:
            raise ValueError("Request body is too large.")

        raw_body = self.rfile.read(length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Request body must be valid JSON.") from exc

        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object.")
        return payload

    def _send_static(self, asset_path: str, content_type: str) -> None:
        try:
            body = files("sql_query_agent").joinpath(*asset_path.split("/")).read_bytes()
        except FileNotFoundError:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Static asset is missing."})
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


def create_server(config: AgentConfig, host: str = "127.0.0.1", port: int = 8000) -> SQLAgentHTTPServer:
    return SQLAgentHTTPServer((host, port), config)


def run_ui(
    config: AgentConfig,
    host: str = "127.0.0.1",
    port: int = 8000,
    open_browser: bool = True,
) -> None:
    server = create_server(config, host=host, port=port)
    actual_host, actual_port = server.server_address[:2]
    browser_host = "127.0.0.1" if actual_host in {"", "0.0.0.0"} else actual_host
    url = f"http://{browser_host}:{actual_port}/"

    print(f"SQL Query Agent UI running at {url}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
