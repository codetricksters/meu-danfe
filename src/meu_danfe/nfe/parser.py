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
