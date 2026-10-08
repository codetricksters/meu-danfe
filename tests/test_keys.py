import pytest

from meu_danfe.exceptions import InvalidAccessKeyError
from meu_danfe.keys import existing_keys_in_dir, is_valid_key, load_keys, normalize_key, validate_key


def _key() -> str:
    return "".join(str(i % 10) for i in range(1, 45))


def test_normalize_key_strips_separators() -> None:
    key = _key()
    spaced = ".".join(key[i : i + 4] for i in range(0, 44, 4))
    assert normalize_key(spaced) == key
    assert normalize_key(f"  {key}  ") == key


def test_is_valid_key_requires_exactly_44_digits() -> None:
    assert is_valid_key(_key()) is True
    assert is_valid_key(_key()[:-1]) is False
    assert is_valid_key(_key() + "0") is False
    assert is_valid_key("not-a-key") is False


def test_validate_key_returns_normalized_or_raises() -> None:
    key = _key()
    assert validate_key(f"{key[:4]}.{key[4:]}") == key
    with pytest.raises(InvalidAccessKeyError):
        validate_key("curta")


def test_load_keys_skips_blank_lines(tmp_path) -> None:
    path = tmp_path / "keys.txt"
    path.write_text(f"{_key()}\n\n   \n{_key()}\n", encoding="utf-8")
    assert load_keys(path) == [_key(), _key()]


def test_existing_keys_in_dir_strips_nfe_prefix(tmp_path) -> None:
    key = _key()
    (tmp_path / f"NFE-{key}.xml").write_text("<x/>", encoding="utf-8")
    (tmp_path / "not-a-key.xml").write_text("<x/>", encoding="utf-8")
    assert existing_keys_in_dir(tmp_path) == {key}
