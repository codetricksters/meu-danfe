# meu-danfe

Brazilian NFe (Nota Fiscal Eletrônica) toolkit: a library that consumes the [Meu DANFE API](https://api.meudanfe.com.br) to search for and download electronic invoices by their 44-character access key (Chave de Acesso), parses NFe/CT-e XML into structured data, and extracts access keys from DANFE PDFs — plus three thin CLIs and an optional local HTTP server built on top of it.

Any other Python project can depend on this one directly and call the library, with no subprocess and no need to reimplement the API's status polling or its rate-limit rule.

## Requirements

- Python ≥3.12
- [uv](https://github.com/astral-sh/uv) package manager

```bash
uv sync --extra all   # all optional extras (excel, pdf, dotenv, server)
```

### Environment variables

Copy `.env.example` to `.env` and fill in the required value:

```
MEU_DANFE_API_KEY=your_api_key_here
MEU_DANFE_API_URL=https://api.meudanfe.com.br/v2/
```

`MEU_DANFE_SERVER_TOKEN` is only needed if you run the optional HTTP server.

## As a library

```python
import asyncio
from pathlib import Path

from meu_danfe import MeuDanfeAsyncClient, MeuDanfeClient, DocumentStatus


# Async (recommended) — download a batch of keys
async def main() -> None:
    async with MeuDanfeAsyncClient.from_env() as client:
        for result in await client.fetch_many(["3224...", "3124..."]):
            if result.ok:
                result.document.write_to(Path("./xmls"))
            elif result.status is DocumentStatus.NOT_FOUND:
                print(f"{result.key}: não encontrada")
            else:
                print(f"{result.key}: {result.error}")

asyncio.run(main())

# Sync facade — same pacing guarantees, no asyncio required
with MeuDanfeClient.from_env() as client:
    document = client.fetch("32240983249078000171...")
    print(document.name, document.doc_type, len(document.data))
```

```python
# Parse an XML into rows (one per <det> item)
from meu_danfe.nfe import parse_xml, extract_rows

rows = extract_rows(parse_xml(Path("nota.xml")))
rows = extract_rows(parse_xml(Path("nota.xml")), columns=my_own_column_map)
```

```python
# Extract access keys from a PDF
from meu_danfe.pdf import extract_keys, extract_keys_from_dir

keys = extract_keys(Path("danfe.pdf"))
by_file = extract_keys_from_dir(Path("/some/dir"), recursive=True)
```

The vendor's rule — never request the same access key more than once within 1 second, or the account gets blocked — is enforced inside the client (`KeyPacer`), across every endpoint, for both the async client and the sync facade. There is no method that bypasses it.

## CLIs

### `meu-danfe-to-excel`

Extracts fields from NFe XML files into an Excel spreadsheet. Each `<det>` item (product line) becomes its own row; invoice-level fields repeat across rows.

```bash
uv run meu-danfe-to-excel --file path/to/invoice.xml --name output_name
uv run meu-danfe-to-excel --source path/to/xml_folder/ --name output_name
uv run meu-danfe-to-excel --source ./xmls/ --name invoices --out ./reports/
```

| Argument | Description |
|----------|-------------|
| `--file FILE` | Path to a single XML file (mutually exclusive with `--source`) |
| `--source DIR` | Folder containing `.xml` files (mutually exclusive with `--file`) |
| `--name NAME` | Output Excel file name, without extension **(required)** |
| `--out DIR` | Output folder. Defaults to the current directory |
| `--columns PATH` | A JSON file overriding the default column map |
| `--recursive` | Recurse into subfolders of `--source` |

#### Configuring columns

The default fields are defined in [`src/meu_danfe/nfe/columns.json`](src/meu_danfe/nfe/columns.json) — a map of column name to JSON path inside the parsed XML:

```json
{
  "Número da Nota": ["nfeProc", "NFe", "infNFe", "ide", "nNF"],
  "Sequencial do Item": ["nfeProc", "NFe", "infNFe", "det", 0, "nItem"]
}
```

The integer `0` in a path is a placeholder for the `det` item index — it is automatically replaced with the actual item number during extraction. Values that resolve to a dict or list are serialised as a JSON string. A missing path yields an empty cell. Pass `--columns` with your own JSON file to override the defaults entirely — no Python changes required.

### `meu-danfe` / `meu-danfe-download`

```bash
uv run meu-danfe --key <44-char-key>
uv run meu-danfe --file chaves.txt --save --out ./xmls/
uv run meu-danfe --file chaves.txt --exclude-existing-in ./xmls/   # skip already-downloaded keys
```

| Argument | Description |
|----------|-------------|
| `--key` / `--file` | Single key, or a file with one key per line (mutually exclusive, required) |
| `--save` | Write XML to disk instead of printing to stdout |
| `--out`, `-o` | Output directory for `--save` (default: current directory) |
| `--exclude-existing-in DIR` | Skip keys already downloaded as `*.xml` in `DIR` — saves R$0,03 per skipped key |
| `--concurrency`, `--timeout`, `--max-polls`, `--poll-interval` | Tuning knobs, forwarded to the client |
| `--env-file PATH` | Load `.env`-style config from this file (requires the `dotenv` extra) |

### `meu-danfe-pdf-keys`

```bash
uv run meu-danfe-pdf-keys --source path/to/danfe.pdf
uv run meu-danfe-pdf-keys --source path/to/pdfs/ --recursive --out keys.txt
```

## Optional local HTTP server

For non-Python consumers. Requires the `server` extra and `MEU_DANFE_SERVER_TOKEN`:

```bash
MEU_DANFE_SERVER_TOKEN=segredo uv run python -m meu_danfe.server
```

Binds `127.0.0.1` by default (pass `--allow-remote` to bind elsewhere) and refuses to start without a token. Every request needs an `X-Meu-Danfe-Token` header matching it. Endpoints: `GET /healthz` (no auth), `POST /v1/documents/fetch` (NDJSON stream, one line per key as it completes), `POST /v1/documents/parse`, `POST /v1/pdf/keys`.

One `MeuDanfeAsyncClient` is shared for the whole server lifetime — the pacing guarantee holds across requests, not just within one.

## Development

```bash
uv run pytest -q          # no real network, no cost — httpx.MockTransport throughout
uv run meu-danfe --help
```

## Other project files

- `notebooks/notas-nb.ipynb` — exploration notebook: maps NFe XML fields, imports `meu_danfe` directly rather than holding its own copy of the client.
- `data/` (gitignored) — local scratch inputs/outputs, not part of the library.
