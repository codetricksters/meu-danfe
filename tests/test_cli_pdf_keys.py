import pytest

pymupdf = pytest.importorskip("pymupdf")

from meu_danfe.cli.pdf_keys import main


def _make_pdf(tmp_path, key: str, name="danfe.pdf"):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), key)
    path = tmp_path / name
    doc.save(path)
    doc.close()
    return path


def test_prints_keys_to_stdout_by_default(tmp_path, capsys) -> None:
    key = "9" * 44
    pdf_path = _make_pdf(tmp_path, key)
    rc = main(["--source", str(pdf_path)])
    assert rc == 0
    assert capsys.readouterr().out.strip() == key


def test_writes_to_out_file_when_given(tmp_path) -> None:
    key = "8" * 44
    pdf_path = _make_pdf(tmp_path, key)
    out_file = tmp_path / "keys.csv"
    rc = main(["--source", str(pdf_path), "--out", str(out_file)])
    assert rc == 0
    assert out_file.read_text(encoding="utf-8").strip() == key
