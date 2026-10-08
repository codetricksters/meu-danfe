"""Async client for the Meu DANFE API.

Encapsulates the three things a consumer must never reimplement: the
status state machine (WAITING/SEARCHING -> NOT_FOUND/OK/ERROR), the
HTTP-status-to-exception mapping, and the >=1s-per-key pacing rule —
applied to EVERY endpoint for a key, including the final download, which
the original app.py did not pace at all.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from types import TracebackType
from typing import Any, Self

import httpx

from meu_danfe.config import DEFAULT_BASE_URL, MeuDanfeConfig
from meu_danfe.exceptions import (
    ConfigurationError,
    MalformedResponseError,
    MeuDanfeError,
    NotFoundStatusError,
    PollTimeoutError,
    SearchFailedError,
    TransportError,
    error_from_response,
)
from meu_danfe.keys import validate_key
from meu_danfe.models import AddResult, DocumentStatus, FetchResult, XmlDocument
from meu_danfe.pacing import KeyPacer

logger = logging.getLogger("meu_danfe")


class MeuDanfeAsyncClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        config: MeuDanfeConfig | None = None,
        timeout: float = 30.0,
        max_concurrency: int = 10,
        min_key_interval: float = 1.0,
        max_polls: int = 30,
        allow_unsafe_interval: bool = False,
        transport: httpx.AsyncBaseTransport | None = None,
        http_client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if config is None:
            if not api_key:
                raise ConfigurationError(
                    "MEU_DANFE_API_KEY não definida. Passe api_key= explicitamente "
                    "ou use MeuDanfeAsyncClient.from_env()."
                )
            config = MeuDanfeConfig(
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
                max_concurrency=max_concurrency,
                min_key_interval=min_key_interval,
                max_polls=max_polls,
                allow_unsafe_interval=allow_unsafe_interval,
            )
        self._config = config
        self._pacer = KeyPacer(
            min_interval=config.min_key_interval,
            max_concurrency=config.max_concurrency,
            clock=clock,
            sleep=sleep,
            allow_unsafe_interval=config.allow_unsafe_interval,
        )
        self._owns_http_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            base_url=config.base_url,
            headers={"Api-Key": config.api_key, "accept": "application/json"},
            timeout=config.timeout,
            transport=transport,
        )

    @classmethod
    def from_env(cls, **overrides: Any) -> Self:
        transport = overrides.pop("transport", None)
        config = MeuDanfeConfig.from_env(**overrides)
        return cls(config=config, transport=transport)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._http.aclose()

    async def _request(self, method: str, path: str, *, key: str) -> httpx.Response:
        async with self._pacer.slot(key):
            try:
                response = await self._http.request(method, path)
            except httpx.RequestError as exc:
                # Covers TransportError, TimeoutException, DecodingError,
                # TooManyRedirects — every network/protocol-level failure
                # httpx can raise, not just the two originally anticipated.
                raise TransportError(f"{key}: falha de transporte ao chamar {path}") from exc
        if response.status_code >= 400:
            raise error_from_response(key, response)
        return response

    @staticmethod
    def _parse_json(key: str, response: httpx.Response, *, context: str) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise MalformedResponseError(f"{key}: {context} não é JSON válido") from exc

    def _status_from(self, key: str, response: httpx.Response) -> tuple[DocumentStatus, Any]:
        payload = self._parse_json(key, response, context="resposta de consulta")
        raw_status = payload.get("status") if isinstance(payload, dict) else None
        # `isinstance(raw_status, str)` must be checked before the `in` membership
        # test below: a non-string status (e.g. a list, from a malformed vendor
        # response) makes `x in DocumentStatus.__members__` raise TypeError
        # (unhashable type), which used to escape uncaught.
        if not isinstance(raw_status, str) or raw_status not in DocumentStatus.__members__:
            raise MalformedResponseError(f"{key}: resposta sem campo 'status' reconhecível: {payload!r}")
        return DocumentStatus(raw_status), payload

    async def add(self, key: str) -> AddResult:
        request_key = validate_key(key)
        response = await self._request("PUT", f"fd/add/{request_key}", key=key)
        status, payload = self._status_from(key, response)
        return AddResult(key=key, status=status, raw=payload)

    async def get_xml(self, key: str) -> XmlDocument:
        request_key = validate_key(key)
        response = await self._request("GET", f"fd/get/xml/{request_key}", key=key)
        payload = self._parse_json(key, response, context="resposta de download")
        if not isinstance(payload, dict):
            raise MalformedResponseError(f"{key}: resposta de download não é um objeto JSON: {payload!r}")
        return XmlDocument(
            key=key,
            name=payload.get("name") or f"{key}.xml",
            doc_type=payload.get("type", ""),
            content_format=payload.get("format", ""),
            data=payload.get("data", ""),
            raw=payload,
        )

    async def wait_for(
        self, key: str, *, max_polls: int | None = None, poll_interval: float | None = None
    ) -> AddResult:
        limit = self._config.max_polls if max_polls is None else max_polls
        result = await self.add(key)
        polls = 1
        while not result.status.is_terminal:
            if polls >= limit:
                raise PollTimeoutError(key=key, polls=polls, last_status=result.status)
            result = await self.add(key)
            polls += 1
        return result

    async def fetch(self, key: str) -> XmlDocument:
        result = await self.wait_for(key)
        if result.status is DocumentStatus.NOT_FOUND:
            raise NotFoundStatusError(key=key)
        if result.status is DocumentStatus.ERROR:
            raise SearchFailedError(key=key)
        return await self.get_xml(key)

    async def fetch_many(self, keys: Iterable[str]) -> list[FetchResult]:
        return [result async for result in self.iter_fetch(keys)]

    async def iter_fetch(self, keys: Iterable[str]) -> AsyncIterator[FetchResult]:
        async def _one(key: str) -> FetchResult:
            polls = 0
            try:
                limit = self._config.max_polls
                result = await self.add(key)
                polls = 1
                while not result.status.is_terminal:
                    if polls >= limit:
                        raise PollTimeoutError(key=key, polls=polls, last_status=result.status)
                    result = await self.add(key)
                    polls += 1
                if result.status is DocumentStatus.OK:
                    document = await self.get_xml(key)
                    return FetchResult(key=key, status=result.status, document=document, error=None, polls=polls)
                return FetchResult(key=key, status=result.status, document=None, error=None, polls=polls)
            except MeuDanfeError as exc:
                return FetchResult(key=key, status=None, document=None, error=exc, polls=polls)
            except Exception as exc:
                # Batch isolation is the point of this method: even a bug we
                # haven't anticipated for ONE key must not escape and cancel
                # or lose the results of every other key in the batch.
                return FetchResult(
                    key=key, status=None, document=None,
                    error=MeuDanfeError(f"{key}: erro inesperado: {exc}"), polls=polls,
                )

        pending = {asyncio.ensure_future(_one(key)) for key in keys}
        try:
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    yield await task
        finally:
            # If the consumer abandons this generator early (breaks out of
            # `async for`, or it's garbage collected), cancel whatever is
            # still in flight instead of letting it keep running — and
            # paying R$0,03 per new key — for a batch nobody is reading.
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
