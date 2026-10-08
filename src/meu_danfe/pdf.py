"""Extract 44-digit NFe/CT-e access keys from DANFE PDF text.

Requires the `pdf` extra (PyMuPDF).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import IO

from meu_danfe.exceptions import MissingDependencyError
from meu_danfe.keys import normalize_key

ACCESS_KEY_IN_TEXT_RE = re.compile(r"\d(?:[ .\-]*\d){43}")


def _require_pymupdf():
    try:
        import pymupdf
    except ImportError as exc:
        raise MissingDependencyError(
            'Extração de PDF requer PyMuPDF. Instale com: '
            'pip install "meu-danfe-downloader[pdf]"'
        ) from exc
    return pymupdf


def extract_keys(source: Path | bytes | IO[bytes], *, dedupe: bool = True) -> list[str]:
    pymupdf = _require_pymupdf()
    if isinstance(source, Path):
        doc = pymupdf.open(source)
    elif hasattr(source, "read"):
        doc = pymupdf.open(stream=source.read(), filetype="pdf")
    else:
        doc = pymupdf.open(stream=source, filetype="pdf")
    keys: list[str] = []
    try:
        for page in doc:
            keys.extend(normalize_key(m) for m in ACCESS_KEY_IN_TEXT_RE.findall(page.get_text()))
    finally:
        doc.close()
    if not dedupe:
        return keys
    seen: set[str] = set()
    deduped: list[str] = []
    for key in keys:
        if key not in seen:
            seen.add(key)
            deduped.append(key)
    return deduped


def extract_keys_from_dir(root: Path, *, recursive: bool = True, pattern: str = "*.pdf") -> dict[Path, list[str]]:
    glob = root.rglob(pattern) if recursive else root.glob(pattern)
    return {path: extract_keys(path) for path in sorted(glob) if path.is_file()}
