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
