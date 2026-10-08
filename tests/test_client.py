import asyncio

import httpx
import pytest

from meu_danfe.client import MeuDanfeAsyncClient
from meu_danfe.exceptions import (
    AuthenticationError,
    InvalidAccessKeyError,
    MalformedResponseError,
    MeuDanfeError,
    PollTimeoutError,
    TransportError,
)


def _key(n: int = 1) -> str:
    # str(n) % 10, not n itself: for n >= 10, str(n) is 2+ chars, so
    # str(n) * 44 would produce an 88+ char string — not a valid 44-digit key.
    return str(n % 10) * 44


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


async def test_non_string_status_in_batch_does_not_kill_the_other_keys() -> None:
    # Review-reproduced finding: {"status": [...]} makes `in DocumentStatus.__members__`
    # raise TypeError (unhashable list), which used to escape `iter_fetch` uncaught.
    good_key = _key(8)
    bad_key = _key(9)
    transport = _transport({good_key: [{"status": "OK"}], bad_key: [{"status": ["OK"]}]})
    async with MeuDanfeAsyncClient("chave", transport=transport, sleep=_noop) as client:
        results = await client.fetch_many([good_key, bad_key])
    by_key = {r.key: r for r in results}
    assert by_key[good_key].ok is True
    assert by_key[bad_key].ok is False
    assert isinstance(by_key[bad_key].error, MeuDanfeError)


async def test_get_xml_non_dict_payload_does_not_kill_the_batch() -> None:
    # Review-reproduced finding: a JSON list from get_xml raised AttributeError
    # ('list' object has no attribute 'get'), uncaught by iter_fetch.
    good_key = _key(10)
    bad_key = _key(11)

    def handler(request: httpx.Request) -> httpx.Response:
        if "fd/add" in request.url.path:
            return httpx.Response(200, json={"status": "OK"})
        if bad_key in request.url.path:
            return httpx.Response(200, json=["not", "a", "dict"])
        return httpx.Response(200, json={"name": "n.xml", "type": "NFE", "format": "XML", "data": "<x/>"})

    async with MeuDanfeAsyncClient("chave", transport=httpx.MockTransport(handler), sleep=_noop) as client:
        results = await client.fetch_many([good_key, bad_key])
    by_key = {r.key: r for r in results}
    assert by_key[good_key].ok is True
    assert by_key[bad_key].ok is False
    assert isinstance(by_key[bad_key].error, MeuDanfeError)


async def test_unexpected_exception_in_one_key_does_not_kill_the_batch() -> None:
    # Defense in depth for Review Focus "one failing key must not take down
    # a batch": even a bug we haven't anticipated must not escape iter_fetch.
    good_key = _key(12)
    bad_key = _key(13)

    def handler(request: httpx.Request) -> httpx.Response:
        if bad_key in request.url.path:
            raise RuntimeError("completely unanticipated bug")
        if "fd/add" in request.url.path:
            return httpx.Response(200, json={"status": "OK"})
        return httpx.Response(200, json={"name": "n.xml", "type": "NFE", "format": "XML", "data": "<x/>"})

    async with MeuDanfeAsyncClient("chave", transport=httpx.MockTransport(handler), sleep=_noop) as client:
        results = await client.fetch_many([good_key, bad_key])
    by_key = {r.key: r for r in results}
    assert by_key[good_key].ok is True
    assert by_key[bad_key].ok is False
    assert isinstance(by_key[bad_key].error, MeuDanfeError)


async def test_unvalidated_key_is_rejected_before_any_request_is_made() -> None:
    # Review-reproduced finding: add("../../admin/delete?x=") built a request
    # to that literal path — unvalidated keys were injected straight into the URL.
    requests_made: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_made.append(str(request.url))
        return httpx.Response(200, json={"status": "OK"})

    async with MeuDanfeAsyncClient("chave", transport=httpx.MockTransport(handler), sleep=_noop) as client:
        with pytest.raises(InvalidAccessKeyError):
            await client.add("../../admin/delete?x=")

    assert requests_made == []


async def test_abandoning_iter_fetch_cancels_the_still_pending_requests() -> None:
    # Review-reproduced finding: breaking out of `iter_fetch` early (or
    # letting the generator get garbage collected) left other keys' requests
    # running to completion anyway — continuing to spend R$0,03 per new key
    # for a batch nobody is reading.
    blocked_key = _key(7)
    quick_key = _key(8)
    release = asyncio.Event()
    blocked_request_started = asyncio.Event()
    resumed_after_release = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if blocked_key in request.url.path and "fd/add" in request.url.path:
            blocked_request_started.set()
            await release.wait()
            resumed_after_release["n"] += 1
            return httpx.Response(200, json={"status": "OK"})
        if "fd/add" in request.url.path:
            return httpx.Response(200, json={"status": "OK"})
        return httpx.Response(200, json={"name": "n.xml", "type": "NFE", "format": "XML", "data": "<x/>"})

    async with MeuDanfeAsyncClient("chave", transport=httpx.MockTransport(handler), sleep=_noop) as client:
        agen = client.iter_fetch([quick_key, blocked_key])
        first = await agen.__anext__()
        assert first.key == quick_key
        await blocked_request_started.wait()
        await agen.aclose()  # consumer abandons the generator early

    release.set()
    await asyncio.sleep(0)  # let a NOT-cancelled task resume, if the bug is present
    assert resumed_after_release["n"] == 0


async def test_fetch_result_key_matches_the_caller_supplied_key_even_when_invalid() -> None:
    good_key = _key(14)
    bad_key = "not-a-valid-key"

    def handler(request: httpx.Request) -> httpx.Response:
        if "fd/add" in request.url.path:
            return httpx.Response(200, json={"status": "OK"})
        return httpx.Response(200, json={"name": "n.xml", "type": "NFE", "format": "XML", "data": "<x/>"})

    async with MeuDanfeAsyncClient("chave", transport=httpx.MockTransport(handler), sleep=_noop) as client:
        results = await client.fetch_many([good_key, bad_key])
    by_key = {r.key: r for r in results}
    assert by_key[good_key].ok is True
    assert by_key[bad_key].ok is False
    assert isinstance(by_key[bad_key].error, InvalidAccessKeyError)
