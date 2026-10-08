# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`meu_danfe` is a Brazilian NFe (Nota Fiscal Eletrônica) toolkit: an importable library that consumes the [Meu DANFE API](https://api.meudanfe.com.br) to search for and download electronic invoices by their 44-character access key (Chave de Acesso), parses NFe/CT-e XML into structured rows, and extracts access keys from DANFE PDFs. Three thin CLIs and an optional local HTTP server sit on top of the library — they hold no logic of their own.

Any other tool can depend on this project directly (`uv add --editable`, a path, or a git URL) and call the library — no subprocess, no reimplementing the API's state machine or its rate-limit rule.

## Package Manager

This project uses `uv`. Always use `uv` instead of `pip`:

```bash
uv sync                      # install core dependencies
uv sync --extra all          # install every optional extra (excel, pdf, dotenv, server)
uv add <pkg>                 # add a dependency
uv run python ...            # run with the project's environment
uv run pytest -q             # run the test suite (no real network, no cost)
```

Requires Python ≥3.12.

## Running the Project

```bash
# Download XMLs by access key (installed as a script)
uv run meu-danfe --key <44-char-key>
uv run meu-danfe --file chaves.txt --save --out ./xmls/

# Extract XML fields to Excel
uv run meu-danfe-to-excel --source ./xmls/ --name invoices --out ./reports/

# Extract access keys from DANFE PDFs
uv run meu-danfe-pdf-keys --source ./pdfs/ --out keys.txt

# Optional local HTTP server (requires MEU_DANFE_SERVER_TOKEN)
uv run python -m meu_danfe.server

uv run jupyter notebook notebooks/notas-nb.ipynb
```

## Architecture

### Library (`src/meu_danfe/`)

- `config.py` — `MeuDanfeConfig`, a frozen dataclass. Explicit constructor args are primary; `.from_env()` is the **only** place that reads `os.environ` or a `.env` file, and only when called. Nothing in this package touches the environment or disk at import time — importing `meu_danfe` with no `.env` present and no env vars set never raises.
- `exceptions.py` — the exception tree every other module raises. `ERROR_MESSAGES` holds the vendor's Portuguese operator-facing text, verbatim, for HTTP 400/401/402/403/404/500; `error_from_response()` maps a response to the right typed exception.
- `models.py` — `DocumentStatus` (WAITING/SEARCHING/NOT_FOUND/OK/ERROR, with `.is_terminal`/`.is_success`), `AddResult`, `XmlDocument` (with `.write_to()`), `FetchResult` (with `.ok`).
- `pacing.py` — `KeyPacer`: guarantees ≥1 second between consecutive requests for the *same* access key, across every endpoint (add/poll/download), and bounds overall concurrency. This is the one rule a consumer must never be able to bypass — repeating a key within 1 second blocks the Meu DANFE account.
- `client.py` — `MeuDanfeAsyncClient`: `add`, `get_xml`, `wait_for`, `fetch`, `fetch_many`, `iter_fetch`. The canonical implementation; async.
- `sync_client.py` — `MeuDanfeClient`: the same method names, no `async`, running the *same* async client on a dedicated background event loop so the pacer's state and the HTTP connection pool survive across calls.
- `storage.py` — `save_xml()` sanitizes the vendor-supplied filename so it can never write outside the destination directory.
- `keys.py` — access key normalisation/validation and `existing_keys_in_dir()` (skip keys already downloaded, to avoid paying R$0,03 twice).
- `nfe/` — `columns.json` + `columns.py` (the column-name → JSON-path map, overridable) and `parser.py` (`parse_xml`, `extract_rows`, one row per `<det>` product line, invoice fields repeated).
- `pdf.py` — `extract_keys()` / `extract_keys_from_dir()`. Requires the `pdf` extra.
- `excel.py` — `write_excel()`. Requires the `excel` extra.
- `server/` — optional FastAPI app (`create_app()`), token-gated, binds `127.0.0.1` by default, one shared client per app lifetime. Requires the `server` extra.

### CLIs (`src/meu_danfe/cli/`)

Thin `argparse` wrappers — `download.py` (`meu-danfe`/`meu-danfe-download`), `to_excel.py` (`meu-danfe-to-excel`), `pdf_keys.py` (`meu-danfe-pdf-keys`). All logic lives in the library above; these only parse args, call it, and format output.

### Optional extras

| Extra | Adds | Used by |
|---|---|---|
| `excel` | pandas, openpyxl | `excel.py`, `meu-danfe-to-excel` |
| `pdf` | PyMuPDF | `pdf.py`, `meu-danfe-pdf-keys` |
| `dotenv` | python-dotenv | `MeuDanfeConfig.from_env(dotenv_path=...)` |
| `server` | fastapi, uvicorn, python-multipart | `server/` |
| `cli` | excel + pdf + dotenv | running all three CLIs |
| `all` | cli + server | everything |

### Configuration

Required variables (see `.env.example`): `MEU_DANFE_API_KEY` (sent as the `Api-Key` header) and `MEU_DANFE_API_URL` (defaults to `https://api.meudanfe.com.br/v2/` — note the `/v2/`). The optional server reads `MEU_DANFE_SERVER_TOKEN` and refuses to start without it.

### API Behavior

- `add()`/`wait_for()` return a status in `WAITING`, `SEARCHING`, `NOT_FOUND`, `OK`, `ERROR`. The terminal set is `NOT_FOUND`, `OK`, `ERROR`.
- **Rate limit**: sending the same access key more than once within 1 second blocks the account — enforced by `KeyPacer`, not left to the caller.
- CT-e items and already-cached invoices are free; new NFe searches cost R$0,03 each. `existing_keys_in_dir()` / `--exclude-existing-in` avoid paying twice for a key already downloaded.

### Notes on the project's history

- `notebooks/notas-nb.ipynb` is a prior exploration notebook, now updated to import the library instead of holding its own (older, synchronous, less careful) copy of the client and PDF key extractor.
- `data/` (gitignored) holds local scratch inputs/outputs (`chaves_nfe.csv`, `notas.tsv`, `todo.csv`, `out.csv`) — not part of the library, not committed.
