"""Loading the column-name -> JSON-path map that drives NFe row extraction."""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from functools import cache
from importlib import resources
from pathlib import Path

ColumnMap = Mapping[str, Sequence[str | int]]

DET_PLACEHOLDER: int = 0


@cache
def default_columns() -> ColumnMap:
    text = resources.files("meu_danfe.nfe").joinpath("columns.json").read_text(encoding="utf-8")
    return json.loads(text)


def load_columns(path: Path) -> ColumnMap:
    return json.loads(Path(path).read_text(encoding="utf-8"))
