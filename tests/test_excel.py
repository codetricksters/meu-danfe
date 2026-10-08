import pytest

pytest.importorskip("pandas")
pytest.importorskip("openpyxl")

from meu_danfe.excel import write_excel
from meu_danfe.nfe.columns import default_columns


def test_write_excel_contains_the_documented_header(tmp_path) -> None:
    rows = [{name: "" for name in default_columns()}]
    rows[0]["Número da Nota"] = "123"
    out = write_excel(rows, tmp_path / "out.xlsx")

    import openpyxl
    wb = openpyxl.load_workbook(out)
    header = [cell.value for cell in next(wb.active.iter_rows(max_row=1))]
    assert "Número da Nota" in header


def test_write_excel_creates_missing_output_directory(tmp_path) -> None:
    out = write_excel([{"a": 1}], tmp_path / "nested" / "out.xlsx", columns={"a": ["a"]})
    assert out.exists()


def test_rows_to_dataframe_without_pandas_raises_missing_dependency(monkeypatch) -> None:
    import sys

    from meu_danfe.exceptions import MissingDependencyError
    monkeypatch.setitem(sys.modules, "pandas", None)
    from meu_danfe.excel import rows_to_dataframe
    with pytest.raises(MissingDependencyError):
        rows_to_dataframe([{"a": 1}], columns={"a": ["a"]})
