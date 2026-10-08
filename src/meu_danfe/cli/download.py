"""`meu-danfe` / `meu-danfe-download` — download NFe/CT-e XML by access key."""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from meu_danfe.cli._common import EXIT_CONFIG_ERROR, EXIT_OK, EXIT_PARTIAL_FAILURE, setup_logging
from meu_danfe.client import MeuDanfeAsyncClient
from meu_danfe.config import MeuDanfeConfig, default_dotenv_path
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
    parser.add_argument("--env-file", type=Path, default=None,
                         help="Default: ./.env if it exists (requires the `dotenv` extra)")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--exclude-existing-in", type=Path, default=None,
                         help="Skip keys already downloaded as *.xml in this directory")
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    try:
        config = MeuDanfeConfig.from_env(
            dotenv_path=args.env_file or default_dotenv_path(),
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
