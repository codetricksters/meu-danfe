from meu_danfe.nfe.parser import extract_rows, parse_xml


def test_multi_det_produces_one_row_per_item_and_repeats_invoice_fields(fixtures_dir) -> None:
    document = parse_xml(fixtures_dir / "nfe_multi_det.xml")
    rows = extract_rows(document)
    assert len(rows) == 3
    assert {row["Número da Nota"] for row in rows} == {"123"}
    assert [row["Descrição do Produto"] for row in rows] == ["Produto Um", "Produto Dois", "Produto Tres"]


def test_single_det_still_produces_exactly_one_row(fixtures_dir) -> None:
    # Regression for the xmltodict force_list gotcha: without it, a lone
    # <det> collapses to a dict and len() would count dict keys, not rows.
    document = parse_xml(fixtures_dir / "nfe_single_det.xml")
    rows = extract_rows(document)
    assert len(rows) == 1
    assert rows[0]["Código do Produto"] == "P001"


def test_missing_optional_fields_yield_none_not_an_exception(fixtures_dir) -> None:
    document = parse_xml(fixtures_dir / "nfe_sparse.xml")
    rows = extract_rows(document)
    assert rows[0]["Informações Complementares"] is None
    assert rows[0]["Data de Saída/Entrada"] is None


def test_parse_xml_accepts_bytes_with_declared_encoding(fixtures_dir) -> None:
    raw = (fixtures_dir / "nfe_single_det.xml").read_bytes()
    document = parse_xml(raw)
    assert extract_rows(document)[0]["Código do Produto"] == "P001"


def test_extract_rows_accepts_a_custom_column_map(fixtures_dir) -> None:
    document = parse_xml(fixtures_dir / "nfe_multi_det.xml")
    custom = {"produto": ["nfeProc", "NFe", "infNFe", "det", 0, "prod", "xProd"]}
    rows = extract_rows(document, columns=custom)
    assert rows == [{"produto": "Produto Um"}, {"produto": "Produto Dois"}, {"produto": "Produto Tres"}]
