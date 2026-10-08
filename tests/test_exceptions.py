import httpx
import pytest

from meu_danfe.exceptions import (
    ApiKeyReplacedError,
    AuthenticationError,
    DocumentNotFoundError,
    DocumentUnavailableError,
    DownloadRequestError,
    ERROR_MESSAGES,
    InsufficientBalanceError,
    InvalidKeyResponseError,
    MeuDanfeAPIError,
    MeuDanfeError,
    NotFoundStatusError,
    PollTimeoutError,
    SearchFailedError,
    UnexpectedStatusError,
    error_from_response,
)


def _response(status_code: int) -> httpx.Response:
    request = httpx.Request("GET", "https://api.meudanfe.com.br/v2/fd/add/x")
    return httpx.Response(status_code, request=request, json={"status": "ERROR"})


@pytest.mark.parametrize(
    ("status_code", "expected_class"),
    [
        (400, InvalidKeyResponseError),
        (401, AuthenticationError),
        (402, InsufficientBalanceError),
        (403, ApiKeyReplacedError),
        (404, DocumentNotFoundError),
        (500, DownloadRequestError),
    ],
)
def test_error_from_response_maps_status_to_class_with_verbatim_message(status_code, expected_class):
    exc = error_from_response("k" * 44, _response(status_code))
    assert isinstance(exc, expected_class)
    assert isinstance(exc, MeuDanfeAPIError)
    assert exc.message == ERROR_MESSAGES[status_code]
    assert str(exc) == f"{'k' * 44}: {ERROR_MESSAGES[status_code]}"


def test_error_from_response_unknown_status_is_unexpected():
    exc = error_from_response("k" * 44, _response(599))
    assert isinstance(exc, UnexpectedStatusError)
    assert isinstance(exc, MeuDanfeAPIError)


def test_document_not_found_is_also_document_unavailable():
    exc = error_from_response("k" * 44, _response(404))
    assert isinstance(exc, DocumentUnavailableError)
    assert isinstance(exc, MeuDanfeAPIError)
    assert exc.status_code == 404


def test_not_found_status_error_message():
    exc = NotFoundStatusError("k" * 44)
    assert isinstance(exc, DocumentUnavailableError)
    assert "NOT_FOUND" in str(exc)


def test_search_failed_error_message():
    exc = SearchFailedError("k" * 44)
    assert isinstance(exc, DocumentUnavailableError)
    assert "ERROR" in str(exc)


def test_poll_timeout_error_carries_context():
    exc = PollTimeoutError(key="k" * 44, polls=30, last_status="SEARCHING")
    assert exc.polls == 30
    assert exc.last_status == "SEARCHING"


def test_all_error_messages_map_to_a_class():
    for status_code, message in ERROR_MESSAGES.items():
        exc = error_from_response("k" * 44, _response(status_code))
        assert exc.message == message
        assert isinstance(exc, MeuDanfeError)
