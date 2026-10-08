import time

import httpx

from meu_danfe.sync_client import MeuDanfeClient


def _ok_handler(request: httpx.Request) -> httpx.Response:
    if "fd/add" in request.url.path:
        return httpx.Response(200, json={"status": "OK"})
    return httpx.Response(200, json={"name": "n.xml", "type": "NFE", "format": "XML", "data": "<x/>"})


def test_sequential_sync_fetch_same_key_respects_one_second_pacing() -> None:
    transport = httpx.MockTransport(_ok_handler)
    with MeuDanfeClient("chave", transport=transport, max_polls=5) as client:
        start = time.monotonic()
        client.fetch("k" * 44)
        client.fetch("k" * 44)
        elapsed = time.monotonic() - start
    assert elapsed >= 1.0


def test_fetch_many_and_iter_fetch_return_results_for_every_key() -> None:
    transport = httpx.MockTransport(_ok_handler)
    with MeuDanfeClient("chave", transport=transport, max_polls=5, min_key_interval=0.01,
                         allow_unsafe_interval=True) as client:
        results = client.fetch_many(["a" * 44, "b" * 44])
        assert {r.key for r in results} == {"a" * 44, "b" * 44}
        assert all(r.ok for r in results)

        streamed = list(client.iter_fetch(["c" * 44]))
        assert len(streamed) == 1
        assert streamed[0].ok is True


def test_close_stops_the_background_thread_cleanly() -> None:
    client = MeuDanfeClient("chave", transport=httpx.MockTransport(_ok_handler))
    client.close()
    assert not client._runner._thread.is_alive()
