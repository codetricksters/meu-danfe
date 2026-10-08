from __future__ import annotations

import secrets

from fastapi import Header, HTTPException

from meu_danfe.server.settings import ServerSettings


def require_token(settings: ServerSettings):
    async def _check(x_meu_danfe_token: str | None = Header(default=None)) -> None:
        if not x_meu_danfe_token or not secrets.compare_digest(x_meu_danfe_token, settings.token):
            raise HTTPException(status_code=401, detail="Token inválido ou ausente.")

    return _check
