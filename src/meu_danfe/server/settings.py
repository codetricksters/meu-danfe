"""Settings for the optional local HTTP server. The server refuses to
start without a token — see ConfigurationError below."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from meu_danfe.config import _merge_env_with_dotenv
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
    def from_env(
        cls, env: dict[str, str] | None = None, *, dotenv_path: Any | None = None, **overrides: object
    ) -> "ServerSettings":
        import os
        env = env if env is not None else os.environ
        merged = _merge_env_with_dotenv(env, dotenv_path)
        token = overrides.pop("token", None) or merged.get("MEU_DANFE_SERVER_TOKEN")
        if not token:
            raise ConfigurationError("MEU_DANFE_SERVER_TOKEN não definida.")
        return cls(token=token, **overrides)
