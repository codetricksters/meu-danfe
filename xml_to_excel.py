import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd
import xmltodict

ROOT_DIR = Path(__file__).resolve().parent

def _load_columns() -> dict[str, list]:
    return json.loads((ROOT_DIR / "columns.json").read_text(encoding="utf-8"))


# Paths use 0 as a placeholder for the det item index; it will be replaced per item.
COLUMNS: dict[str, list] = _load_columns()

_DET_PLACEHOLDER = 0  # integer sentinel in paths that marks the det index


def _get(data: Any, path: list) -> Any:
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


def _resolve_path(path: list, det_index: int) -> list:
    return [det_index if (isinstance(k, int) and k == _DET_PLACEHOLDER) else k for k in path]


def _extract_rows(data: dict) -> list[dict]:
    det_list = _get(data, ["nfeProc", "NFe", "infNFe", "det"]) or []

    rows = []
    for n in range(len(det_list)):
        row = {}
        for col, path in COLUMNS.items():
            resolved = _resolve_path(path, n)
            row[col] = _serialize(_get(data, resolved))
        rows.append(row)
    return rows


def _parse_xml(path: Path) -> dict:
    return xmltodict.parse(path.read_text(encoding="utf-8"), force_list=("det",))


def _collect_xml_files(source: Path) -> list[Path]:
    return sorted(source.glob("*.xml"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract NFe XML data to Excel")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--source", type=Path, metavar="DIR", help="Folder containing XML files")
    group.add_argument("--file", type=Path, metavar="FILE", help="Single XML file")
    parser.add_argument("--out", type=Path, default=ROOT_DIR, metavar="DIR", help="Output folder (default: script directory)")
    parser.add_argument("--name", required=True, metavar="NAME", help="Excel file name (without extension)")
    args = parser.parse_args()

    if args.source:
        xml_files = _collect_xml_files(args.source)
        if not xml_files:
            parser.error(f"No XML files found in {args.source}")
    else:
        if not args.file.is_file():
            parser.error(f"File not found: {args.file}")
        xml_files = [args.file]

    all_rows = []
    for xml_path in xml_files:
        try:
            data = _parse_xml(xml_path)
            all_rows.extend(_extract_rows(data))
        except Exception as exc:
            print(f"Warning: skipping {xml_path.name} — {exc}")

    df = pd.DataFrame(all_rows, columns=list(COLUMNS.keys()))

    args.out.mkdir(parents=True, exist_ok=True)
    out_file = args.out / f"{args.name}.xlsx"
    df.to_excel(out_file, index=False, engine="openpyxl")
    print(f"Saved {len(all_rows)} row(s) to {out_file}")


if __name__ == "__main__":
    main()
