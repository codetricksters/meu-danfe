# meu_danfe Library Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `meu-danfe-downloader` into an installable `meu_danfe` library (client + parser + PDF key extraction), with the existing CLIs as thin wrappers and an optional local HTTP server, so another tool can consume it without a subprocess or reimplementing its logic.

**Architecture:** `src/meu_danfe/` package, async client (`MeuDanfeAsyncClient`) as the canonical implementation with a thin sync facade (`MeuDanfeClient`) running the same async code on a dedicated background event loop. A `KeyPacer` encapsulates the vendor's ≥1s-per-key rule across every endpoint. Typed exceptions replace `print`+`None`. `argparse` CLIs and an optional FastAPI server are callers of the library, not holders of logic.

**Tech Stack:** Python ≥3.12, httpx (async HTTP), xmltodict (XML parsing), pytest + pytest-asyncio + httpx.MockTransport (tests, no real network), hatchling (build backend). Optional extras: pandas+openpyxl (excel), pymupdf (pdf), python-dotenv (dotenv), fastapi+uvicorn (server).

**Spec:** `docs/superpowers/specs/2026-10-08-meu-danfe-library-refactor-design.md` — read its Addendum first; it corrects the original test-baseline plan.

## Global Constraints

- `requires-python` ends at `>=3.12` (Task 17); develop against whatever `uv` resolves (3.14) until then — nothing in this plan uses 3.13/3.14-only syntax.
- Zero dependency on, or knowledge of, any other project (e.g. `uau`). The library never imports anything consumer-specific.
- Core runtime dependencies are `httpx` and `xmltodict` only. `pandas`/`openpyxl`, `pymupdf`, `python-dotenv`, `fastapi`/`uvicorn` are optional extras (`excel`, `pdf`, `dotenv`, `server`).
- `ERROR_MESSAGES` Portuguese strings are preserved byte-for-byte from `app.py`'s current dict (400/401/402/403/404/500).
- Pacing default is `min_key_interval = 1.0` seconds; a client/pacer refuses anything lower unless `allow_unsafe_interval=True` is passed explicitly.
- **No code in `src/meu_danfe/` touches `os.environ` or the filesystem at import time.** `MeuDanfeConfig.from_env()` / `ServerSettings.from_env()` are the only env readers, and only when called explicitly.
- CLI flags preserved exactly: `download` keeps `--key`/`--file` (mutually exclusive, required), `--save`, `--out`/`-o`; `to_excel` keeps `--source`/`--file` (mutually exclusive, required), `--name` (required), `--out`.
- The HTTP server binds `127.0.0.1` by default, refuses to start without `MEU_DANFE_SERVER_TOKEN` configured, and refuses a non-loopback bind without an explicit `--allow-remote`.
- No test may reach the real network — every real query against Meu DANFE costs R$0,03. All client/server tests use `httpx.MockTransport`.
- Legacy root scripts (`app.py`, `xml_to_excel.py`, `pdf_key_extractor.py`, `filter_files.py`) are deleted as soon as the task that absorbs their logic is green — not kept as compatibility shims. No consumer depends on them yet (confirmed during brainstorming).

## Review Focus

- **Path-traversal `name` from the API.** `get_xml`'s JSON payload has a `name` field the vendor controls; a value like `../../etc/passwd` or `/etc/passwd` must still land strictly inside the caller's `out_dir`, never escape it. Covered in Task 4.
- **One failing key must not take down a batch.** A `httpx.ConnectError`/`TransportError` on one key inside `fetch_many`/`iter_fetch` must surface as that key's `FetchResult.error`, not cancel or lose the other keys' results. Covered in Task 9.
- **A single `<det>` item collapses to a dict without `force_list`.** `xmltodict.parse` turns a lone repeated-tag element into a bare dict, not a one-item list — a parser that forgets `force_list=("det",)` silently returns zero rows for a one-line invoice. Covered in Task 7.
- **A terminal-looking response with no usable `status`.** A non-JSON body, or JSON missing the `status` key, must raise `MalformedResponseError`, never loop forever (the original `app.py` bug: `None not in TERMINAL_STATUSES` spins) and never raise an unrelated `KeyError`/`AttributeError`. Covered in Task 9.
- **Pacing must survive across sync calls, not just within one.** Two sequential `MeuDanfeClient.fetch()` calls for the *same* key must still be ≥1s apart — the one way a naive `asyncio.run()`-per-call sync facade would silently violate the vendor's rate limit. Covered in Task 10.

---

### Task 1: Package skeleton and build system

**Files:**
- Modify: `pyproject.toml` (full rewrite)
- Create: `src/meu_danfe/__init__.py`
- Create: `src/meu_danfe/py.typed`
- Create: `tests/conftest.py`
- Create: `tests/test_smoke.py`

**Interfaces:**
- Produces: an installable `meu_danfe` package namespace; a `tests/conftest.py` with a `no_real_network` autouse fixture, a `FakeClock` class, and a `fixtures_dir` fixture that every later task's tests use.

**Scaffolding exception:** this task has no meaningful prior "RED" behaviour to watch fail (there's no package yet to import), so its RED step is "the build doesn't exist" rather than a failing assertion. Ledger this as an accepted deviation from strict TDD for pure scaffolding — do not generalize it to later tasks.

- [ ] **Step 1: Rewrite `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[project]
name = "meu-danfe-downloader"
version = "0.1.0"
description = "Cliente da API Meu DANFE + extrator de dados de XML NFe/CT-e"
readme = "README.md"
requires-python = ">=3.14"
dependencies = [
    "httpx>=0.28.1",
    "xmltodict>=1.0.4",
]

[project.optional-dependencies]
excel = ["pandas>=3.0.2", "openpyxl>=3.1.5"]
pdf = ["pymupdf>=1.27.2.3"]
dotenv = ["python-dotenv>=1.2.2"]
server = ["fastapi>=0.115", "uvicorn>=0.30"]
cli = ["meu-danfe-downloader[excel,pdf,dotenv]"]
all = ["meu-danfe-downloader[cli,server]"]

[project.scripts]
meu-danfe = "meu_danfe.cli.download:main"
meu-danfe-download = "meu_danfe.cli.download:main"
meu-danfe-to-excel = "meu_danfe.cli.to_excel:main"
meu-danfe-pdf-keys = "meu_danfe.cli.pdf_keys:main"

[tool.hatch.build.targets.wheel]
packages = ["src/meu_danfe"]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "ipython>=9.13.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

(`requires-python` stays `>=3.14` until Task 17 — lowering it early would mean developing against two floors at once for no benefit.)

- [ ] **Step 2: Create the package directory and marker files**

`src/meu_danfe/__init__.py`:
```python
"""Cliente da API Meu DANFE + extrator de dados de XML NFe/CT-e."""
```

`src/meu_danfe/py.typed`: empty file (PEP 561 marker).

- [ ] **Step 3: `uv sync` and confirm the package imports**

Run: `uv sync && uv run python -c "import meu_danfe; print(meu_danfe.__doc__)"`
Expected: sync succeeds (editable install of `meu_danfe`); prints the docstring. (This is the task's actual "did scaffolding work" check, standing in for a RED→GREEN pair.)

- [ ] **Step 4: Write `tests/conftest.py`**

```python
"""Shared pytest fixtures for the meu_danfe test suite.

No test here may reach the real network: every real query against the
Meu DANFE API costs R$ 0,03, so an autouse fixture patches httpx's real
transport classes to raise if anything tries. httpx.MockTransport is a
different class and is unaffected.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "A test attempted a real network request. Use httpx.MockTransport instead."
        )

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _forbidden, raising=True)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _forbidden, raising=True)


class FakeClock:
    """A controllable monotonic clock + async sleep for pacing tests.

    `now` only advances when `sleep()` is awaited, so tests assert
    elapsed time without ever actually waiting.
    """

    def __init__(self, start: float = 0.0) -> None:
        self.now = start
        self.sleep_calls: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        if seconds > 0:
            self.now += seconds


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
```

- [ ] **Step 5: Write `tests/test_smoke.py`**

```python
def test_package_importable() -> None:
    import meu_danfe  # noqa: F401
```

- [ ] **Step 6: Run the suite**

Run: `uv run pytest -q`
Expected: `1 passed`

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/meu_danfe/__init__.py src/meu_danfe/py.typed tests/conftest.py tests/test_smoke.py
git commit -m "feat: package skeleton — meu_danfe is importable"
```

---

### Task 2: Exception hierarchy

**Files:**
- Create: `src/meu_danfe/exceptions.py`
- Test: `tests/test_exceptions.py`

**Interfaces:**
- Produces: `MeuDanfeError` and the full tree below it; `ERROR_MESSAGES: dict[int, str]`; `error_from_response(key: str, response: httpx.Response) -> MeuDanfeAPIError`. Every later task that raises an API-facing error imports from here.

```
MeuDanfeError
├── ConfigurationError
├── MissingDependencyError (+ImportError)
├── InvalidAccessKeyError (+ValueError)
├── MalformedResponseError
├── TransportError
├── PollTimeoutError(key, polls, last_status)
├── DocumentUnavailableError                 # marker, no custom __init__
│   ├── NotFoundStatusError(key)
│   └── SearchFailedError(key)
└── MeuDanfeAPIError(key, status_code, message, response)
    ├── InvalidKeyResponseError   (400)
    ├── AuthenticationError       (401)
    ├── InsufficientBalanceError  (402)
    ├── ApiKeyReplacedError       (403)
    ├── DocumentNotFoundError (+DocumentUnavailableError) (404)
    ├── DownloadRequestError      (500)
    └── UnexpectedStatusError     (anything else)
```

`DocumentNotFoundError` inherits from both `MeuDanfeAPIError` and `DocumentUnavailableError`. Both parents define incompatible `__init__` signatures, so `DocumentNotFoundError.__init__` does NOT call `super().__init__(...)` cooperatively — it sets its own attributes and calls `Exception.__init__` directly. This is deliberate; do not "simplify" it to a `super()` call, which would raise `TypeError` on the signature mismatch.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_exceptions.py
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_exceptions.py -q`
Expected: `ModuleNotFoundError: No module named 'meu_danfe.exceptions'`

- [ ] **Step 3: Write `src/meu_danfe/exceptions.py`**

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_exceptions.py -q`
Expected: all tests `passed`

- [ ] **Step 5: Commit**

```bash
git add src/meu_danfe/exceptions.py tests/test_exceptions.py
git commit -m "feat: exception hierarchy with verbatim vendor error messages"
```

---

### Task 3: Config

**Files:**
- Create: `src/meu_danfe/config.py`
- Test: `tests/test_config.py`, `tests/test_import_without_env.py`

**Interfaces:**
- Consumes: `ConfigurationError`, `MissingDependencyError` from Task 2.
- Produces: `MeuDanfeConfig` (frozen dataclass: `api_key, base_url, timeout, max_concurrency, min_key_interval, max_polls, allow_unsafe_interval`), `MeuDanfeConfig.from_env(...)`, `DEFAULT_BASE_URL`, `DEFAULT_TIMEOUT`, `DEFAULT_MAX_CONCURRENCY`, `MIN_KEY_INTERVAL`, `DEFAULT_MAX_POLLS`. Tasks 9/10/16 build their client/server from a `MeuDanfeConfig`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_import_without_env.py
"""The single most important regression test in this plan: importing the
package, and building a config without one, must never raise KeyError —
the exact bug app.py has today at module scope."""
import importlib

import pytest


def test_import_does_not_touch_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("MEU_DANFE_API_KEY", "MEU_DANFE_API_URL"):
        monkeypatch.delenv(name, raising=False)
    import meu_danfe
    importlib.reload(meu_danfe)  # a fresh import must not raise


def test_from_env_raises_configuration_error_not_keyerror() -> None:
    from meu_danfe.config import MeuDanfeConfig
    from meu_danfe.exceptions import ConfigurationError

    with pytest.raises(ConfigurationError):
        MeuDanfeConfig.from_env(env={})
```

```python
# tests/test_config.py
import pytest

from meu_danfe.config import DEFAULT_BASE_URL, MeuDanfeConfig
from meu_danfe.exceptions import ConfigurationError


def test_explicit_api_key_requires_no_environment() -> None:
    config = MeuDanfeConfig(api_key="minha-chave")
    assert config.base_url == DEFAULT_BASE_URL
    assert config.min_key_interval == 1.0


def test_blank_api_key_raises_configuration_error() -> None:
    with pytest.raises(ConfigurationError):
        MeuDanfeConfig(api_key="")


def test_base_url_without_trailing_slash_gets_one() -> None:
    config = MeuDanfeConfig(api_key="x", base_url="https://api.meudanfe.com.br/v2")
    assert config.base_url == "https://api.meudanfe.com.br/v2/"


def test_min_key_interval_below_one_second_rejected_by_default() -> None:
    with pytest.raises(ConfigurationError):
        MeuDanfeConfig(api_key="x", min_key_interval=0.1)


def test_min_key_interval_below_one_second_allowed_when_opted_in() -> None:
    config = MeuDanfeConfig(api_key="x", min_key_interval=0.1, allow_unsafe_interval=True)
    assert config.min_key_interval == 0.1


def test_repr_masks_api_key() -> None:
    config = MeuDanfeConfig(api_key="segredo-super-secreto")
    assert "segredo-super-secreto" not in repr(config)
    assert "creto" in repr(config)  # last 4 chars kept for operator disambiguation


def test_from_env_reads_prefixed_variables() -> None:
    env = {"MEU_DANFE_API_KEY": "chave-do-ambiente", "MEU_DANFE_API_URL": "https://example.test/v2/"}
    config = MeuDanfeConfig.from_env(env=env)
    assert config.api_key == "chave-do-ambiente"
    assert config.base_url == "https://example.test/v2/"


def test_from_env_explicit_api_key_overrides_environment() -> None:
    config = MeuDanfeConfig.from_env(env={"MEU_DANFE_API_KEY": "do-ambiente"}, api_key="explicita")
    assert config.api_key == "explicita"


def test_from_env_without_dotenv_path_never_imports_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    monkeypatch.setitem(sys.modules, "dotenv", None)  # import dotenv would now raise
    config = MeuDanfeConfig.from_env(env={"MEU_DANFE_API_KEY": "x"})
    assert config.api_key == "x"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_config.py tests/test_import_without_env.py -q`
Expected: `ModuleNotFoundError: No module named 'meu_danfe.config'`

- [ ] **Step 3: Write `src/meu_danfe/config.py`**

```python
"""Configuration for the Meu DANFE client.

Nothing in this module touches os.environ or the filesystem at import
time: `MeuDanfeConfig.from_env` is the ONLY place environment or dotenv
values are read, and only when a caller invokes it explicitly.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from meu_danfe.exceptions import ConfigurationError, MissingDependencyError

DEFAULT_BASE_URL = "https://api.meudanfe.com.br/v2/"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_CONCURRENCY = 10
MIN_KEY_INTERVAL = 1.0
DEFAULT_MAX_POLLS = 30


@dataclass(frozen=True, slots=True)
class MeuDanfeConfig:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    timeout: float = DEFAULT_TIMEOUT
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY
    min_key_interval: float = MIN_KEY_INTERVAL
    max_polls: int = DEFAULT_MAX_POLLS
    allow_unsafe_interval: bool = False

    def __post_init__(self) -> None:
        if not self.api_key or not self.api_key.strip():
            raise ConfigurationError(
                "MEU_DANFE_API_KEY não definida. Passe api_key= explicitamente "
                "ou defina a variável de ambiente MEU_DANFE_API_KEY."
            )
        base_url = self.base_url or DEFAULT_BASE_URL
        if not base_url.endswith("/"):
            base_url = base_url + "/"
        object.__setattr__(self, "base_url", base_url)
        if self.max_concurrency < 1:
            raise ConfigurationError("max_concurrency precisa ser >= 1.")
        if self.min_key_interval < MIN_KEY_INTERVAL and not self.allow_unsafe_interval:
            raise ConfigurationError(
                "min_key_interval abaixo de 1.0s viola a regra do fornecedor "
                "(chaves repetidas em menos de 1s bloqueiam a conta). "
                "Passe allow_unsafe_interval=True para forçar."
            )

    def __repr__(self) -> str:
        masked = f"***{self.api_key[-4:]}" if len(self.api_key) > 4 else "***"
        return (
            f"MeuDanfeConfig(api_key={masked!r}, base_url={self.base_url!r}, "
            f"timeout={self.timeout}, max_concurrency={self.max_concurrency}, "
            f"min_key_interval={self.min_key_interval}, max_polls={self.max_polls})"
        )

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        prefix: str = "MEU_DANFE_",
        dotenv_path: Any | None = None,
        **overrides: Any,
    ) -> "MeuDanfeConfig":
        if env is None:
            import os
            env = os.environ

        merged: dict[str, str] = dict(env)
        if dotenv_path is not None:
            try:
                from dotenv import dotenv_values
            except ImportError as exc:
                raise MissingDependencyError(
                    'dotenv_path foi passado, mas python-dotenv não está instalado. '
                    'Instale com: pip install "meu-danfe-downloader[dotenv]"'
                ) from exc
            file_values = {k: v for k, v in dotenv_values(dotenv_path).items() if v is not None}
            merged = {**file_values, **merged}

        api_key = overrides.pop("api_key", None) or merged.get(f"{prefix}API_KEY")
        if not api_key:
            raise ConfigurationError(
                f"{prefix}API_KEY não definida. Passe api_key= explicitamente, "
                f"defina a variável de ambiente {prefix}API_KEY, ou passe dotenv_path=."
            )
        kwargs: dict[str, Any] = {"api_key": api_key}
        if url := merged.get(f"{prefix}API_URL"):
            kwargs["base_url"] = url
        kwargs.update(overrides)
        return cls(**kwargs)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_config.py tests/test_import_without_env.py -q`
Expected: all tests `passed`

- [ ] **Step 5: Commit**

```bash
git add src/meu_danfe/config.py tests/test_config.py tests/test_import_without_env.py
git commit -m "feat: MeuDanfeConfig — explicit-first config, no import-time env access"
```

---

### Task 4: Models and storage

**Files:**
- Create: `src/meu_danfe/storage.py`
- Create: `src/meu_danfe/models.py`
- Test: `tests/test_storage.py`, `tests/test_models.py`

**Interfaces:**
- Produces: `storage.sanitize_filename(name, *, fallback) -> str`, `storage.save_xml(document, out_dir, *, filename=None, overwrite=False) -> Path`; `models.DocumentStatus` (StrEnum: WAITING/SEARCHING/NOT_FOUND/OK/ERROR, `.is_terminal`, `.is_success`), `models.AddResult(key, status, raw)`, `models.XmlDocument(key, name, doc_type, content_format, data, raw)` with `.safe_filename` and `.write_to(out_dir, *, filename=None, overwrite=False)`, `models.FetchResult(key, status, document, error, polls)` with `.ok`.
- `storage.py` only imports `models` under `TYPE_CHECKING` (storage must be importable without models, since models imports storage at runtime) — do not turn this into a real import, it would create a circular import.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_storage.py
from meu_danfe.storage import sanitize_filename


def test_sanitize_filename_strips_directory_components() -> None:
    assert sanitize_filename("../../etc/passwd", fallback="x.xml") == "passwd"
    assert sanitize_filename("/etc/passwd", fallback="x.xml") == "passwd"


def test_sanitize_filename_strips_unsafe_characters() -> None:
    assert sanitize_filename('weird:name?.xml', fallback="x.xml") == "weird_name_.xml"


def test_sanitize_filename_falls_back_on_empty_result() -> None:
    assert sanitize_filename("...", fallback="fallback.xml") == "fallback.xml"
```

```python
# tests/test_models.py
import pytest

from meu_danfe.models import DocumentStatus, FetchResult, XmlDocument


@pytest.mark.parametrize(
    ("status", "terminal", "success"),
    [
        (DocumentStatus.WAITING, False, False),
        (DocumentStatus.SEARCHING, False, False),
        (DocumentStatus.NOT_FOUND, True, False),
        (DocumentStatus.OK, True, True),
        (DocumentStatus.ERROR, True, False),
    ],
)
def test_document_status_terminal_and_success(status, terminal, success) -> None:
    assert status.is_terminal is terminal
    assert status.is_success is success


def _document(name: str) -> XmlDocument:
    return XmlDocument(key="k" * 44, name=name, doc_type="NFE", content_format="XML", data="<x/>", raw={})


def test_write_to_neutralizes_relative_path_traversal_name(tmp_path) -> None:
    out_dir = tmp_path / "xmls"
    path = _document("../../etc/passwd").write_to(out_dir)
    assert path.parent.resolve() == out_dir.resolve()
    assert path.name == "passwd"
    assert not (tmp_path / "etc").exists()


def test_write_to_neutralizes_absolute_path_name(tmp_path) -> None:
    out_dir = tmp_path / "xmls"
    path = _document("/etc/passwd").write_to(out_dir)
    assert path.parent.resolve() == out_dir.resolve()
    assert path.name == "passwd"


def test_write_to_refuses_overwrite_by_default(tmp_path) -> None:
    out_dir = tmp_path / "xmls"
    doc = _document("nota.xml")
    doc.write_to(out_dir)
    with pytest.raises(FileExistsError):
        doc.write_to(out_dir)
    doc.write_to(out_dir, overwrite=True)  # does not raise


def test_fetch_result_ok_reflects_document_presence() -> None:
    doc = _document("n.xml")
    assert FetchResult(key="k", status=DocumentStatus.OK, document=doc, error=None, polls=1).ok is True
    assert FetchResult(key="k", status=DocumentStatus.NOT_FOUND, document=None, error=None, polls=1).ok is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_storage.py tests/test_models.py -q`
Expected: `ModuleNotFoundError: No module named 'meu_danfe.storage'`

- [ ] **Step 3: Write `src/meu_danfe/storage.py`**

```python
"""Writing downloaded XML to disk, with filenames the vendor's `name`
field can never use to escape the destination directory."""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from meu_danfe.models import XmlDocument

_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def sanitize_filename(name: str, *, fallback: str) -> str:
    """Reduce an API-supplied filename to a bare name with no path
    components, so it can never escape the destination directory."""
    candidate = Path(name).name  # drops any "/" or "\" directory components
    candidate = _UNSAFE_CHARS.sub("_", candidate).strip(". ")
    return candidate or fallback


def save_xml(
    document: "XmlDocument", out_dir: Path, *, filename: str | None = None, overwrite: bool = False
) -> Path:
    name = sanitize_filename(filename or document.name, fallback=f"{document.key}.xml")
    out_dir.mkdir(parents=True, exist_ok=True)
    resolved_dir = out_dir.resolve()
    path = out_dir / name
    if path.resolve().parent != resolved_dir:
        # Defense in depth: sanitize_filename should already guarantee this.
        raise ValueError(f"nome de arquivo resolvido fora do diretório de destino: {name!r}")
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} já existe (passe overwrite=True para sobrescrever)")
    path.write_text(document.data, encoding="utf-8")
    return path
```

- [ ] **Step 4: Write `src/meu_danfe/models.py`**

```python
"""Typed values the client returns, instead of raw httpx.Response."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from meu_danfe.storage import save_xml, sanitize_filename

if TYPE_CHECKING:
    from meu_danfe.exceptions import MeuDanfeError


class DocumentStatus(StrEnum):
    WAITING = "WAITING"
    SEARCHING = "SEARCHING"
    NOT_FOUND = "NOT_FOUND"
    OK = "OK"
    ERROR = "ERROR"

    @property
    def is_terminal(self) -> bool:
        return self in (DocumentStatus.NOT_FOUND, DocumentStatus.OK, DocumentStatus.ERROR)

    @property
    def is_success(self) -> bool:
        return self is DocumentStatus.OK


@dataclass(frozen=True, slots=True)
class AddResult:
    key: str
    status: DocumentStatus
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class XmlDocument:
    key: str
    name: str
    doc_type: str
    content_format: str
    data: str
    raw: Mapping[str, Any]

    @property
    def safe_filename(self) -> str:
        return sanitize_filename(self.name, fallback=f"{self.key}.xml")

    def write_to(self, out_dir: Path, *, filename: str | None = None, overwrite: bool = False) -> Path:
        return save_xml(self, out_dir, filename=filename, overwrite=overwrite)


@dataclass(frozen=True, slots=True)
class FetchResult:
    key: str
    status: DocumentStatus | None
    document: XmlDocument | None
    error: "MeuDanfeError | None"
    polls: int

    @property
    def ok(self) -> bool:
        return self.document is not None
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_storage.py tests/test_models.py -q`
Expected: all tests `passed`

- [ ] **Step 6: Commit**

```bash
git add src/meu_danfe/storage.py src/meu_danfe/models.py tests/test_storage.py tests/test_models.py
git commit -m "feat: typed models (DocumentStatus/AddResult/XmlDocument/FetchResult) and safe storage"
```

---

### Task 5: KeyPacer

**Files:**
- Create: `src/meu_danfe/pacing.py`
- Test: `tests/test_pacing.py`

**Interfaces:**
- Consumes: `ConfigurationError` from Task 2; `FakeClock` fixture from Task 1.
- Produces: `KeyPacer(min_interval=1.0, *, max_concurrency=10, clock=time.monotonic, sleep=asyncio.sleep, max_tracked_keys=4096, allow_unsafe_interval=False)` with `async with pacer.slot(key): ...`. Task 9's client wraps every HTTP call in `pacer.slot(key)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pacing.py
import asyncio

import pytest

from meu_danfe.exceptions import ConfigurationError
from meu_danfe.pacing import KeyPacer


async def test_same_key_waits_at_least_min_interval(fake_clock) -> None:
    pacer = KeyPacer(min_interval=1.0, clock=fake_clock.clock, sleep=fake_clock.sleep)
    key = "k" * 44
    async with pacer.slot(key):
        pass
    start = fake_clock.now
    async with pacer.slot(key):
        pass
    assert fake_clock.now - start >= 1.0


async def test_different_keys_do_not_wait_for_each_other(fake_clock) -> None:
    pacer = KeyPacer(min_interval=1.0, clock=fake_clock.clock, sleep=fake_clock.sleep)
    async with pacer.slot("k" * 44):
        pass
    before = fake_clock.now
    async with pacer.slot("j" * 44):
        pass
    assert fake_clock.now == before  # no sleep needed for a different key


async def test_max_concurrency_bounds_in_flight_slots(fake_clock) -> None:
    pacer = KeyPacer(min_interval=0.0, max_concurrency=2, clock=fake_clock.clock, sleep=fake_clock.sleep,
                      allow_unsafe_interval=True)
    peak = 0
    current = 0

    async def worker(key: str) -> None:
        nonlocal peak, current
        async with pacer.slot(key):
            current += 1
            peak = max(peak, current)
            await asyncio.sleep(0)
            current -= 1

    await asyncio.gather(*(worker(f"key-{i}") for i in range(5)))
    assert peak <= 2


def test_min_interval_below_one_second_rejected_by_default() -> None:
    with pytest.raises(ConfigurationError):
        KeyPacer(min_interval=0.1)


def test_min_interval_below_one_second_allowed_when_opted_in() -> None:
    KeyPacer(min_interval=0.1, allow_unsafe_interval=True)  # does not raise


async def test_pruning_does_not_evict_a_held_lock(fake_clock) -> None:
    pacer = KeyPacer(min_interval=0.0, max_tracked_keys=2, clock=fake_clock.clock, sleep=fake_clock.sleep,
                      allow_unsafe_interval=True)
    for i in range(5):
        async with pacer.slot(f"key-{i}"):
            pass
    # No assertion beyond "did not raise" / did not grow unbounded — pruning
    # is a memory-bound guard, not user-visible behaviour.
    assert len(pacer._key_locks) <= 3  # a little slack is fine; unbounded growth is not
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_pacing.py -q`
Expected: `ModuleNotFoundError: No module named 'meu_danfe.pacing'`

- [ ] **Step 3: Write `src/meu_danfe/pacing.py`**

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_pacing.py -q`
Expected: all tests `passed`

- [ ] **Step 5: Commit**

```bash
git add src/meu_danfe/pacing.py tests/test_pacing.py
git commit -m "feat: KeyPacer — unbypassable >=1s-per-key pacing + bounded concurrency"
```

---

### Task 6: Access key utilities

**Files:**
- Create: `src/meu_danfe/keys.py`
- Test: `tests/test_keys.py`

**Interfaces:**
- Consumes: `InvalidAccessKeyError` from Task 2.
- Produces: `ACCESS_KEY_RE`, `normalize_key(raw) -> str`, `is_valid_key(raw) -> bool`, `validate_key(raw) -> str` (raises), `load_keys(path) -> list[str]`, `existing_keys_in_dir(directory, *, pattern="*.xml") -> set[str]`. Task 8 (`pdf.py`) uses `normalize_key`; Task 13 (`cli/download.py`) uses `load_keys` and `existing_keys_in_dir`.
- Scope note: checksum (mod-11 check digit) validation is deliberately NOT implemented — the spec defers it (a wrong implementation would reject *valid* keys, worse than the R$0,03 it would save).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_keys.py
import pytest

from meu_danfe.exceptions import InvalidAccessKeyError
from meu_danfe.keys import existing_keys_in_dir, is_valid_key, load_keys, normalize_key, validate_key


def _key() -> str:
    return "".join(str(i % 10) for i in range(1, 45))


def test_normalize_key_strips_separators() -> None:
    key = _key()
    spaced = ".".join(key[i : i + 4] for i in range(0, 44, 4))
    assert normalize_key(spaced) == key
    assert normalize_key(f"  {key}  ") == key


def test_is_valid_key_requires_exactly_44_digits() -> None:
    assert is_valid_key(_key()) is True
    assert is_valid_key(_key()[:-1]) is False
    assert is_valid_key(_key() + "0") is False
    assert is_valid_key("not-a-key") is False


def test_validate_key_returns_normalized_or_raises() -> None:
    key = _key()
    assert validate_key(f"{key[:4]}.{key[4:]}") == key
    with pytest.raises(InvalidAccessKeyError):
        validate_key("curta")


def test_load_keys_skips_blank_lines(tmp_path) -> None:
    path = tmp_path / "keys.txt"
    path.write_text(f"{_key()}\n\n   \n{_key()}\n", encoding="utf-8")
    assert load_keys(path) == [_key(), _key()]


def test_existing_keys_in_dir_strips_nfe_prefix(tmp_path) -> None:
    key = _key()
    (tmp_path / f"NFE-{key}.xml").write_text("<x/>", encoding="utf-8")
    (tmp_path / "not-a-key.xml").write_text("<x/>", encoding="utf-8")
    assert existing_keys_in_dir(tmp_path) == {key}
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_keys.py -q`
Expected: `ModuleNotFoundError: No module named 'meu_danfe.keys'`

- [ ] **Step 3: Write `src/meu_danfe/keys.py`**

```python
"""44-digit access key (Chave de Acesso) normalisation and lookup helpers."""
from __future__ import annotations

import re
from pathlib import Path

from meu_danfe.exceptions import InvalidAccessKeyError

ACCESS_KEY_RE = re.compile(r"^\d{44}$")
_STRIP_RE = re.compile(r"[ .\-]")


def normalize_key(raw: str) -> str:
    """Strip spaces, dots and dashes commonly used to group the 44 digits."""
    return _STRIP_RE.sub("", raw.strip())


def is_valid_key(raw: str) -> bool:
    return bool(ACCESS_KEY_RE.match(normalize_key(raw)))


def validate_key(raw: str) -> str:
    key = normalize_key(raw)
    if not ACCESS_KEY_RE.match(key):
        raise InvalidAccessKeyError(raw, f"chave deve ter 44 dígitos, tem {len(key)}")
    return key


def load_keys(path: Path) -> list[str]:
    """One access key per line; blank lines skipped."""
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def existing_keys_in_dir(directory: Path, *, pattern: str = "*.xml") -> set[str]:
    """Access keys already present as downloaded files, e.g. 'NFE-{chave}.xml'
    or '{chave}.xml'. Used to skip keys that would cost R$0,03 to re-fetch."""
    found: set[str] = set()
    for path in directory.glob(pattern):
        candidate = path.stem.split("-", 1)[-1]
        if is_valid_key(candidate):
            found.add(normalize_key(candidate))
    return found
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_keys.py -q`
Expected: all tests `passed`

- [ ] **Step 5: Commit**

```bash
git add src/meu_danfe/keys.py tests/test_keys.py
git commit -m "feat: access key normalisation/validation helpers"
```

---

### Task 7: NFe XML parsing (absorbs `xml_to_excel.py`)

**Files:**
- Create: `src/meu_danfe/nfe/__init__.py`
- Create: `src/meu_danfe/nfe/columns.json` (moved verbatim from root `columns.json`)
- Create: `src/meu_danfe/nfe/columns.py`
- Create: `src/meu_danfe/nfe/parser.py`
- Create: `tests/fixtures/nfe_multi_det.xml`, `tests/fixtures/nfe_single_det.xml`, `tests/fixtures/nfe_sparse.xml`
- Test: `tests/test_parser.py`
- Delete: root `columns.json`, root `xml_to_excel.py`

**Interfaces:**
- Produces: `columns.ColumnMap`, `columns.DET_PLACEHOLDER = 0`, `columns.default_columns() -> ColumnMap`, `columns.load_columns(path) -> ColumnMap`; `parser.parse_xml(source) -> dict`, `parser.extract_rows(document, columns=None) -> list[dict]`, `parser.extract_rows_from_file(path, columns=None) -> list[dict]`, `parser.iter_rows_from_dir(source, columns=None, *, recursive=False, on_error="warn") -> Iterator[tuple[Path, list[dict]]]`. Task 12 (`excel.py`) and Task 14 (`cli/to_excel.py`) consume all of these.
- Review Focus: a single `<det>` must still produce exactly one row (`force_list=("det",)` is non-negotiable — do not remove it "to simplify").

- [ ] **Step 1: Write the three XML fixtures**

`tests/fixtures/nfe_multi_det.xml` (3 `<det>` items):
```xml
<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
  <NFe>
    <infNFe Id="NFe35260100000000000000000000000000000000001" versao="4.00">
      <ide>
        <nNF>123</nNF>
        <serie>1</serie>
        <dhEmi>2026-01-15T10:00:00-03:00</dhEmi>
        <dhSaiEnt>2026-01-16T08:00:00-03:00</dhSaiEnt>
        <natOp>VENDA</natOp>
      </ide>
      <emit>
        <CNPJ>11222333000181</CNPJ>
        <xNome>Emitente Teste LTDA</xNome>
        <enderEmit><UF>SP</UF></enderEmit>
      </emit>
      <dest>
        <CNPJ>99888777000199</CNPJ>
        <xNome>Destinatario Teste LTDA</xNome>
      </dest>
      <det nItem="1">
        <prod>
          <cProd>P001</cProd>
          <xProd>Produto Um</xProd>
          <NCM>12345678</NCM>
          <CFOP>5102</CFOP>
          <uCom>UN</uCom>
          <qCom>2.0000</qCom>
          <vUnCom>10.00</vUnCom>
          <vProd>20.00</vProd>
        </prod>
        <imposto><ICMS><ICMS00><CST>00</CST><vBC>20.00</vBC><pICMS>18.00</pICMS><vICMS>3.60</vICMS></ICMS00></ICMS></imposto>
      </det>
      <det nItem="2">
        <prod>
          <cProd>P002</cProd>
          <xProd>Produto Dois</xProd>
          <NCM>87654321</NCM>
          <CFOP>5102</CFOP>
          <uCom>UN</uCom>
          <qCom>1.0000</qCom>
          <vUnCom>50.00</vUnCom>
          <vProd>50.00</vProd>
        </prod>
        <imposto><ICMS><ICMS00><CST>00</CST><vBC>50.00</vBC><pICMS>18.00</pICMS><vICMS>9.00</vICMS></ICMS00></ICMS></imposto>
      </det>
      <det nItem="3">
        <prod>
          <cProd>P003</cProd>
          <xProd>Produto Tres</xProd>
          <NCM>11223344</NCM>
          <CFOP>5102</CFOP>
          <uCom>UN</uCom>
          <qCom>3.0000</qCom>
          <vUnCom>5.00</vUnCom>
          <vProd>15.00</vProd>
        </prod>
        <imposto><ICMS><ICMS00><CST>00</CST><vBC>15.00</vBC><pICMS>18.00</pICMS><vICMS>2.70</vICMS></ICMS00></ICMS></imposto>
      </det>
      <total>
        <ICMSTot><vNF>85.00</vNF><vProd>85.00</vProd><vFrete>0.00</vFrete><vSeg>0.00</vSeg><vDesc>0.00</vDesc></ICMSTot>
      </total>
      <infAdic><infCpl>Observacoes de teste.</infCpl></infAdic>
    </infNFe>
  </NFe>
  <protNFe><infProt><chNFe>35260100000000000000000000000000000000001</chNFe></infProt></protNFe>
</nfeProc>
```

`tests/fixtures/nfe_single_det.xml`: identical structure but with exactly one `<det nItem="1">` block (copy the first `<det>` from above, drop the other two, adjust `<total>` to `vNF=20.00/vProd=20.00`).

`tests/fixtures/nfe_sparse.xml`: identical to the single-det fixture but with the `<dhSaiEnt>` line and the entire `<infAdic>` block removed.

- [ ] **Step 2: Write `tests/test_parser.py`**

```python
from meu_danfe.nfe.parser import extract_rows, parse_xml


def test_multi_det_produces_one_row_per_item_and_repeats_invoice_fields(fixtures_dir) -> None:
    document = parse_xml(fixtures_dir / "nfe_multi_det.xml")
    rows = extract_rows(document)
    assert len(rows) == 3
    assert {row["Número da Nota"] for row in rows} == {"123"}
    assert [row["Descrição do Produto"] for row in rows] == ["Produto Um", "Produto Dois", "Produto Tres"]


def test_single_det_still_produces_exactly_one_row(fixtures_dir) -> None:
    # Regression for the xmltodict force_list gotcha: without it, a lone
    # <det> collapses to a dict and len() would count dict keys, not rows.
    document = parse_xml(fixtures_dir / "nfe_single_det.xml")
    rows = extract_rows(document)
    assert len(rows) == 1
    assert rows[0]["Código do Produto"] == "P001"


def test_missing_optional_fields_yield_none_not_an_exception(fixtures_dir) -> None:
    document = parse_xml(fixtures_dir / "nfe_sparse.xml")
    rows = extract_rows(document)
    assert rows[0]["Informações Complementares"] is None
    assert rows[0]["Data de Saída/Entrada"] is None


def test_parse_xml_accepts_bytes_with_declared_encoding(fixtures_dir) -> None:
    raw = (fixtures_dir / "nfe_single_det.xml").read_bytes()
    document = parse_xml(raw)
    assert extract_rows(document)[0]["Código do Produto"] == "P001"


def test_extract_rows_accepts_a_custom_column_map(fixtures_dir) -> None:
    document = parse_xml(fixtures_dir / "nfe_multi_det.xml")
    custom = {"produto": ["nfeProc", "NFe", "infNFe", "det", 0, "prod", "xProd"]}
    rows = extract_rows(document, columns=custom)
    assert rows == [{"produto": "Produto Um"}, {"produto": "Produto Dois"}, {"produto": "Produto Tres"}]
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/test_parser.py -q`
Expected: `ModuleNotFoundError: No module named 'meu_danfe.nfe'`

- [ ] **Step 4: Move `columns.json` and write `nfe/columns.py` + `nfe/parser.py`**

```bash
mkdir -p src/meu_danfe/nfe
git mv columns.json src/meu_danfe/nfe/columns.json
touch src/meu_danfe/nfe/__init__.py
```

`src/meu_danfe/nfe/columns.py`:
```python
"""Loading the column-name -> JSON-path map that drives NFe row extraction."""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from functools import cache
from importlib import resources
from pathlib import Path

ColumnMap = Mapping[str, Sequence[str | int]]

DET_PLACEHOLDER: int = 0


@cache
def default_columns() -> ColumnMap:
    text = resources.files("meu_danfe.nfe").joinpath("columns.json").read_text(encoding="utf-8")
    return json.loads(text)


def load_columns(path: Path) -> ColumnMap:
    return json.loads(Path(path).read_text(encoding="utf-8"))
```

`src/meu_danfe/nfe/parser.py`:
```python
"""Extract NFe/CT-e invoice data from parsed XML into flat rows, one per
<det> (product line) item, with invoice-level fields repeated."""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import IO, Any, Literal

import xmltodict

from meu_danfe.nfe.columns import ColumnMap, DET_PLACEHOLDER, default_columns

logger = logging.getLogger("meu_danfe.nfe")


def _get(data: Any, path: Sequence[str | int]) -> Any:
    node = data
    for key in path:
        if node is None:
            return None
        try:
            node = node[key]
        except (KeyError, IndexError, TypeError):
            return None
    return node


def _serialize(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _resolve_path(path: Sequence[str | int], det_index: int) -> list[str | int]:
    return [det_index if (isinstance(k, int) and k == DET_PLACEHOLDER) else k for k in path]


def parse_xml(source: str | bytes | Path | IO[bytes]) -> dict[str, Any]:
    """<det> is always forced to a list, even with one item — xmltodict
    otherwise collapses a single-element repeated tag into a bare dict."""
    if isinstance(source, Path):
        source = source.read_bytes()
    elif hasattr(source, "read"):
        source = source.read()
    return xmltodict.parse(source, force_list=("det",))


def extract_rows(document: dict[str, Any], columns: ColumnMap | None = None) -> list[dict[str, Any]]:
    cols = columns if columns is not None else default_columns()
    det_list = _get(document, ["nfeProc", "NFe", "infNFe", "det"]) or []
    rows: list[dict[str, Any]] = []
    for index in range(len(det_list)):
        row = {name: _serialize(_get(document, _resolve_path(path, index))) for name, path in cols.items()}
        rows.append(row)
    return rows


def extract_rows_from_file(path: Path, columns: ColumnMap | None = None) -> list[dict[str, Any]]:
    return extract_rows(parse_xml(path), columns)


def iter_rows_from_dir(
    source: Path,
    columns: ColumnMap | None = None,
    *,
    recursive: bool = False,
    on_error: Literal["warn", "raise", "skip"] = "warn",
) -> Iterator[tuple[Path, list[dict[str, Any]]]]:
    glob = source.rglob("*.xml") if recursive else source.glob("*.xml")
    for xml_path in sorted(glob):
        try:
            yield xml_path, extract_rows_from_file(xml_path, columns)
        except Exception as exc:
            if on_error == "raise":
                raise
            if on_error == "warn":
                logger.warning("skipping %s — %s", xml_path.name, exc)
```

- [ ] **Step 5: Run to verify it passes, then delete the absorbed root script**

Run: `uv run pytest tests/test_parser.py -q`
Expected: all tests `passed`

```bash
git rm xml_to_excel.py
```

- [ ] **Step 6: Commit**

```bash
git add src/meu_danfe/nfe tests/fixtures tests/test_parser.py
git commit -m "feat: nfe.parser — absorb xml_to_excel.py's row extraction into the library"
```

---

### Task 8: PDF key extraction (absorbs `pdf_key_extractor.py`, `filter_files.py`)

**Files:**
- Create: `src/meu_danfe/pdf.py`
- Test: `tests/test_pdf.py`
- Delete: root `pdf_key_extractor.py`, root `filter_files.py`

**Interfaces:**
- Consumes: `MissingDependencyError` from Task 2, `normalize_key` from Task 6.
- Produces: `ACCESS_KEY_IN_TEXT_RE`, `extract_keys(source, *, dedupe=True) -> list[str]`, `extract_keys_from_dir(root, *, recursive=True, pattern="*.pdf") -> dict[Path, list[str]]`. Used only by `cli/pdf_keys.py` (Task 15) and `server/app.py` (Task 16).
- `filter_files.py`'s only reusable idea (skip keys already downloaded) is already covered by Task 6's `existing_keys_in_dir` — this task deletes it outright with no replacement module.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_pdf.py
import pytest

pymupdf = pytest.importorskip("pymupdf")

from meu_danfe.pdf import extract_keys, extract_keys_from_dir


def _sample_key() -> str:
    return "".join(str(i % 10) for i in range(1, 45))


def _make_pdf(tmp_path, lines, name="danfe.pdf"):
    doc = pymupdf.open()
    page = doc.new_page()
    for i, line in enumerate(lines):
        page.insert_text((72, 72 + i * 20), line)
    path = tmp_path / name
    doc.save(path)
    doc.close()
    return path


def test_extract_keys_finds_dot_separated_key(tmp_path) -> None:
    key = _sample_key()
    spaced = ".".join(key[i : i + 4] for i in range(0, 44, 4))
    pdf_path = _make_pdf(tmp_path, [f"Chave de acesso: {spaced}"])
    assert extract_keys(pdf_path) == [key]


def test_extract_keys_dedupes_by_default(tmp_path) -> None:
    key = "4" * 44
    pdf_path = _make_pdf(tmp_path, [key, key])
    assert extract_keys(pdf_path) == [key]
    assert extract_keys(pdf_path, dedupe=False) == [key, key]


def test_extract_keys_from_dir_maps_each_pdf(tmp_path) -> None:
    key_a = "1" * 44
    key_b = "2" * 44
    path_a = _make_pdf(tmp_path, [key_a], name="a.pdf")
    path_b = _make_pdf(tmp_path, [key_b], name="b.pdf")
    result = extract_keys_from_dir(tmp_path)
    assert result[path_a] == [key_a]
    assert result[path_b] == [key_b]


def test_extract_keys_raises_missing_dependency_error_without_pymupdf(monkeypatch) -> None:
    import sys

    from meu_danfe.exceptions import MissingDependencyError
    monkeypatch.setitem(sys.modules, "pymupdf", None)
    with pytest.raises(MissingDependencyError):
        extract_keys(b"not a real pdf")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_pdf.py -q`
Expected: `ModuleNotFoundError: No module named 'meu_danfe.pdf'`

- [ ] **Step 3: Write `src/meu_danfe/pdf.py`**

```python
"""Extract 44-digit NFe/CT-e access keys from DANFE PDF text.

Requires the `pdf` extra (PyMuPDF).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import IO

from meu_danfe.exceptions import MissingDependencyError
from meu_danfe.keys import normalize_key

ACCESS_KEY_IN_TEXT_RE = re.compile(r"\d(?:[ .\-]*\d){43}")


def _require_pymupdf():
    try:
        import pymupdf
    except ImportError as exc:
        raise MissingDependencyError(
            'Extração de PDF requer PyMuPDF. Instale com: '
            'pip install "meu-danfe-downloader[pdf]"'
        ) from exc
    return pymupdf


def extract_keys(source: Path | bytes | IO[bytes], *, dedupe: bool = True) -> list[str]:
    pymupdf = _require_pymupdf()
    if isinstance(source, Path):
        doc = pymupdf.open(source)
    elif hasattr(source, "read"):
        doc = pymupdf.open(stream=source.read(), filetype="pdf")
    else:
        doc = pymupdf.open(stream=source, filetype="pdf")
    keys: list[str] = []
    try:
        for page in doc:
            keys.extend(normalize_key(m) for m in ACCESS_KEY_IN_TEXT_RE.findall(page.get_text()))
    finally:
        doc.close()
    if not dedupe:
        return keys
    seen: set[str] = set()
    deduped: list[str] = []
    for key in keys:
        if key not in seen:
            seen.add(key)
            deduped.append(key)
    return deduped


def extract_keys_from_dir(root: Path, *, recursive: bool = True, pattern: str = "*.pdf") -> dict[Path, list[str]]:
    glob = root.rglob(pattern) if recursive else root.glob(pattern)
    return {path: extract_keys(path) for path in sorted(glob) if path.is_file()}
```

- [ ] **Step 4: Run to verify it passes, then delete the absorbed root scripts**

Run: `uv run pytest tests/test_pdf.py -q`
Expected: all tests `passed`

```bash
git rm pdf_key_extractor.py filter_files.py
```

- [ ] **Step 5: Commit**

```bash
git add src/meu_danfe/pdf.py tests/test_pdf.py
git commit -m "feat: pdf.extract_keys — absorb pdf_key_extractor.py; drop filter_files.py"
```

---

### Task 9: Async client

**Files:**
- Create: `src/meu_danfe/client.py`
- Test: `tests/test_client.py`

**Interfaces:**
- Consumes: `MeuDanfeConfig`, `DEFAULT_BASE_URL` (Task 3); the exception tree (Task 2); `AddResult, DocumentStatus, FetchResult, XmlDocument` (Task 4); `KeyPacer` (Task 5).
- Produces: `MeuDanfeAsyncClient(api_key=None, *, base_url=DEFAULT_BASE_URL, config=None, timeout=30.0, max_concurrency=10, min_key_interval=1.0, max_polls=30, allow_unsafe_interval=False, transport=None, http_client=None, clock=time.monotonic, sleep=asyncio.sleep)` with `.from_env(**overrides)`, `async with` support, `.add`, `.get_xml`, `.wait_for`, `.fetch`, `.fetch_many`, `.iter_fetch`. Task 10 wraps this; Task 13 and Task 16 build it from a `MeuDanfeConfig`.
- Review Focus: a `ConnectError`/`TransportError` on one key must become that key's `FetchResult.error`, never cancel the batch; a terminal-looking response missing `status` must raise `MalformedResponseError`, never loop forever.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_client.py
import httpx
import pytest

from meu_danfe.client import MeuDanfeAsyncClient
from meu_danfe.exceptions import (
    AuthenticationError,
    MalformedResponseError,
    PollTimeoutError,
    TransportError,
)
from meu_danfe.models import DocumentStatus


def _key(n: int = 1) -> str:
    return str(n) * 44


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
    async with MeuDanfeAsyncClient("chave", transport=transport, max_polls=10,
                                    sleep=lambda _s: _noop()) as client:
        document = await client.fetch(key)
    assert document.data == "<x/>"
    assert document.doc_type == "NFE"


async def _noop() -> None:
    return None


async def test_not_found_status_raises_typed_error() -> None:
    key = _key(2)
    transport = _transport({key: [{"status": "NOT_FOUND"}]})
    async with MeuDanfeAsyncClient("chave", transport=transport, sleep=lambda _s: _noop()) as client:
        with pytest.raises(Exception) as excinfo:
            await client.fetch(key)
    from meu_danfe.exceptions import NotFoundStatusError
    assert isinstance(excinfo.value, NotFoundStatusError)


async def test_http_401_raises_authentication_error() -> None:
    key = _key(3)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "nope"})

    async with MeuDanfeAsyncClient("chave", transport=httpx.MockTransport(handler),
                                    sleep=lambda _s: _noop()) as client:
        with pytest.raises(AuthenticationError):
            await client.add(key)


async def test_poll_timeout_raises_after_max_polls() -> None:
    key = _key(4)
    transport = _transport({key: [{"status": "SEARCHING"}]})
    async with MeuDanfeAsyncClient("chave", transport=transport, max_polls=3,
                                    sleep=lambda _s: _noop()) as client:
        with pytest.raises(PollTimeoutError):
            await client.fetch(key)


async def test_missing_status_field_raises_malformed_response_not_infinite_loop() -> None:
    key = _key(5)
    transport = _transport({key: [{"no_status_here": True}]})
    async with MeuDanfeAsyncClient("chave", transport=transport, max_polls=3,
                                    sleep=lambda _s: _noop()) as client:
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

    async with MeuDanfeAsyncClient("chave", transport=httpx.MockTransport(handler),
                                    sleep=lambda _s: _noop()) as client:
        results = await client.fetch_many([good_key, bad_key])

    by_key = {r.key: r for r in results}
    assert by_key[good_key].ok is True
    assert by_key[bad_key].ok is False
    assert isinstance(by_key[bad_key].error, TransportError)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_client.py -q`
Expected: `ModuleNotFoundError: No module named 'meu_danfe.client'`

- [ ] **Step 3: Write `src/meu_danfe/client.py`**

```python
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
            except httpx.TimeoutException as exc:
                raise TransportError(f"{key}: tempo esgotado ao chamar {path}") from exc
            except httpx.TransportError as exc:
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
        if raw_status not in DocumentStatus.__members__:
            raise MalformedResponseError(f"{key}: resposta sem campo 'status' reconhecível: {payload!r}")
        return DocumentStatus(raw_status), payload

    async def add(self, key: str) -> AddResult:
        response = await self._request("PUT", f"fd/add/{key}", key=key)
        status, payload = self._status_from(key, response)
        return AddResult(key=key, status=status, raw=payload)

    async def get_xml(self, key: str) -> XmlDocument:
        response = await self._request("GET", f"fd/get/xml/{key}", key=key)
        payload = self._parse_json(key, response, context="resposta de download")
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

        pending = {asyncio.ensure_future(_one(key)) for key in keys}
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                yield await task
```

Note: `fetch_many`/`iter_fetch` yield results in **completion order**, not input order — match by `.key` if order matters. This is deliberate (results surface as soon as they're ready) and must not be "fixed" to preserve input order.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_client.py -q`
Expected: all tests `passed`

- [ ] **Step 5: Commit**

```bash
git add src/meu_danfe/client.py tests/test_client.py
git commit -m "feat: MeuDanfeAsyncClient — state machine, typed errors, pacing on every call"
```

---

### Task 10: Sync facade

**Files:**
- Create: `src/meu_danfe/sync_client.py`
- Test: `tests/test_sync_facade.py`

**Interfaces:**
- Consumes: `MeuDanfeAsyncClient` (Task 9), `MeuDanfeConfig` (Task 3), `AddResult/FetchResult/XmlDocument` (Task 4).
- Produces: `MeuDanfeClient` with the same method names as `MeuDanfeAsyncClient` minus `async`: `.add`, `.get_xml`, `.wait_for`, `.fetch`, `.fetch_many`, `.iter_fetch`, `.close`, `__enter__`/`__exit__`, `.from_env`.
- Review Focus: two sequential `client.fetch(key)` calls for the SAME key must still be ≥1s apart in real wall-clock time — proving the pacer's state (and the httpx connection pool) survives across calls, which a per-call `asyncio.run()` would not.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sync_facade.py
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
```

Note: the first test takes >=1 real second to run — acceptable, it is the only way to prove the facade's thread/loop persistence, which is exactly the behaviour this task exists to guarantee.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_sync_facade.py -q`
Expected: `ModuleNotFoundError: No module named 'meu_danfe.sync_client'`

- [ ] **Step 3: Write `src/meu_danfe/sync_client.py`**

```python
"""Synchronous facade over MeuDanfeAsyncClient.

Runs the SAME async client on a dedicated event loop in a background
thread owned by this object, so the httpx connection pool and the
KeyPacer's per-key timestamps persist across calls — unlike calling
asyncio.run() per method, which creates a fresh loop (and a fresh
KeyPacer) every time and would silently break the >=1s-per-key pacing
rule between two sequential sync calls for the same key.
"""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterable, Iterator
from types import TracebackType
from typing import Any, Self

from meu_danfe.client import MeuDanfeAsyncClient
from meu_danfe.config import MeuDanfeConfig
from meu_danfe.models import AddResult, FetchResult, XmlDocument


class _LoopRunner:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True, name="meu-danfe-loop")
        self._thread.start()

    def run(self, coro: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def run_each(self, make_agen: Any) -> Iterator[Any]:
        agen = make_agen()

        async def _advance() -> Any:
            return await agen.__anext__()

        while True:
            try:
                yield self.run(_advance())
            except StopAsyncIteration:
                return

    def close(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        self._loop.close()


class MeuDanfeClient:
    """Sync twin of MeuDanfeAsyncClient. Same method names, no `async`."""

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        self._runner = _LoopRunner()

        async def _build() -> MeuDanfeAsyncClient:
            return MeuDanfeAsyncClient(api_key, **kwargs)

        self._async = self._runner.run(_build())

    @classmethod
    def from_env(cls, **overrides: Any) -> Self:
        transport = overrides.pop("transport", None)
        config = MeuDanfeConfig.from_env(**overrides)
        instance = cls.__new__(cls)
        instance._runner = _LoopRunner()

        async def _build() -> MeuDanfeAsyncClient:
            return MeuDanfeAsyncClient(config=config, transport=transport)

        instance._async = instance._runner.run(_build())
        return instance

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()

    def close(self) -> None:
        self._runner.run(self._async.aclose())
        self._runner.close()

    def add(self, key: str) -> AddResult:
        return self._runner.run(self._async.add(key))

    def get_xml(self, key: str) -> XmlDocument:
        return self._runner.run(self._async.get_xml(key))

    def wait_for(self, key: str, *, max_polls: int | None = None, poll_interval: float | None = None) -> AddResult:
        return self._runner.run(self._async.wait_for(key, max_polls=max_polls, poll_interval=poll_interval))

    def fetch(self, key: str) -> XmlDocument:
        return self._runner.run(self._async.fetch(key))

    def fetch_many(self, keys: Iterable[str]) -> list[FetchResult]:
        return self._runner.run(self._async.fetch_many(keys))

    def iter_fetch(self, keys: Iterable[str]) -> Iterator[FetchResult]:
        yield from self._runner.run_each(lambda: self._async.iter_fetch(keys))
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_sync_facade.py -q`
Expected: all tests `passed` (the pacing test takes ~1s — that's expected, not a hang)

- [ ] **Step 5: Commit**

```bash
git add src/meu_danfe/sync_client.py tests/test_sync_facade.py
git commit -m "feat: MeuDanfeClient — sync facade sharing one loop/pacer, zero duplicated logic"
```

---

### Task 11: Public re-exports

**Files:**
- Modify: `src/meu_danfe/__init__.py`
- Test: `tests/test_public_api.py`

**Interfaces:**
- Consumes: everything from Tasks 2–10.
- Produces: the package's `__all__` surface and `__version__`. This is what a consumer actually types after `import meu_danfe`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_public_api.py
def test_documented_public_names_are_importable() -> None:
    import meu_danfe

    for name in (
        "MeuDanfeAsyncClient", "MeuDanfeClient", "MeuDanfeConfig", "DocumentStatus",
        "AddResult", "XmlDocument", "FetchResult", "MeuDanfeError",
        "ConfigurationError", "DocumentUnavailableError", "NotFoundStatusError",
        "SearchFailedError", "PollTimeoutError", "TransportError",
        "MalformedResponseError", "InvalidAccessKeyError", "MissingDependencyError",
        "MeuDanfeAPIError", "AuthenticationError", "InsufficientBalanceError",
        "ApiKeyReplacedError", "InvalidKeyResponseError", "DocumentNotFoundError",
        "DownloadRequestError", "UnexpectedStatusError",
    ):
        assert hasattr(meu_danfe, name), f"missing public export: {name}"
        assert name in meu_danfe.__all__
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_public_api.py -q`
Expected: `AssertionError: missing public export: MeuDanfeAsyncClient` (the current `__init__.py` only has a docstring)

- [ ] **Step 3: Rewrite `src/meu_danfe/__init__.py`**

```python
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
```

- [ ] **Step 4: Run to verify it passes, and re-check the import-without-env regression**

Run: `uv run pytest tests/test_public_api.py tests/test_import_without_env.py -q`
Expected: all tests `passed`

- [ ] **Step 5: Commit**

```bash
git add src/meu_danfe/__init__.py tests/test_public_api.py
git commit -m "feat: public re-exports — the whole surface is importable from meu_danfe"
```

---

### Task 12: Excel export

**Files:**
- Create: `src/meu_danfe/excel.py`
- Test: `tests/test_excel.py`

**Interfaces:**
- Consumes: `MissingDependencyError` (Task 2), `ColumnMap`/`default_columns` (Task 7).
- Produces: `rows_to_dataframe(rows, columns=None)`, `write_excel(rows, out_file, *, columns=None, sheet_name="NFe") -> Path`. Used by `cli/to_excel.py` (Task 14).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_excel.py
import pytest

pytest.importorskip("pandas")
pytest.importorskip("openpyxl")

from meu_danfe.excel import write_excel
from meu_danfe.nfe.columns import default_columns


def test_write_excel_contains_the_documented_header(tmp_path) -> None:
    rows = [{name: "" for name in default_columns()}]
    rows[0]["Número da Nota"] = "123"
    out = write_excel(rows, tmp_path / "out.xlsx")

    import openpyxl
    wb = openpyxl.load_workbook(out)
    header = [cell.value for cell in next(wb.active.iter_rows(max_row=1))]
    assert "Número da Nota" in header


def test_write_excel_creates_missing_output_directory(tmp_path) -> None:
    out = write_excel([{"a": 1}], tmp_path / "nested" / "out.xlsx", columns={"a": ["a"]})
    assert out.exists()


def test_rows_to_dataframe_without_pandas_raises_missing_dependency(monkeypatch) -> None:
    import sys

    from meu_danfe.exceptions import MissingDependencyError
    monkeypatch.setitem(sys.modules, "pandas", None)
    from meu_danfe.excel import rows_to_dataframe
    with pytest.raises(MissingDependencyError):
        rows_to_dataframe([{"a": 1}], columns={"a": ["a"]})
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_excel.py -q`
Expected: `ModuleNotFoundError: No module named 'meu_danfe.excel'`

- [ ] **Step 3: Write `src/meu_danfe/excel.py`**

```python
"""Excel export for parsed NFe rows. Requires the `excel` extra."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from meu_danfe.exceptions import MissingDependencyError
from meu_danfe.nfe.columns import ColumnMap, default_columns


def _require_pandas():
    try:
        import pandas as pd
    except ImportError as exc:
        raise MissingDependencyError(
            'Exportação para Excel requer pandas e openpyxl. Instale com: '
            'pip install "meu-danfe-downloader[excel]"'
        ) from exc
    return pd


def rows_to_dataframe(rows: Sequence[Mapping[str, Any]], columns: ColumnMap | None = None) -> Any:
    pd = _require_pandas()
    cols = columns if columns is not None else default_columns()
    return pd.DataFrame(list(rows), columns=list(cols.keys()))


def write_excel(
    rows: Sequence[Mapping[str, Any]], out_file: Path, *, columns: ColumnMap | None = None, sheet_name: str = "NFe"
) -> Path:
    df = rows_to_dataframe(rows, columns)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(out_file, index=False, engine="openpyxl", sheet_name=sheet_name)
    return out_file
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_excel.py -q`
Expected: all tests `passed`

- [ ] **Step 5: Commit**

```bash
git add src/meu_danfe/excel.py tests/test_excel.py
git commit -m "feat: excel.write_excel — optional pandas/openpyxl export"
```

---

### Task 13: `cli/download` (absorbs `app.py`)

**Files:**
- Create: `src/meu_danfe/cli/__init__.py`
- Create: `src/meu_danfe/cli/_common.py`
- Create: `src/meu_danfe/cli/download.py`
- Test: `tests/test_cli_download.py`
- Delete: root `app.py`

**Interfaces:**
- Consumes: `MeuDanfeAsyncClient` (Task 9), `MeuDanfeConfig`/`ConfigurationError` (Task 3/2), `load_keys`/`existing_keys_in_dir` (Task 6).
- Produces: `cli.download.main(argv=None) -> int`, registered as `meu-danfe` / `meu-danfe-download` in `pyproject.toml` (already declared in Task 1).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_download.py
import httpx
import pytest

from meu_danfe.cli.download import main


def _ok_handler(request: httpx.Request) -> httpx.Response:
    if "fd/add" in request.url.path:
        return httpx.Response(200, json={"status": "OK"})
    return httpx.Response(200, json={"name": "nota.xml", "type": "NFE", "format": "XML", "data": "<x/>"})


def test_main_requires_key_or_file(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2


def test_save_writes_file_and_reports_exit_zero(tmp_path, monkeypatch) -> None:
    import meu_danfe.cli.download as download_mod
    from meu_danfe.client import MeuDanfeAsyncClient as RealAsyncClient

    # Capture the real class under a different name before patching: a
    # lambda that calls `download_mod.MeuDanfeAsyncClient` from inside its
    # own body would resolve to itself (late-binding on the module global)
    # and recurse forever once the attribute is replaced.
    monkeypatch.setattr(
        download_mod, "MeuDanfeAsyncClient",
        lambda *a, **kw: RealAsyncClient(*a, **{**kw, "transport": httpx.MockTransport(_ok_handler)}),
    )
    monkeypatch.setenv("MEU_DANFE_API_KEY", "chave-de-teste")
    key = "k" * 44
    rc = main(["--key", key, "--save", "--out", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "nota.xml").read_text(encoding="utf-8") == "<x/>"


def test_exclude_existing_in_skips_already_downloaded_keys(tmp_path, monkeypatch, capsys) -> None:
    # The filtered key list ends up empty, so _run's `if keys:` guard never
    # constructs a client — no transport mocking needed, just a valid config.
    key = "k" * 44
    (tmp_path / f"NFE-{key}.xml").write_text("<x/>", encoding="utf-8")
    monkeypatch.setenv("MEU_DANFE_API_KEY", "chave-de-teste")
    rc = main(["--key", key, "--exclude-existing-in", str(tmp_path)])
    out = capsys.readouterr().out
    assert "0 ok, 0 falhas" in out
    assert rc == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_cli_download.py -q`
Expected: `ModuleNotFoundError: No module named 'meu_danfe.cli'`

- [ ] **Step 3: Write `src/meu_danfe/cli/__init__.py` and `_common.py`**

`src/meu_danfe/cli/__init__.py`: empty.

`src/meu_danfe/cli/_common.py`:
```python
from __future__ import annotations

import logging
import sys

EXIT_OK = 0
EXIT_ARGPARSE = 2
EXIT_PARTIAL_FAILURE = 3
EXIT_CONFIG_ERROR = 4
EXIT_UNEXPECTED = 1


def setup_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format="%(message)s", stream=sys.stderr)
```

- [ ] **Step 4: Write `src/meu_danfe/cli/download.py`**

```python
"""`meu-danfe` / `meu-danfe-download` — download NFe/CT-e XML by access key."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from meu_danfe.cli._common import EXIT_CONFIG_ERROR, EXIT_OK, EXIT_PARTIAL_FAILURE, setup_logging
from meu_danfe.client import MeuDanfeAsyncClient
from meu_danfe.config import MeuDanfeConfig
from meu_danfe.exceptions import ConfigurationError
from meu_danfe.keys import existing_keys_in_dir, load_keys

logger = logging.getLogger("meu_danfe.cli.download")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Meu DANFE downloader")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--key", help="Single 44-char NFe/CTe access key")
    group.add_argument("--file", type=Path, help="File with one access key per line")
    parser.add_argument("--save", action="store_true", default=False,
                         help="Save each XML to disk (default: print to stdout)")
    parser.add_argument("--out", "-o", type=Path, default=None,
                         help="Directory where XML files are saved when --save is set (default: cwd)")
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--max-polls", type=int, default=30)
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--exclude-existing-in", type=Path, default=None,
                         help="Skip keys already downloaded as *.xml in this directory")
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    try:
        config = MeuDanfeConfig.from_env(
            dotenv_path=args.env_file,
            max_concurrency=args.concurrency,
            timeout=args.timeout,
            max_polls=args.max_polls,
        )
    except ConfigurationError as exc:
        logger.error(str(exc))
        return EXIT_CONFIG_ERROR

    keys = [args.key] if args.key else load_keys(args.file)
    if args.exclude_existing_in:
        existing = existing_keys_in_dir(args.exclude_existing_in)
        keys = [k for k in keys if k not in existing]

    out_dir = (args.out or Path.cwd()).resolve()
    if args.save:
        out_dir.mkdir(parents=True, exist_ok=True)

    ok = 0
    failed = 0
    if keys:
        async with MeuDanfeAsyncClient(config=config) as client:
            for result in await client.fetch_many(keys):
                if result.ok:
                    ok += 1
                    if args.save:
                        path = result.document.write_to(out_dir, overwrite=True)
                        print(f"Saved: {path}")
                    else:
                        print(result.document.data)
                else:
                    failed += 1
                    print(f"{result.key}: {result.error or result.status}", file=sys.stderr)

    print(f"{ok} ok, {failed} falhas")
    return EXIT_OK if failed == 0 else EXIT_PARTIAL_FAILURE


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.log_level)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run to verify it passes, then delete the absorbed root script**

Run: `uv run pytest tests/test_cli_download.py -q`
Expected: all tests `passed`

```bash
git rm app.py
```

- [ ] **Step 6: Commit**

```bash
git add src/meu_danfe/cli/__init__.py src/meu_danfe/cli/_common.py src/meu_danfe/cli/download.py tests/test_cli_download.py
git commit -m "feat: meu-danfe/meu-danfe-download CLI — absorb app.py's lifecycle into the library call"
```

---

### Task 14: `cli/to_excel`

**Files:**
- Create: `src/meu_danfe/cli/to_excel.py`
- Test: `tests/test_cli_to_excel.py`

**Interfaces:**
- Consumes: `write_excel` (Task 12), `load_columns` (Task 7), `extract_rows_from_file`/`iter_rows_from_dir` (Task 7).
- Produces: `cli.to_excel.main(argv=None) -> int`, registered as `meu-danfe-to-excel`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_to_excel.py
import pytest

pytest.importorskip("pandas")
pytest.importorskip("openpyxl")

from meu_danfe.cli.to_excel import main


def test_single_file_writes_expected_row_count(tmp_path, fixtures_dir, capsys) -> None:
    rc = main([
        "--file", str(fixtures_dir / "nfe_multi_det.xml"),
        "--name", "saida",
        "--out", str(tmp_path),
    ])
    assert rc == 0
    assert (tmp_path / "saida.xlsx").exists()
    assert "3 row(s)" in capsys.readouterr().out


def test_missing_file_returns_nonzero(tmp_path, capsys) -> None:
    rc = main(["--file", str(tmp_path / "nope.xml"), "--name", "x", "--out", str(tmp_path)])
    assert rc != 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_cli_to_excel.py -q`
Expected: `ModuleNotFoundError: No module named 'meu_danfe.cli.to_excel'`

- [ ] **Step 3: Write `src/meu_danfe/cli/to_excel.py`**

```python
"""`meu-danfe-to-excel` — extract NFe XML fields into an Excel spreadsheet."""
from __future__ import annotations

import argparse
from pathlib import Path

from meu_danfe.excel import write_excel
from meu_danfe.nfe.columns import load_columns
from meu_danfe.nfe.parser import extract_rows_from_file, iter_rows_from_dir


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract NFe XML data to Excel")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--source", type=Path, metavar="DIR", help="Folder containing XML files")
    group.add_argument("--file", type=Path, metavar="FILE", help="Single XML file")
    parser.add_argument("--out", type=Path, default=Path.cwd(), metavar="DIR")
    parser.add_argument("--name", required=True, metavar="NAME")
    parser.add_argument("--columns", type=Path, default=None)
    parser.add_argument("--recursive", action="store_true", default=False)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    columns = load_columns(args.columns) if args.columns else None

    all_rows: list[dict] = []
    if args.source:
        for _xml_path, rows in iter_rows_from_dir(args.source, columns, recursive=args.recursive, on_error="warn"):
            all_rows.extend(rows)
    else:
        if not args.file.is_file():
            print(f"File not found: {args.file}")
            return 2
        all_rows.extend(extract_rows_from_file(args.file, columns))

    out_file = args.out / f"{args.name}.xlsx"
    write_excel(all_rows, out_file, columns=columns)
    print(f"Saved {len(all_rows)} row(s) to {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_cli_to_excel.py -q`
Expected: all tests `passed`

- [ ] **Step 5: Commit**

```bash
git add src/meu_danfe/cli/to_excel.py tests/test_cli_to_excel.py
git commit -m "feat: meu-danfe-to-excel CLI"
```

---

### Task 15: `cli/pdf_keys`

**Files:**
- Create: `src/meu_danfe/cli/pdf_keys.py`
- Test: `tests/test_cli_pdf_keys.py`

**Interfaces:**
- Consumes: `extract_keys`/`extract_keys_from_dir` (Task 8).
- Produces: `cli.pdf_keys.main(argv=None) -> int`, registered as `meu-danfe-pdf-keys`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_pdf_keys.py
import pytest

pymupdf = pytest.importorskip("pymupdf")

from meu_danfe.cli.pdf_keys import main


def _make_pdf(tmp_path, key: str, name="danfe.pdf"):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), key)
    path = tmp_path / name
    doc.save(path)
    doc.close()
    return path


def test_prints_keys_to_stdout_by_default(tmp_path, capsys) -> None:
    key = "9" * 44
    pdf_path = _make_pdf(tmp_path, key)
    rc = main(["--source", str(pdf_path)])
    assert rc == 0
    assert capsys.readouterr().out.strip() == key


def test_writes_to_out_file_when_given(tmp_path) -> None:
    key = "8" * 44
    pdf_path = _make_pdf(tmp_path, key)
    out_file = tmp_path / "keys.csv"
    rc = main(["--source", str(pdf_path), "--out", str(out_file)])
    assert rc == 0
    assert out_file.read_text(encoding="utf-8").strip() == key
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_cli_pdf_keys.py -q`
Expected: `ModuleNotFoundError: No module named 'meu_danfe.cli.pdf_keys'`

- [ ] **Step 3: Write `src/meu_danfe/cli/pdf_keys.py`**

```python
"""`meu-danfe-pdf-keys` — extract 44-digit access keys from DANFE PDFs."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from meu_danfe.pdf import extract_keys, extract_keys_from_dir


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract NFe access keys from DANFE PDFs")
    parser.add_argument("--source", type=Path, required=True, help="A PDF file or a directory of PDFs")
    parser.add_argument("--out", type=Path, default=None, help="Output file (default: stdout)")
    parser.add_argument("--append", dest="append", action="store_true", default=False)
    parser.add_argument("--no-dedupe", dest="dedupe", action="store_false", default=True)
    parser.add_argument("--recursive", action="store_true", default=False)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.source.is_dir():
        by_file = extract_keys_from_dir(args.source, recursive=args.recursive)
        keys = [key for found in by_file.values() for key in found]
    else:
        keys = extract_keys(args.source, dedupe=args.dedupe)

    lines = "\n".join(keys)
    if args.out:
        mode = "a" if args.append else "w"
        with args.out.open(mode, encoding="utf-8") as f:
            if keys:
                f.write(lines + "\n")
    else:
        print(lines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_cli_pdf_keys.py -q`
Expected: all tests `passed`

- [ ] **Step 5: Commit**

```bash
git add src/meu_danfe/cli/pdf_keys.py tests/test_cli_pdf_keys.py
git commit -m "feat: meu-danfe-pdf-keys CLI"
```

---

### Task 16: Optional local HTTP server

**Files:**
- Create: `src/meu_danfe/server/__init__.py`
- Create: `src/meu_danfe/server/settings.py`
- Create: `src/meu_danfe/server/auth.py`
- Create: `src/meu_danfe/server/schemas.py`
- Create: `src/meu_danfe/server/app.py`
- Create: `src/meu_danfe/server/__main__.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `MeuDanfeAsyncClient`/`MeuDanfeConfig` (Tasks 9/3), `extract_rows`/`parse_xml` (Task 7), `extract_keys` (Task 8), `ConfigurationError` (Task 2).
- Produces: `create_app(*, config, settings, transport=None) -> FastAPI`, `ServerSettings(token, max_keys_per_request=50, host="127.0.0.1", port=8787)` with `.from_env(...)`. This is the extent of the HTTP surface for non-Python consumers — no other module depends on it.
- Only one `MeuDanfeAsyncClient` is created per app (in the `lifespan`), never one per request — a client per request would recreate the `KeyPacer` and lose the pacing guarantee across requests.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_server.py
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_server.py -q`
Expected: `ModuleNotFoundError: No module named 'meu_danfe.server'`

- [ ] **Step 3: Write the `server/` package**

`src/meu_danfe/server/__init__.py`: empty.

`src/meu_danfe/server/settings.py`:
```python
"""Settings for the optional local HTTP server. The server refuses to
start without a token — see ConfigurationError below."""
from __future__ import annotations

from dataclasses import dataclass

from meu_danfe.exceptions import ConfigurationError


@dataclass(frozen=True, slots=True)
class ServerSettings:
    token: str
    max_keys_per_request: int = 50
    host: str = "127.0.0.1"
    port: int = 8787

    def __post_init__(self) -> None:
        if not self.token or not self.token.strip():
            raise ConfigurationError(
                "O servidor exige MEU_DANFE_SERVER_TOKEN configurado; ele nunca sobe sem token."
            )

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None, **overrides: object) -> "ServerSettings":
        import os
        env = env if env is not None else os.environ
        token = overrides.pop("token", None) or env.get("MEU_DANFE_SERVER_TOKEN")
        if not token:
            raise ConfigurationError("MEU_DANFE_SERVER_TOKEN não definida.")
        return cls(token=token, **overrides)
```

`src/meu_danfe/server/auth.py`:
```python
from __future__ import annotations

import secrets

from fastapi import Header, HTTPException

from meu_danfe.server.settings import ServerSettings


def require_token(settings: ServerSettings):
    async def _check(x_meu_danfe_token: str | None = Header(default=None)) -> None:
        if not x_meu_danfe_token or not secrets.compare_digest(x_meu_danfe_token, settings.token):
            raise HTTPException(status_code=401, detail="Token inválido ou ausente.")

    return _check
```

`src/meu_danfe/server/schemas.py`:
```python
from __future__ import annotations

from pydantic import BaseModel, Field


class FetchRequest(BaseModel):
    keys: list[str] = Field(..., min_length=1)


class DocumentOut(BaseModel):
    key: str
    name: str
    doc_type: str
    content_format: str
    data: str


class FetchResultOut(BaseModel):
    key: str
    status: str | None
    ok: bool
    error: str | None
    document: DocumentOut | None


class ParseRequest(BaseModel):
    xml: str


class RowsOut(BaseModel):
    rows: list[dict]


class KeysOut(BaseModel):
    keys: list[str]
```

`src/meu_danfe/server/app.py`:
```python
"""Optional local HTTP server over the meu_danfe library, for non-Python
consumers. ONE MeuDanfeAsyncClient lives for the app's whole lifetime —
never one per request, which would reset the KeyPacer and lose pacing."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from meu_danfe.client import MeuDanfeAsyncClient
from meu_danfe.config import MeuDanfeConfig
from meu_danfe.nfe.parser import extract_rows, parse_xml
from meu_danfe.pdf import extract_keys
from meu_danfe.server.auth import require_token
from meu_danfe.server.schemas import DocumentOut, FetchRequest, FetchResultOut, KeysOut, ParseRequest, RowsOut
from meu_danfe.server.settings import ServerSettings

logger = logging.getLogger("meu_danfe.server")


def create_app(*, config: MeuDanfeConfig, settings: ServerSettings, transport=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with MeuDanfeAsyncClient(config=config, transport=transport) as client:
            app.state.client = client
            yield

    app = FastAPI(title="meu-danfe server", lifespan=lifespan)
    token_dep = require_token(settings)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/documents/fetch", dependencies=[Depends(token_dep)])
    async def fetch_documents(body: FetchRequest) -> StreamingResponse:
        if len(body.keys) > settings.max_keys_per_request:
            raise HTTPException(
                status_code=413, detail=f"Máximo de {settings.max_keys_per_request} chaves por requisição."
            )
        client: MeuDanfeAsyncClient = app.state.client

        async def _stream() -> AsyncIterator[bytes]:
            total_polls = 0
            async for result in client.iter_fetch(body.keys):
                total_polls += result.polls
                out = FetchResultOut(
                    key=result.key,
                    status=str(result.status) if result.status else None,
                    ok=result.ok,
                    error=str(result.error) if result.error else None,
                    document=(
                        DocumentOut(
                            key=result.document.key,
                            name=result.document.name,
                            doc_type=result.document.doc_type,
                            content_format=result.document.content_format,
                            data=result.document.data,
                        )
                        if result.document
                        else None
                    ),
                )
                yield (out.model_dump_json() + "\n").encode("utf-8")
            logger.info(
                "fetch batch complete: %d keys, %d polls (~R$ %.2f)",
                len(body.keys), total_polls, total_polls * 0.03,
            )

        return StreamingResponse(_stream(), media_type="application/x-ndjson")

    @app.post("/v1/documents/parse", dependencies=[Depends(token_dep)], response_model=RowsOut)
    async def parse_document(body: ParseRequest) -> RowsOut:
        return RowsOut(rows=extract_rows(parse_xml(body.xml)))

    @app.post("/v1/pdf/keys", dependencies=[Depends(token_dep)], response_model=KeysOut)
    async def pdf_keys(file: UploadFile) -> KeysOut:
        content = await file.read()
        return KeysOut(keys=extract_keys(content))

    return app
```

`src/meu_danfe/server/__main__.py`:
```python
"""`python -m meu_danfe.server` — run the local HTTP server."""
from __future__ import annotations

import argparse

import uvicorn

from meu_danfe.config import MeuDanfeConfig
from meu_danfe.server.app import create_app
from meu_danfe.server.settings import ServerSettings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="meu-danfe HTTP server (local, token-protected)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--allow-remote", action="store_true", default=False)
    parser.add_argument("--max-keys-per-request", type=int, default=50)
    parser.add_argument("--env-file", default=None)
    args = parser.parse_args(argv)

    if args.host not in ("127.0.0.1", "localhost") and not args.allow_remote:
        parser.error("Bind não-local requer --allow-remote explícito.")

    config = MeuDanfeConfig.from_env(dotenv_path=args.env_file)
    settings = ServerSettings.from_env(host=args.host, port=args.port, max_keys_per_request=args.max_keys_per_request)
    uvicorn.run(create_app(config=config, settings=settings), host=settings.host, port=settings.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Add the `server` extra's test dependency and run**

Run: `uv sync --group dev --extra server --extra pdf --extra excel --extra dotenv && uv run pytest tests/test_server.py -q`
Expected: all tests `passed`

- [ ] **Step 5: Commit**

```bash
git add src/meu_danfe/server tests/test_server.py
git commit -m "feat: optional local HTTP server — token-gated, one shared client, batch fetch streaming"
```

---

### Task 17: Lower the Python floor to 3.12

**Files:**
- Modify: `pyproject.toml` (`requires-python`)

**Interfaces:**
- No new interfaces — this task re-verifies every previous task's tests under a second interpreter.

- [ ] **Step 1: Lower the floor**

In `pyproject.toml`, change:
```toml
requires-python = ">=3.14"
```
to:
```toml
requires-python = ">=3.12"
```

- [ ] **Step 2: Re-lock and run the full suite on 3.12**

Run: `uv lock -p 3.12 && uv run -p 3.12 --extra all pytest -q`
Expected: all tests `passed` on Python 3.12

- [ ] **Step 3: Confirm 3.14 still passes too**

Run: `uv run -p 3.14 --extra all pytest -q`
Expected: all tests `passed` on Python 3.14

- [ ] **Step 4: Confirm a clean wheel install works**

Run: `uv build && uv run --isolated --with "$(ls dist/*.whl)" python -c "import meu_danfe; print(meu_danfe.__version__)"`
Expected: prints `0.1.0`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: lower requires-python to >=3.12 — nothing here needs 3.13/3.14"
```

---

### Task 18: Docs, notebook, and data hygiene

**Files:**
- Create: `.env.example`
- Modify: `README.md`, `CLAUDE.md`
- Modify: `notas-nb.ipynb` (move to `notebooks/notas-nb.ipynb`)
- Modify: data file locations (`chaves_nfe.csv`, `todo.csv`, `out.csv` → `data/`; `notas.tsv`/`test_output.xlsx` already untracked, move for tidiness only)

**Interfaces:** none — this task has no tests; it is documentation and housekeeping. Verification is manual review, listed in Step 5.

- [ ] **Step 1: Write `.env.example`**

```bash
# Required
MEU_DANFE_API_KEY=
MEU_DANFE_API_URL=https://api.meudanfe.com.br/v2/

# Optional server extra
MEU_DANFE_SERVER_TOKEN=
```

- [ ] **Step 2: Rewrite `CLAUDE.md` and `README.md`**

Rewrite both to describe the library-first architecture: `src/meu_danfe/` modules and their responsibilities (client, sync_client, config, exceptions, models, pacing, storage, keys, nfe.parser, nfe.columns, pdf, excel, cli/*, server/*), the extras table (`excel`, `pdf`, `dotenv`, `server`, `cli`, `all`), and the three CLI entry points. Fix two inherited inaccuracies while rewriting:
- `CLAUDE.md` currently claims "The `.env` also contains SharePoint, SQL Server (UAU-CLOUD), and Microsoft Graph API credentials used by the notebook" — the notebook never touches any of those; they are unused variables inherited from a different project. State that plainly instead.
- `README.md`'s example shows `MEU_DANFE_API_URL=https://api.meudanfe.com.br` (no `/v2`); the real endpoints live under `/v2/`, as `.env.example` now shows correctly.

- [ ] **Step 3: Move the notebook and rewrite its first two cells**

```bash
mkdir -p notebooks
git mv notas-nb.ipynb notebooks/notas-nb.ipynb
```

Replace cell 1 (the `LiveServerSession`/sync `find_and_add_nfe`/`get_nfe` duplicate, its bare `except:` that swallows everything including `KeyboardInterrupt`, and the dead `main()` scaffolding) with:
```python
from meu_danfe import MeuDanfeClient

with MeuDanfeClient.from_env() as client:
    document = client.fetch("CHAVE_DE_ACESSO_AQUI")
    print(document.name, document.doc_type, len(document.data))
```

Fix cell 2's field-mapping documentation: it currently swaps `CNPJ Destinatário` and `Razão Social Destinatário` (the real mapping, in `src/meu_danfe/nfe/columns.json`, has them correct) — correct the doc cell to match.

Replace cell 4's inline `extract_key(file: Path)` (duplicate of the old `pdf_key_extractor.py`) with:
```python
from meu_danfe.pdf import extract_keys_from_dir

found = extract_keys_from_dir(WD)
```

- [ ] **Step 4: Move remaining data files into `data/` for tidiness**

```bash
mkdir -p data
git mv chaves_nfe.csv data/chaves_nfe.csv 2>/dev/null || mv chaves_nfe.csv data/chaves_nfe.csv
git mv todo.csv data/todo.csv 2>/dev/null || mv todo.csv data/todo.csv
git mv out.csv data/out.csv 2>/dev/null || mv out.csv data/out.csv
mv notas.tsv data/notas.tsv       # already untracked — plain mv, not git mv
mv test_output.xlsx data/test_output.xlsx  # already untracked
```

(`chaves_nfe.csv`/`todo.csv`/`out.csv` were tracked in the Task 0 baseline commit since the original `.gitignore` bug let them through — `git mv` relocates their history; `git rm --cached` was not needed because the fixed `*.csv` rule in `.gitignore` now makes `data/*.csv` ignored going forward too, so the move alone keeps them out of future commits.)

- [ ] **Step 5: Manual verification**

Run: `uv run meu-danfe --help && uv run meu-danfe-to-excel --help && uv run meu-danfe-pdf-keys --help`
Expected: all three print their argument help with the documented flags (`--key/--file/--save/--out,-o`; `--source/--file/--name/--out`; `--source/--out/--append/--no-dedupe/--recursive`)

Run: `git status --short`
Expected: `chaves_nfe.csv`, `todo.csv`, `out.csv` show as moved (not new); `notas.tsv`/`test_output.xlsx` do not appear at all (still ignored)

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "docs: library-first README/CLAUDE.md, rewritten notebook, data/ tidiness"
```

---

## Final Verification (whole branch)

```bash
uv run -p 3.12 --extra all pytest -q
uv run -p 3.14 --extra all pytest -q
uv build && uv run --isolated --with "$(ls dist/*.whl)" python -c "import meu_danfe"
git log --oneline main..HEAD   # every task is its own commit, in order
```

One real query against the live API (cost: R$0,03), using a key you choose, is the final human-run check that the mocked test suite's assumptions about the vendor's actual responses hold — run it only after every task above is green, and only if you want to spend the three centavos.
