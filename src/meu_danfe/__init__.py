"""Cliente da API Meu DANFE + extrator de dados de XML NFe/CT-e.

Nada neste pacote toca em os.environ ou no disco em tempo de import —
MeuDanfeConfig.from_env() é o único ponto de leitura de ambiente, e só
quando chamado explicitamente.
"""
from __future__ import annotations

import logging

from meu_danfe.client import MeuDanfeAsyncClient
from meu_danfe.config import MeuDanfeConfig
from meu_danfe.exceptions import (
    ApiKeyReplacedError,
    AuthenticationError,
    ConfigurationError,
    DocumentNotFoundError,
    DocumentUnavailableError,
    DownloadRequestError,
    InsufficientBalanceError,
    InvalidAccessKeyError,
    InvalidKeyResponseError,
    MalformedResponseError,
    MeuDanfeAPIError,
    MeuDanfeError,
    MissingDependencyError,
    NotFoundStatusError,
    PollTimeoutError,
    SearchFailedError,
    TransportError,
    UnexpectedStatusError,
)
from meu_danfe.models import AddResult, DocumentStatus, FetchResult, XmlDocument
from meu_danfe.sync_client import MeuDanfeClient

logging.getLogger("meu_danfe").addHandler(logging.NullHandler())

__version__ = "0.1.0"

__all__ = [
    "AddResult",
    "ApiKeyReplacedError",
    "AuthenticationError",
    "ConfigurationError",
    "DocumentNotFoundError",
    "DocumentStatus",
    "DocumentUnavailableError",
    "DownloadRequestError",
    "FetchResult",
    "InsufficientBalanceError",
    "InvalidAccessKeyError",
    "InvalidKeyResponseError",
    "MalformedResponseError",
    "MeuDanfeAPIError",
    "MeuDanfeAsyncClient",
    "MeuDanfeClient",
    "MeuDanfeConfig",
    "MeuDanfeError",
    "MissingDependencyError",
    "NotFoundStatusError",
    "PollTimeoutError",
    "SearchFailedError",
    "TransportError",
    "UnexpectedStatusError",
    "XmlDocument",
    "__version__",
]
