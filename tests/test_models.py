import pytest

from meu_danfe.models import DocumentStatus, FetchResult, XmlDocument


@pytest.mark.parametrize(
    ("status", "terminal", "success"),
    [
        (DocumentStatus.WAITING, False, False),
        (DocumentStatus.SEARCHING, False, False),
        (DocumentStatus.NOT_FOUND, True, False),
        (DocumentStatus.OK, True, True),
        (DocumentStatus.ERROR, True, False),
    ],
)
def test_document_status_terminal_and_success(status, terminal, success) -> None:
    assert status.is_terminal is terminal
    assert status.is_success is success


def _document(name: str) -> XmlDocument:
    return XmlDocument(key="k" * 44, name=name, doc_type="NFE", content_format="XML", data="<x/>", raw={})


def test_write_to_neutralizes_relative_path_traversal_name(tmp_path) -> None:
    out_dir = tmp_path / "xmls"
    path = _document("../../etc/passwd").write_to(out_dir)
    assert path.parent.resolve() == out_dir.resolve()
    assert path.name == "passwd"
    assert not (tmp_path / "etc").exists()


def test_write_to_neutralizes_absolute_path_name(tmp_path) -> None:
    out_dir = tmp_path / "xmls"
    path = _document("/etc/passwd").write_to(out_dir)
    assert path.parent.resolve() == out_dir.resolve()
    assert path.name == "passwd"


def test_write_to_refuses_overwrite_by_default(tmp_path) -> None:
    out_dir = tmp_path / "xmls"
    doc = _document("nota.xml")
    doc.write_to(out_dir)
    with pytest.raises(FileExistsError):
        doc.write_to(out_dir)
    doc.write_to(out_dir, overwrite=True)  # does not raise


def test_fetch_result_ok_reflects_document_presence() -> None:
    doc = _document("n.xml")
    assert FetchResult(key="k", status=DocumentStatus.OK, document=doc, error=None, polls=1).ok is True
    assert FetchResult(key="k", status=DocumentStatus.NOT_FOUND, document=None, error=None, polls=1).ok is False
