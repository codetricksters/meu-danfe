"""`python -m meu_danfe.server` — run the local HTTP server."""
from __future__ import annotations

import argparse

import uvicorn

from meu_danfe.config import MeuDanfeConfig, default_dotenv_path
from meu_danfe.server.app import create_app
from meu_danfe.server.settings import ServerSettings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="meu-danfe HTTP server (local, token-protected)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--allow-remote", action="store_true", default=False)
    parser.add_argument("--max-keys-per-request", type=int, default=50)
    parser.add_argument("--env-file", default=None,
                         help="Default: ./.env if it exists (requires the `dotenv` extra)")
    args = parser.parse_args(argv)

    if args.host not in ("127.0.0.1", "localhost") and not args.allow_remote:
        parser.error("Bind não-local requer --allow-remote explícito.")

    # Both config (api_key) and settings (server token) can live in the
    # same .env file — pass the SAME resolved path to both.
    dotenv_path = args.env_file or default_dotenv_path()
    config = MeuDanfeConfig.from_env(dotenv_path=dotenv_path)
    settings = ServerSettings.from_env(
        dotenv_path=dotenv_path, host=args.host, port=args.port, max_keys_per_request=args.max_keys_per_request
    )
    uvicorn.run(create_app(config=config, settings=settings), host=settings.host, port=settings.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
