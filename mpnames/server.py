"""Local HTTP API and static web server."""

from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import db
from .ollama import is_ollama_available


class AppServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler, db_path: Path, web_dir: Path):
        super().__init__(server_address, handler)
        self.db_path = db_path
        self.web_dir = web_dir


class Handler(BaseHTTPRequestHandler):
    server: AppServer

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._handle_api(parsed.path, parse_qs(parsed.query))
            return
        if parsed.path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._serve_static(parsed.path)

    def log_message(self, format: str, *args) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _handle_api(self, path: str, query: dict[str, list[str]]) -> None:
        connection = db.connect(self.server.db_path)
        db.initialize(connection)
        try:
            if path == "/api/stats":
                self._json(db.dataset_stats_snapshot(connection) or db.stats(connection))
            elif path == "/api/search":
                initial_search = (
                    db.dataset_initial_search_snapshot(connection)
                    if _is_initial_search(query)
                    else None
                )
                if initial_search is not None:
                    self._json(initial_search)
                else:
                    self._json(
                        db.search(
                            connection,
                            q=_params(query, "q"),
                            q_mode=_param(query, "q_mode", "and"),
                            q_target=_param(query, "q_target", "both"),
                            orbit=_params(query, "orbit"),
                            citation_category=_params(query, "citation_category"),
                            person_role=_params(query, "person_role"),
                            gender=_params(query, "gender"),
                            discoverer=_params(query, "discoverer"),
                            observatory=_params(query, "observatory"),
                            flag=_params(query, "flag"),
                            sort=_param(query, "sort", "number"),
                            direction=_param(query, "direction", "asc"),
                            limit=_int_param(query, "limit", 50),
                            offset=_int_param(query, "offset", 0),
                        )
                    )
            elif path == "/api/wordcloud":
                self._json(
                    {
                        "words": db.wordcloud(
                            connection,
                            q=_params(query, "q"),
                            q_mode=_param(query, "q_mode", "and"),
                            q_target=_param(query, "q_target", "both"),
                            orbit=_params(query, "orbit"),
                            citation_category=_params(query, "citation_category"),
                            person_role=_params(query, "person_role"),
                            gender=_params(query, "gender"),
                            discoverer=_params(query, "discoverer"),
                            observatory=_params(query, "observatory"),
                            flag=_params(query, "flag"),
                        )
                    }
                )
            elif path == "/api/facets":
                self._json(
                    db.facets(
                        connection,
                        q=_params(query, "q"),
                        q_mode=_param(query, "q_mode", "and"),
                        q_target=_param(query, "q_target", "both"),
                        orbit=_params(query, "orbit"),
                        citation_category=_params(query, "citation_category"),
                        person_role=_params(query, "person_role"),
                        gender=_params(query, "gender"),
                        discoverer=_params(query, "discoverer"),
                        observatory=_params(query, "observatory"),
                        flag=_params(query, "flag"),
                    )
                )
            elif path == "/api/ollama/status":
                self._json({"available": is_ollama_available()})
            elif path.startswith("/api/objects/"):
                permid = unquote(path.removeprefix("/api/objects/"))
                data = db.get_object(connection, permid)
                if data is None:
                    self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                else:
                    self._json(data)
            else:
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
        finally:
            connection.close()

    def _serve_static(self, path: str) -> None:
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (self.server.web_dir / relative).resolve()
        web_root = self.server.web_dir.resolve()
        if not str(target).startswith(str(web_root)) or not target.exists() or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve(db_path: Path, web_dir: Path, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    connection = db.connect(db_path)
    db.initialize(connection)
    connection.close()
    server = AppServer((host, port), Handler, db_path, web_dir)
    print(f"Serving Minor Planet Names Search at http://{host}:{port}/")
    server.serve_forever()
    return server


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve Minor Planet Names Search")
    parser.add_argument("--db", default=str(db.DEFAULT_DB), help="SQLite database path")
    parser.add_argument("--web", default="web", help="Static web directory")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind")
    return parser


def _param(query: dict[str, list[str]], key: str, default: str = "") -> str:
    values = query.get(key)
    return values[0] if values else default


def _params(query: dict[str, list[str]], key: str) -> list[str]:
    return query.get(key, [])


def _is_initial_search(query: dict[str, list[str]]) -> bool:
    filter_names = (
        "q", "orbit", "citation_category", "person_role", "gender",
        "discoverer", "observatory", "flag",
    )
    return (
        not any(value for name in filter_names for value in _params(query, name))
        and _param(query, "q_mode", "and") == "and"
        and _param(query, "q_target", "both") == "both"
        and query.get("sort") == ["alpha"]
        and _param(query, "direction", "asc") == "asc"
        and _int_param(query, "limit", 50) == 50
        and _int_param(query, "offset", 0) == 0
    )


def _int_param(query: dict[str, list[str]], key: str, default: int) -> int:
    try:
        return int(_param(query, key, str(default)))
    except ValueError:
        return default
