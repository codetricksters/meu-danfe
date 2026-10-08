"""Configuration for the Meu DANFE client.

Nothing in this module touches os.environ or the filesystem at import
time: `MeuDanfeConfig.from_env` is the ONLY place environment or dotenv
values are read, and only when a caller invokes it explicitly.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meu_danfe.exceptions import ConfigurationError, MissingDependencyError

DEFAULT_BASE_URL = "https://api.meudanfe.com.br/v2/"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_CONCURRENCY = 10
MIN_KEY_INTERVAL = 1.0
DEFAULT_MAX_POLLS = 30


def default_dotenv_path() -> Path | None:
    """`./.env` if it exists in the current working directory, else None.

    A plain function, not a module-level constant: calling it is a
    filesystem check, and nothing in this module may touch the filesystem
    merely by being imported.
    """
    candidate = Path(".env")
    return candidate if candidate.is_file() else None


def _merge_env_with_dotenv(env: Mapping[str, str], dotenv_path: Any | None) -> dict[str, str]:
    """Shared by MeuDanfeConfig.from_env and ServerSettings.from_env: dotenv
    file values first, then real environment values on top (env wins)."""
    merged: dict[str, str] = dict(env)
    if dotenv_path is None:
        return merged
    try:
        from dotenv import dotenv_values
    except ImportError as exc:
        raise MissingDependencyError(
            'dotenv_path foi passado, mas python-dotenv não está instalado. '
            'Instale com: pip install "meu-danfe-downloader[dotenv]"'
        ) from exc
    file_values = {k: v for k, v in dotenv_values(dotenv_path).items() if v is not None}
    return {**file_values, **merged}


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

        merged = _merge_env_with_dotenv(env, dotenv_path)

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
