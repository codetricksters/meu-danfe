import httpx
import pytest

from meu_danfe.client import MeuDanfeAsyncClient
from meu_danfe.exceptions import (
    AuthenticationError,
    MalformedResponseError,
    PollTimeoutError,
    TransportError,
)


def _key(n: int = 1) -> str:
    return str(n) * 44


async def _noop(_s: float) -> None:
    return None


def _transport(script: dict[str, list[dict]]) -> httpx.MockTransport:
    """`script` maps a key to a list of JSON bodies returned in order for
    successive calls to that key's `fd/add` endpoint; the LAST entry also
    serves `fd/get/xml`."""
    calls: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        parts = request.url.path.rsplit("/", 1)
        key = parts[-1]
        if "fd/add" in request.url.path:
            n = calls.get(key, 0)
            calls[key] = n + 1
            body = script[key][min(n, len(script[key]) - 1)]
            return httpx.Response(200, json=body)
        if "fd/get/xml" in request.url.path:
            return httpx.Response(
                200, json={"name": f"{key}.xml", "type": "NFE", "format": "XML", "data": "<x/>"}
            )
        raise AssertionError(f"unexpected path {request.url.path}")

    return httpx.MockTransport(handler)


async def test_fetch_waits_through_waiting_and_searching_then_downloads() -> None:
    key = _key()
    transport = _transport({key: [{"status": "WAITING"}, {"status": "SEARCHING"}, {"status": "OK"}]})
    async with MeuDanfeAsyncClient("chave", transport=transport, max_polls=10, sleep=_noop) as client:
        document = await client.fetch(key)
    assert document.data == "<x/>"
    assert document.doc_type == "NFE"


async def test_not_found_status_raises_typed_error() -> None:
    key = _key(2)
    transport = _transport({key: [{"status": "NOT_FOUND"}]})
    async with MeuDanfeAsyncClient("chave", transport=transport, sleep=_noop) as client:
        with pytest.raises(Exception) as excinfo:
            await client.fetch(key)
    from meu_danfe.exceptions import NotFoundStatusError
    assert isinstance(excinfo.value, NotFoundStatusError)


async def test_http_401_raises_authentication_error() -> None:
    key = _key(3)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "nope"})

    async with MeuDanfeAsyncClient("chave", transport=httpx.MockTransport(handler), sleep=_noop) as client:
        with pytest.raises(AuthenticationError):
            await client.add(key)


async def test_poll_timeout_raises_after_max_polls() -> None:
    key = _key(4)
    transport = _transport({key: [{"status": "SEARCHING"}]})
    async with MeuDanfeAsyncClient("chave", transport=transport, max_polls=3, sleep=_noop) as client:
        with pytest.raises(PollTimeoutError):
            await client.fetch(key)


async def test_missing_status_field_raises_malformed_response_not_infinite_loop() -> None:
    key = _key(5)
    transport = _transport({key: [{"no_status_here": True}]})
    async with MeuDanfeAsyncClient("chave", transport=transport, max_polls=3, sleep=_noop) as client:
        with pytest.raises(MalformedResponseError):
            await client.add(key)


async def test_one_connect_error_in_a_batch_does_not_cancel_the_others() -> None:
    good_key = _key(6)
    bad_key = _key(7)

    def handler(request: httpx.Request) -> httpx.Response:
        if bad_key in request.url.path:
            raise httpx.ConnectError("boom", request=request)
        if "fd/add" in request.url.path:
            return httpx.Response(200, json={"status": "OK"})
        return httpx.Response(200, json={"name": "n.xml", "type": "NFE", "format": "XML", "data": "<x/>"})

    async with MeuDanfeAsyncClient("chave", transport=httpx.MockTransport(handler), sleep=_noop) as client:
        results = await client.fetch_many([good_key, bad_key])

    by_key = {r.key: r for r in results}
    assert by_key[good_key].ok is True
    assert by_key[bad_key].ok is False
    assert isinstance(by_key[bad_key].error, TransportError)
