"""Enforces the vendor's rule: the SAME access key must not be requested
more than once per second, or the account gets blocked. This is the one
piece of behaviour a consumer must never be able to bypass."""
from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from meu_danfe.exceptions import ConfigurationError


class KeyPacer:
    """>= min_interval seconds between consecutive requests for the SAME
    key; caps requests in flight across all keys at max_concurrency.

    All asyncio primitives are created lazily, on first use inside a
    running event loop — a KeyPacer built before any loop runs (e.g. at
    client-construction time) never binds to the wrong loop.
    """

    def __init__(
        self,
        min_interval: float = 1.0,
        *,
        max_concurrency: int | None = 10,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_tracked_keys: int = 4096,
        allow_unsafe_interval: bool = False,
    ) -> None:
        if min_interval < 1.0 and not allow_unsafe_interval:
            raise ConfigurationError(
                "min_interval abaixo de 1.0s viola a regra do fornecedor "
                "(chaves repetidas em menos de 1s bloqueiam a conta). "
                "Passe allow_unsafe_interval=True para forçar."
            )
        self._min_interval = min_interval
        self._max_concurrency = max_concurrency
        self._clock = clock
        self._sleep = sleep
        self._max_tracked_keys = max_tracked_keys
        self._last_seen: OrderedDict[str, float] = OrderedDict()
        self._key_locks: OrderedDict[str, asyncio.Lock] = OrderedDict()
        self._semaphore: asyncio.Semaphore | None = None

    def _get_semaphore(self) -> asyncio.Semaphore | None:
        if self._max_concurrency is None:
            return None
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._max_concurrency)
        return self._semaphore

    def _get_key_lock(self, key: str) -> asyncio.Lock:
        lock = self._key_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._key_locks[key] = lock
            self._prune()
        else:
            self._key_locks.move_to_end(key)
        return lock

    def _prune(self) -> None:
        while len(self._key_locks) > self._max_tracked_keys:
            oldest_key = next(iter(self._key_locks))
            if self._key_locks[oldest_key].locked():
                break
            del self._key_locks[oldest_key]
            self._last_seen.pop(oldest_key, None)

    @asynccontextmanager
    async def slot(self, key: str) -> AsyncIterator[None]:
        semaphore = self._get_semaphore()
        lock = self._get_key_lock(key)
        async with lock:
            last = self._last_seen.get(key)
            if last is not None:
                wait = self._min_interval - (self._clock() - last)
                if wait > 0:
                    await self._sleep(wait)
            if semaphore is not None:
                await semaphore.acquire()
            try:
                yield
            finally:
                if semaphore is not None:
                    semaphore.release()
                self._last_seen[key] = self._clock()
                self._last_seen.move_to_end(key)
