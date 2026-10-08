"""Synchronous facade over MeuDanfeAsyncClient.

Runs the SAME async client on a dedicated event loop in a background
thread owned by this object, so the httpx connection pool and the
KeyPacer's per-key timestamps persist across calls — unlike calling
asyncio.run() per method, which creates a fresh loop (and a fresh
KeyPacer) every time and would silently break the >=1s-per-key pacing
rule between two sequential sync calls for the same key.
"""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterable, Iterator
from types import TracebackType
from typing import Any, Self

from meu_danfe.client import MeuDanfeAsyncClient
from meu_danfe.config import MeuDanfeConfig
from meu_danfe.models import AddResult, FetchResult, XmlDocument


class _LoopRunner:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True, name="meu-danfe-loop")
        self._thread.start()

    def run(self, coro: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def run_each(self, make_agen: Any) -> Iterator[Any]:
        agen = make_agen()

        async def _advance() -> Any:
            return await agen.__anext__()

        while True:
            try:
                yield self.run(_advance())
            except StopAsyncIteration:
                return

    def close(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        self._loop.close()


class MeuDanfeClient:
    """Sync twin of MeuDanfeAsyncClient. Same method names, no `async`."""

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        self._runner = _LoopRunner()

        async def _build() -> MeuDanfeAsyncClient:
            return MeuDanfeAsyncClient(api_key, **kwargs)

        self._async = self._runner.run(_build())

    @classmethod
    def from_env(cls, **overrides: Any) -> Self:
        transport = overrides.pop("transport", None)
        config = MeuDanfeConfig.from_env(**overrides)
        instance = cls.__new__(cls)
        instance._runner = _LoopRunner()

        async def _build() -> MeuDanfeAsyncClient:
            return MeuDanfeAsyncClient(config=config, transport=transport)

        instance._async = instance._runner.run(_build())
        return instance

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()

    def close(self) -> None:
        self._runner.run(self._async.aclose())
        self._runner.close()

    def add(self, key: str) -> AddResult:
        return self._runner.run(self._async.add(key))

    def get_xml(self, key: str) -> XmlDocument:
        return self._runner.run(self._async.get_xml(key))

    def wait_for(self, key: str, *, max_polls: int | None = None, poll_interval: float | None = None) -> AddResult:
        return self._runner.run(self._async.wait_for(key, max_polls=max_polls, poll_interval=poll_interval))

    def fetch(self, key: str) -> XmlDocument:
        return self._runner.run(self._async.fetch(key))

    def fetch_many(self, keys: Iterable[str]) -> list[FetchResult]:
        return self._runner.run(self._async.fetch_many(keys))

    def iter_fetch(self, keys: Iterable[str]) -> Iterator[FetchResult]:
        yield from self._runner.run_each(lambda: self._async.iter_fetch(keys))
