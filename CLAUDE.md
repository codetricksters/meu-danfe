# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Brazilian NFe (Nota Fiscal Eletrônica) downloader and data extractor. Consumes the [Meu DANFE API](https://api.meudanfe.com.br) to search for and download electronic invoices by their 44-character access keys (Chave de Acesso), then extracts the XML fields into Excel spreadsheets.

This project **does not expose an API of its own** — it is an API client plus two command-line tools.

## Package Manager

This project uses `uv`. Always use `uv` instead of `pip`:

```bash
uv sync           # install dependencies
uv add <pkg>      # add a dependency
uv run python ... # run with the project's environment
```

Requires Python 3.14+.

## Running the Project

There are no `[project.scripts]` entry points — invoke the scripts directly.

```bash
# Download XMLs by access key
uv run python app.py --key <44-char-key>
uv run python app.py --file chaves.txt --save --out ./xmls/

# Extract XML fields to Excel
uv run python xml_to_excel.py --source ./xmls/ --name invoices --out ./reports/
uv run python xml_to_excel.py --file nota.xml --name nota

uv run jupyter notebook notas-nb.ipynb
```

## Architecture

### CLIs

- [app.py](app.py) — API client and downloader CLI (`argparse` + `httpx.AsyncClient`).
  - `find_and_add_nfe(key, client)` queues a search (PUT `fd/add/{key}`, costs R$0.03/query).
  - `get_nfe(key, client)` downloads the XML (GET `fd/get/xml/{key}`); the response JSON carries `name`, `type`, `format`, `data`.
  - `process_key` runs the full lifecycle: queue → poll until a terminal status → download → save or print.
  - Concurrency is capped by a module-level `asyncio.Semaphore(10)`; polling sleeps 1 s between requests for the same key.
  - HTTP errors are mapped to Portuguese messages via `ERROR_MESSAGES` (400/401/402/403/404/500) and logged, not raised — failures return `None`.
  - Flags: `--key` / `--file` (mutually exclusive, one required), `--save`, `--out`/`-o`.

- [xml_to_excel.py](xml_to_excel.py) — XML → Excel CLI. Parses with `xmltodict` (`force_list=("det",)`) and writes one row per `<det>` item (product line), repeating invoice-level fields across rows. Flags: `--source` / `--file` (mutually exclusive, one required), `--name` (required, no extension), `--out`.
  - Extracted columns come from [columns.json](columns.json) — a map of column name → JSON path into the parsed XML. The integer `0` in a path is a placeholder for the `det` index and is substituted per item. Add or remove columns there; no Python changes needed.
  - Missing paths yield empty cells; dict/list values are serialised as JSON strings.

### One-off scripts

These have **hardcoded absolute paths** pointing at the author's machine — adjust before running.

- [pdf_key_extractor.py](pdf_key_extractor.py) — scrapes 44-digit access keys out of DANFE PDFs with PyMuPDF, appending them to `chaves_nfe.csv`. Reads from a hardcoded `WD`.
- [filter_files.py](filter_files.py) — filters `todo.csv` into `out.csv`, dropping keys already downloaded to a hardcoded `src_dir`.
- [notas-nb.ipynb](notas-nb.ipynb) — exploration notebook: maps NFe XML fields, filters PDFs against invoice data in [notas.tsv](notas.tsv).

### Configuration

Credentials are loaded from `.env` via `python-dotenv` (`dotenv_values`, not `load_dotenv` — nothing reaches `os.environ`). Required variables:
- `MEU_DANFE_API_KEY` — API token, sent as the `Api-Key` header
- `MEU_DANFE_API_URL` — base URL for `httpx.AsyncClient(base_url=...)`, so endpoint paths are relative (`fd/add/{key}`)

The `.env` also contains SharePoint, SQL Server (UAU-CLOUD), and Microsoft Graph API credentials used by the notebook.

### API Behavior

- `find_and_add_nfe` returns a response whose `status` is one of: `WAITING`, `SEARCHING`, `NOT_FOUND`, `OK`, `ERROR`. The terminal set is `NOT_FOUND`, `OK`, `ERROR`.
- **Rate limit**: sending the same access key more than once within 1 second blocks the account. Keep the `await asyncio.sleep(1)` in the polling loop.
- CT-e items and already-cached invoices are free; new NFe searches cost R$0.03 each. Avoid re-running downloads over keys already fetched.
