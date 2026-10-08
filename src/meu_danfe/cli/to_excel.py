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
