"""Фальшивый мод: JSON-RPC сервер, отвечающий по схеме настоящего.

Нужен, чтобы отлаживать мост и командную строку без запущенной игры.
Ответы берутся из `tests/fixtures/gamestate.json`, который построен по
спецификации мода (`src/lua/utils/openrpc.json`).
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

FIXTURE = Path(__file__).parent / "fixtures" / "gamestate.json"


def sample_state() -> dict[str, Any]:
    """Свежая копия эталонного состояния, чтобы тесты не влияли друг на друга."""
    with FIXTURE.open(encoding="utf-8") as handle:
        return json.load(handle)  # type: ignore[no-any-return]


class FakeMod(BaseHTTPRequestHandler):
    """Обработчик запросов. Управляется классовыми полями, а не экземпляром:
    сервер создаёт обработчик на каждый запрос сам."""

    calls: ClassVar[list[dict[str, Any]]] = []
    """Все полученные запросы — по ним тесты проверяют, что отправил клиент."""

    error_for: ClassVar[str | None] = None
    """Метод, на который надо ответить ошибкой JSON-RPC."""

    state: ClassVar[dict[str, Any] | None] = None
    """Состояние, которое отдавать. `None` — эталонное из фикстуры."""

    @classmethod
    def reset(cls) -> None:
        cls.calls = []
        cls.error_for = None
        cls.state = None

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        FakeMod.calls.append(request)

        method = request.get("method")
        body: dict[str, Any] = {"jsonrpc": "2.0", "id": request.get("id")}
        if method == FakeMod.error_for:
            body["error"] = {"code": -32602, "message": "invalid params"}
        elif method == "health":
            body["result"] = {"status": "ok"}
        else:
            body["result"] = FakeMod.state if FakeMod.state is not None else sample_state()

        encoded = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, fmt: str, *args: Any) -> None:
        """Молчать: логи сервера в выводе тестов только мешают."""


@contextmanager
def running_fake_mod() -> Iterator[int]:
    """Поднять фальшивый мод на свободном порту и вернуть его номер."""
    FakeMod.reset()
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeMod)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
