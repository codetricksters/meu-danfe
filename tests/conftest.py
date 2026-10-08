"""Shared pytest fixtures for the meu_danfe test suite.

No test here may reach the real network: every real query against the
Meu DANFE API costs R$ 0,03, so an autouse fixture patches httpx's real
transport classes to raise if anything tries. httpx.MockTransport is a
different class and is unaffected.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "A test attempted a real network request. Use httpx.MockTransport instead."
        )

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _forbidden, raising=True)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _forbidden, raising=True)


class FakeClock:
    """A controllable monotonic clock + async sleep for pacing tests.

    `now` only advances when `sleep()` is awaited, so tests assert
    elapsed time without ever actually waiting.
    """

    def __init__(self, start: float = 0.0) -> None:
        self.now = start
        self.sleep_calls: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        if seconds > 0:
            self.now += seconds


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
