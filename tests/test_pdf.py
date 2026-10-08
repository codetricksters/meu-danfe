import pytest

pymupdf = pytest.importorskip("pymupdf")

from meu_danfe.pdf import extract_keys, extract_keys_from_dir


def _sample_key() -> str:
    return "".join(str(i % 10) for i in range(1, 45))


def _make_pdf(tmp_path, lines, name="danfe.pdf"):
    doc = pymupdf.open()
    page = doc.new_page()
    for i, line in enumerate(lines):
        page.insert_text((72, 72 + i * 20), line)
    path = tmp_path / name
    doc.save(path)
    doc.close()
    return path


def test_extract_keys_finds_dot_separated_key(tmp_path) -> None:
    key = _sample_key()
    spaced = ".".join(key[i : i + 4] for i in range(0, 44, 4))
    pdf_path = _make_pdf(tmp_path, [f"Chave de acesso: {spaced}"])
    assert extract_keys(pdf_path) == [key]


def test_extract_keys_dedupes_by_default(tmp_path) -> None:
    key = "4" * 44
    pdf_path = _make_pdf(tmp_path, [key, key])
    assert extract_keys(pdf_path) == [key]
    assert extract_keys(pdf_path, dedupe=False) == [key, key]


def test_extract_keys_from_dir_maps_each_pdf(tmp_path) -> None:
    key_a = "1" * 44
    key_b = "2" * 44
    path_a = _make_pdf(tmp_path, [key_a], name="a.pdf")
    path_b = _make_pdf(tmp_path, [key_b], name="b.pdf")
    result = extract_keys_from_dir(tmp_path)
    assert result[path_a] == [key_a]
    assert result[path_b] == [key_b]


def test_extract_keys_raises_missing_dependency_error_without_pymupdf(monkeypatch) -> None:
    import sys

    from meu_danfe.exceptions import MissingDependencyError
    monkeypatch.setitem(sys.modules, "pymupdf", None)
    with pytest.raises(MissingDependencyError):
        extract_keys(b"not a real pdf")
