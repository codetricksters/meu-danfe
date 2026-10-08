import httpx
import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from meu_danfe.config import MeuDanfeConfig
from meu_danfe.exceptions import ConfigurationError
from meu_danfe.server.app import create_app
from meu_danfe.server.settings import ServerSettings


def _ok_handler(request: httpx.Request) -> httpx.Response:
    if "fd/add" in request.url.path:
        return httpx.Response(200, json={"status": "OK"})
    return httpx.Response(200, json={"name": "n.xml", "type": "NFE", "format": "XML", "data": "<x/>"})


def _app(handler=_ok_handler, max_keys_per_request: int = 50):
    config = MeuDanfeConfig(api_key="chave")
    settings = ServerSettings(token="segredo", max_keys_per_request=max_keys_per_request)
    return create_app(config=config, settings=settings, transport=httpx.MockTransport(handler))


def test_healthz_requires_no_token() -> None:
    with TestClient(_app()) as client:
        resp = client.get("/healthz")
    assert resp.status_code == 200


def test_fetch_without_token_is_rejected() -> None:
    with TestClient(_app()) as client:
        resp = client.post("/v1/documents/fetch", json={"keys": ["k" * 44]})
    assert resp.status_code == 401


def test_fetch_with_wrong_token_is_rejected() -> None:
    with TestClient(_app()) as client:
        resp = client.post(
            "/v1/documents/fetch", json={"keys": ["k" * 44]}, headers={"X-Meu-Danfe-Token": "errado"}
        )
    assert resp.status_code == 401


def test_fetch_with_token_streams_one_ndjson_line_per_key() -> None:
    with TestClient(_app()) as client:
        resp = client.post(
            "/v1/documents/fetch",
            json={"keys": ["k" * 44, "j" * 44]},
            headers={"X-Meu-Danfe-Token": "segredo"},
        )
    assert resp.status_code == 200
    lines = [line for line in resp.text.strip().split("\n") if line]
    assert len(lines) == 2


def test_fetch_rejects_batch_over_the_configured_limit() -> None:
    with TestClient(_app(max_keys_per_request=1)) as client:
        resp = client.post(
            "/v1/documents/fetch",
            json={"keys": ["k" * 44, "j" * 44]},
            headers={"X-Meu-Danfe-Token": "segredo"},
        )
    assert resp.status_code == 413


def test_parse_endpoint_returns_rows_for_posted_xml(fixtures_dir) -> None:
    xml_text = (fixtures_dir / "nfe_multi_det.xml").read_text(encoding="utf-8")
    with TestClient(_app()) as client:
        resp = client.post(
            "/v1/documents/parse", json={"xml": xml_text}, headers={"X-Meu-Danfe-Token": "segredo"}
        )
    assert resp.status_code == 200
    assert len(resp.json()["rows"]) == 3


def test_server_settings_refuses_empty_token() -> None:
    with pytest.raises(ConfigurationError):
        ServerSettings(token="")
