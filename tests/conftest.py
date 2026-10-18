from __future__ import annotations

import io
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def validation(status: str = "done", valid: bool = True, errors: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A validation as the API returns it."""
    errors = errors or []
    finished = status not in ("queued", "running")
    return {
        "id": "val_1",
        "status": status,
        "progress": 100 if finished else 0,
        "created_at": "2026-10-18T10:00:00+00:00",
        "finished_at": "2026-10-18T10:00:01+00:00" if finished else None,
        "document": {"source": "upload", "name": "invoice.xml", "size": 12},
        "schema": {"kind": "xsd", "catalog": "peppol-bis-3-invoice", "name": "Peppol BIS Billing 3.0 Invoice"},
        "result": {
            "valid": valid,
            "outcome": "valid" if valid else "invalid",
            "errors_total": len(errors),
            "warnings_total": 0,
            "errors_truncated": False,
            "errors": errors,
            "warnings": [],
            "bytes": 12,
            "duration_ms": 5,
        }
        if finished
        else None,
        "error": None,
        "links": {"report": "https://xmlvalid.com/api/v1/validations/val_1/report"},
    }


class Api:
    """Answers requests from a queue and keeps them, bodies read, for assertions."""

    def __init__(self) -> None:
        self.queue: list[httpx.Response | Exception] = []
        self.requests: list[httpx.Request] = []
        self.bodies: list[bytes] = []

    def json(self, status: int, body: Any, headers: dict[str, str] | None = None) -> Api:
        self.queue.append(
            httpx.Response(
                status,
                content=json.dumps(body).encode(),
                headers={"Content-Type": "application/json", **(headers or {})},
            )
        )
        return self

    def raw(self, status: int, body: str, headers: dict[str, str] | None = None) -> Api:
        self.queue.append(httpx.Response(status, text=body, headers=headers))
        return self

    def fail(self, error: Exception) -> Api:
        self.queue.append(error)
        return self

    def _answer(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.queue:
            raise AssertionError(f"Unexpected request {request.method} {request.url}")
        answer = self.queue.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(request.read())
        return self._answer(request)

    async def async_handler(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(await request.aread())
        return self._answer(request)


@pytest.fixture
def api() -> Api:
    return Api()


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Records the client's sleeps instead of sleeping."""
    slept: list[float] = []

    async def asleep(seconds: float) -> None:
        slept.append(seconds)

    record: Callable[[float], None] = slept.append
    monkeypatch.setattr("xmlvalid._client.time.sleep", record)
    monkeypatch.setattr("xmlvalid._client.anyio.sleep", asleep)
    return slept


class Reads(io.BytesIO):
    """Remembers the sizes it was read with: a streamed upload never reads all at once."""

    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.sizes: list[int | None] = []

    def read(self, size: int | None = -1, /) -> bytes:
        self.sizes.append(size)
        return super().read(size)

    @property
    def streamed(self) -> bool:
        return bool(self.sizes) and all(size is not None and size > 0 for size in self.sizes)
