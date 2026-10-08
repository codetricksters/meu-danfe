from __future__ import annotations

from pydantic import BaseModel, Field


class FetchRequest(BaseModel):
    keys: list[str] = Field(..., min_length=1)


class DocumentOut(BaseModel):
    key: str
    name: str
    doc_type: str
    content_format: str
    data: str


class FetchResultOut(BaseModel):
    key: str
    status: str | None
    ok: bool
    error: str | None
    document: DocumentOut | None


class ParseRequest(BaseModel):
    xml: str


class RowsOut(BaseModel):
    rows: list[dict]


class KeysOut(BaseModel):
    keys: list[str]
