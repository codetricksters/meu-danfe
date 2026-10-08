# meu-danfe

Brazilian NFe (Nota Fiscal Eletrônica) downloader and data extractor. Integrates with the [Meu DANFE API](https://api.meudanfe.com.br) to search and retrieve electronic invoices by their 44-character access key (Chave de Acesso), and provides a CLI tool to extract NFe XML data into Excel spreadsheets.

## Requirements

- Python 3.14+
- [uv](https://github.com/astral-sh/uv) package manager

```bash
uv sync
```

### Environment variables

Copy `.env.example` to `.env` (or create `.env` manually) and fill in the required values:

```
MEU_DANFE_API_KEY=your_api_key_here
MEU_DANFE_API_URL=https://api.meudanfe.com.br
```

The `.env` file also supports optional SharePoint, SQL Server (UAU-CLOUD), and Microsoft Graph API credentials used in the notebook.

## xml_to_excel

Extracts fields from NFe XML files and saves them to an Excel spreadsheet. Each `<det>` item (product line) in the invoice becomes its own row; invoice-level fields are repeated across rows.

### Usage

```bash
# Extract a single XML file
uv run python xml_to_excel.py --file path/to/invoice.xml --name output_name

# Extract all XML files from a folder
uv run python xml_to_excel.py --source path/to/xml_folder/ --name output_name

# Specify a custom output directory (defaults to the project root)
uv run python xml_to_excel.py --source ./xmls/ --name invoices --out ./reports/
```

### Arguments

| Argument | Description |
|----------|-------------|
| `--file FILE` | Path to a single XML file (mutually exclusive with `--source`) |
| `--source DIR` | Folder containing `.xml` files (mutually exclusive with `--file`) |
| `--name NAME` | Output Excel file name, without extension **(required)** |
| `--out DIR` | Output folder. Defaults to the project root directory |

The output file is saved as `<name>.xlsx`.

### Configuring columns (`columns.json`)

The fields extracted to Excel are defined in [`columns.json`](columns.json). Each entry maps a column name to the JSON path inside the parsed XML:

```json
{
  "Número da Nota": ["nfeProc", "NFe", "infNFe", "ide", "nNF"],
  "Sequencial do Item": ["nfeProc", "NFe", "infNFe", "det", 0, "nItem"]
}
```

- The integer `0` in a path is a placeholder for the `det` item index — it is automatically replaced with the actual item number during extraction.
- Values that resolve to a dict or list are serialised as a JSON string in the cell.
- If a path does not exist in a given XML, the cell is left empty.

To add a new column, append an entry to `columns.json`. To remove one, delete its entry. No Python changes required.

## Other modules

### `pdf_key_extractor.py`

Extracts NFe access keys from DANFE PDF files using [PyMuPDF](https://pymupdf.readthedocs.io/). Useful for building an input list for the API client.

### `notas-nb.ipynb`

Jupyter notebook for interactive exploration: maps NFe XML fields, filters PDFs against invoice data in `notas.tsv`, and queries the Meu DANFE API.

```bash
uv run jupyter notebook notas-nb.ipynb
```

## API notes

- `find_and_add_nfe(key, session)` — queues a search (PUT). Costs R$0.03 per new query; CT-e items and already-cached invoices are free.
- `get_nfe(key, session)` — retrieves the XML (GET).
- Possible status responses: `WAITING`, `SEARCHING`, `NOT_FOUND`, `OK`, `ERROR`.
- **Rate limit:** sending the same access key more than once within 1 second blocks the account.
