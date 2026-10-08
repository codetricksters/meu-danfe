from meu_danfe.storage import sanitize_filename


def test_sanitize_filename_strips_directory_components() -> None:
    assert sanitize_filename("../../etc/passwd", fallback="x.xml") == "passwd"
    assert sanitize_filename("/etc/passwd", fallback="x.xml") == "passwd"


def test_sanitize_filename_strips_unsafe_characters() -> None:
    assert sanitize_filename('weird:name?.xml', fallback="x.xml") == "weird_name_.xml"


def test_sanitize_filename_falls_back_on_empty_result() -> None:
    assert sanitize_filename("...", fallback="fallback.xml") == "fallback.xml"
