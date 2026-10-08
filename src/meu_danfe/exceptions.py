"""Exception hierarchy for the Meu DANFE client.

ERROR_MESSAGES mirrors the vendor's Portuguese operator-facing text
verbatim; `str(exc)` renders the same "{key}: {msg}" line the original
CLI printed, so logs stay recognisable to a human who already knows
this project.
"""
from __future__ import annotations

import httpx

ERROR_MESSAGES: dict[int, str] = {
    400: "Chave de Acesso inválida.",
    401: "Api-Key não informada ou inválida.",
    402: "Saldo insuficiente. Para adicionar créditos acesse a Área do Cliente.",
    403: "Api-Key foi substituida. Acesse a Área do Cliente no menu API / Integração.",
    404: "NF-e/CT-e não encontrada na sua Área do Cliente. Favor adiciona-la antes do download.",
    500: "Erro ao solicitar download do XML! Confira em sua Área do Cliente no menu Minhas NFs / Minhas CTs, o NF-e/CT-e adicionada.",
}


class MeuDanfeError(Exception):
    """Base for every exception this package raises."""


class ConfigurationError(MeuDanfeError):
    """Client or server misconfigured (missing api_key, unsafe pacing, missing token, ...)."""


class MissingDependencyError(MeuDanfeError, ImportError):
    """An optional extra (pdf/excel/dotenv/server) isn't installed."""


class InvalidAccessKeyError(MeuDanfeError, ValueError):
    """A 44-digit access key failed structural validation."""

    def __init__(self, key: str, reason: str) -> None:
        self.key = key
        self.reason = reason
        super().__init__(f"{key}: {reason}")


class MalformedResponseError(MeuDanfeError):
    """The API returned a body this client cannot interpret."""


class TransportError(MeuDanfeError):
    """A network-level failure (timeout, connection error) talking to the API."""


class PollTimeoutError(MeuDanfeError):
    """wait_for exceeded max_polls without reaching a terminal status."""

    def __init__(self, key: str, polls: int, last_status: object) -> None:
        self.key = key
        self.polls = polls
        self.last_status = last_status
        super().__init__(
            f"{key}: não chegou a um status terminal após {polls} consulta(s); "
            f"último status: {last_status}"
        )


class DocumentUnavailableError(MeuDanfeError):
    """Marker base: there is no XML to download for this key.

    Deliberately has NO custom __init__ — subclasses that also inherit
    from MeuDanfeAPIError (which does define one) would hit a signature
    mismatch under cooperative super() chaining otherwise.
    """


class NotFoundStatusError(DocumentUnavailableError):
    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"{key}: NOT_FOUND — não encontrado ou não existe.")


class SearchFailedError(DocumentUnavailableError):
    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"{key}: ERROR — falha ao consultar.")


class MeuDanfeAPIError(MeuDanfeError):
    """An HTTP-level error response from the Meu DANFE API."""

    def __init__(self, key: str, status_code: int, message: str, response: httpx.Response) -> None:
        self.key = key
        self.status_code = status_code
        self.message = message
        self.response = response
        super().__init__(f"{key}: {message}")


class InvalidKeyResponseError(MeuDanfeAPIError):
    pass


class AuthenticationError(MeuDanfeAPIError):
    pass


class InsufficientBalanceError(MeuDanfeAPIError):
    pass


class ApiKeyReplacedError(MeuDanfeAPIError):
    pass


class DocumentNotFoundError(MeuDanfeAPIError, DocumentUnavailableError):
    def __init__(self, key: str, status_code: int, message: str, response: httpx.Response) -> None:
        # Deliberately bypasses cooperative super() — see the class docstring
        # on DocumentUnavailableError for why.
        self.key = key
        self.status_code = status_code
        self.message = message
        self.response = response
        Exception.__init__(self, f"{key}: {message}")


class DownloadRequestError(MeuDanfeAPIError):
    pass


class UnexpectedStatusError(MeuDanfeAPIError):
    pass


_STATUS_EXCEPTIONS: dict[int, type[MeuDanfeAPIError]] = {
    400: InvalidKeyResponseError,
    401: AuthenticationError,
    402: InsufficientBalanceError,
    403: ApiKeyReplacedError,
    404: DocumentNotFoundError,
    500: DownloadRequestError,
}


def error_from_response(key: str, response: httpx.Response) -> MeuDanfeAPIError:
    status_code = response.status_code
    message = ERROR_MESSAGES.get(status_code, f"HTTP {status_code}: {response.reason_phrase}")
    exc_class = _STATUS_EXCEPTIONS.get(status_code, UnexpectedStatusError)
    return exc_class(key, status_code, message, response)
