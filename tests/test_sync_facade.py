import time

import httpx

from meu_danfe.sync_client import MeuDanfeClient


def _ok_handler(request: httpx.Request) -> httpx.Response:
    if "fd/add" in request.url.path:
        return httpx.Response(200, json={"status": "OK"})
    return httpx.Response(200, json={"name": "n.xml", "type": "NFE", "format": "XML", "data": "<x/>"})


def test_sequential_sync_fetch_same_key_respects_one_second_pacing_between_calls() -> None:
    # Measure the gap BETWEEN requests, not just total elapsed time: a single
    # fetch() already takes ~1s on its own (add -> get_xml is paced too), so
    # a naive asyncio.run()-per-call facade (that resets the pacer on every
    # call) would also satisfy `elapsed >= 1.0` for two calls without ever
    # actually pacing between them. Only the inter-call gap proves the pacer's
    # state survives across sync calls.
    timestamps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        timestamps.append(time.monotonic())
        return _ok_handler(request)

    access_key = "5" * 44
    with MeuDanfeClient("chave", transport=httpx.MockTransport(handler), max_polls=5) as client:
        client.fetch(access_key)
        boundary = len(timestamps)
        client.fetch(access_key)

    gap = timestamps[boundary] - timestamps[boundary - 1]
    assert gap >= 1.0


def test_fetch_many_and_iter_fetch_return_results_for_every_key() -> None:
    transport = httpx.MockTransport(_ok_handler)
    with MeuDanfeClient("chave", transport=transport, max_polls=5, min_key_interval=0.01,
                         allow_unsafe_interval=True) as client:
        results = client.fetch_many(["1" * 44, "2" * 44])
        assert {r.key for r in results} == {"1" * 44, "2" * 44}
        assert all(r.ok for r in results)

        streamed = list(client.iter_fetch(["3" * 44]))
        assert len(streamed) == 1
        assert streamed[0].ok is True


def test_close_stops_the_background_thread_cleanly() -> None:
    client = MeuDanfeClient("chave", transport=httpx.MockTransport(_ok_handler))
    client.close()
    assert not client._runner._thread.is_alive()
