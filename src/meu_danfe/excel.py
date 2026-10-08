"""Excel export for parsed NFe rows. Requires the `excel` extra."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from meu_danfe.exceptions import MissingDependencyError
from meu_danfe.nfe.columns import ColumnMap, default_columns


def _require_pandas():
    try:
        import pandas as pd
    except ImportError as exc:
        raise MissingDependencyError(
            'Exportação para Excel requer pandas e openpyxl. Instale com: '
            'pip install "meu-danfe-downloader[excel]"'
        ) from exc
    return pd


def rows_to_dataframe(rows: Sequence[Mapping[str, Any]], columns: ColumnMap | None = None) -> Any:
    pd = _require_pandas()
    cols = columns if columns is not None else default_columns()
    return pd.DataFrame(list(rows), columns=list(cols.keys()))


def write_excel(
    rows: Sequence[Mapping[str, Any]], out_file: Path, *, columns: ColumnMap | None = None, sheet_name: str = "NFe"
) -> Path:
    df = rows_to_dataframe(rows, columns)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(out_file, index=False, engine="openpyxl", sheet_name=sheet_name)
    return out_file
