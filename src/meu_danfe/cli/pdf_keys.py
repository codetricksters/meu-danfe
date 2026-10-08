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
