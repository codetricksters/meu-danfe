"""Typed values the client returns, instead of raw httpx.Response."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from meu_danfe.storage import save_xml, sanitize_filename

if TYPE_CHECKING:
    from meu_danfe.exceptions import MeuDanfeError


class DocumentStatus(StrEnum):
    WAITING = "WAITING"
    SEARCHING = "SEARCHING"
    NOT_FOUND = "NOT_FOUND"
    OK = "OK"
    ERROR = "ERROR"

    @property
    def is_terminal(self) -> bool:
        return self in (DocumentStatus.NOT_FOUND, DocumentStatus.OK, DocumentStatus.ERROR)

    @property
    def is_success(self) -> bool:
        return self is DocumentStatus.OK


@dataclass(frozen=True, slots=True)
class AddResult:
    key: str
    status: DocumentStatus
    raw: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class XmlDocument:
    key: str
    name: str
    doc_type: str
    content_format: str
    data: str
    raw: Mapping[str, Any]

    @property
    def safe_filename(self) -> str:
        return sanitize_filename(self.name, fallback=f"{self.key}.xml")

    def write_to(self, out_dir: Path, *, filename: str | None = None, overwrite: bool = False) -> Path:
        return save_xml(self, out_dir, filename=filename, overwrite=overwrite)


@dataclass(frozen=True, slots=True)
class FetchResult:
    key: str
    status: DocumentStatus | None
    document: XmlDocument | None
    error: "MeuDanfeError | None"
    polls: int

    @property
    def ok(self) -> bool:
        return self.document is not None
