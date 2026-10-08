"""44-digit access key (Chave de Acesso) normalisation and lookup helpers."""
from __future__ import annotations

import re
from pathlib import Path

from meu_danfe.exceptions import InvalidAccessKeyError

ACCESS_KEY_RE = re.compile(r"^\d{44}$")
_STRIP_RE = re.compile(r"[ .\-]")


def normalize_key(raw: str) -> str:
    """Strip spaces, dots and dashes commonly used to group the 44 digits."""
    return _STRIP_RE.sub("", raw.strip())


def is_valid_key(raw: str) -> bool:
    return bool(ACCESS_KEY_RE.match(normalize_key(raw)))


def validate_key(raw: str) -> str:
    key = normalize_key(raw)
    if not ACCESS_KEY_RE.match(key):
        raise InvalidAccessKeyError(raw, f"chave deve ter 44 dígitos, tem {len(key)}")
    return key


def load_keys(path: Path) -> list[str]:
    """One access key per line; blank lines skipped."""
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def existing_keys_in_dir(directory: Path, *, pattern: str = "*.xml") -> set[str]:
    """Access keys already present as downloaded files, e.g. 'NFE-{chave}.xml'
    or '{chave}.xml'. Used to skip keys that would cost R$0,03 to re-fetch."""
    found: set[str] = set()
    for path in directory.glob(pattern):
        candidate = path.stem.split("-", 1)[-1]
        if is_valid_key(candidate):
            found.add(normalize_key(candidate))
    return found
