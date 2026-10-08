import pytest

pytest.importorskip("pandas")
pytest.importorskip("openpyxl")

from meu_danfe.cli.to_excel import main


def test_single_file_writes_expected_row_count(tmp_path, fixtures_dir, capsys) -> None:
    rc = main([
        "--file", str(fixtures_dir / "nfe_multi_det.xml"),
        "--name", "saida",
        "--out", str(tmp_path),
    ])
    assert rc == 0
    assert (tmp_path / "saida.xlsx").exists()
    assert "3 row(s)" in capsys.readouterr().out


def test_missing_file_returns_nonzero(tmp_path, capsys) -> None:
    rc = main(["--file", str(tmp_path / "nope.xml"), "--name", "x", "--out", str(tmp_path)])
    assert rc != 0
