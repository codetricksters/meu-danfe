"""Writing downloaded XML to disk, with filenames the vendor's `name`
field can never use to escape the destination directory."""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from meu_danfe.models import XmlDocument

_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def sanitize_filename(name: str, *, fallback: str) -> str:
    """Reduce an API-supplied filename to a bare name with no path
    components, so it can never escape the destination directory."""
    candidate = Path(name).name  # drops any "/" or "\" directory components
    candidate = _UNSAFE_CHARS.sub("_", candidate).strip(". ")
    return candidate or fallback


def save_xml(
    document: "XmlDocument", out_dir: Path, *, filename: str | None = None, overwrite: bool = False
) -> Path:
    name = sanitize_filename(filename or document.name, fallback=f"{document.key}.xml")
    out_dir.mkdir(parents=True, exist_ok=True)
    resolved_dir = out_dir.resolve()
    path = out_dir / name
    if path.resolve().parent != resolved_dir:
        # Defense in depth: sanitize_filename should already guarantee this.
        raise ValueError(f"nome de arquivo resolvido fora do diretório de destino: {name!r}")
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} já existe (passe overwrite=True para sobrescrever)")
    path.write_text(document.data, encoding="utf-8")
    return path
