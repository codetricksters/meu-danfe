import argparse
import asyncio
from dotenv import dotenv_values
from pathlib import Path
import httpx

ROOT_DIR = Path(__file__).resolve().parent

config: dict = dotenv_values(ROOT_DIR / ".env")
API_KEY = config["MEU_DANFE_API_KEY"]
BASE_URL = config.get("MEU_DANFE_API_URL", "")
HEADERS = {"Api-Key": API_KEY, "accept": "application/json"}

ERROR_MESSAGES = {
    400: "Chave de Acesso inválida.",
    401: "Api-Key não informada ou inválida.",
    402: "Saldo insuficiente. Para adicionar créditos acesse a Área do Cliente.",
    403: "Api-Key foi substituida. Acesse a Área do Cliente no menu API / Integração.",
    404: "NF-e/CT-e não encontrada na sua Área do Cliente. Favor adiciona-la antes do download.",
    500: "Erro ao solicitar download do XML! Confira em sua Área do Cliente no menu Minhas NFs / Minhas CTs, o NF-e/CT-e adicionada.",
}

TERMINAL_STATUSES = {"NOT_FOUND", "OK", "ERROR"}

# Source - https://stackoverflow.com/a/51026159
# Posted by rouble, modified by community. See post 'Timeline' for change history
# Retrieved 2026-04-25, License - CC BY-SA 4.0


async def find_and_add_nfe(key: str, client: httpx.AsyncClient) -> httpx.Response | None:
    """
    URL Completa: https://api.meudanfe.com.br/v2/fd/add/{Chave-Acesso}

    A busca é feita simplesmente informando a Chave de Acesso no path {Chave-Acesso} e a Api-Key no header da requisição.
    A resposta é um objeto em JSON, contendo detalhes da solicitação com um dos seguintes status:
        WAITING: Na fila para consultar
        SEARCHING: Consultando ou aguardando resposta
        NOT_FOUND: Não encontrado ou não existe
        OK: Consulta realizada com sucesso
        ERROR: Falha ao consultar
    Busca de NF-e via chave de acesso é cobrado R$ 0,03 (3 centavos) por consulta.
    NÃO cobramos buscas de documentos já adicionadas no menu Minhas NFs / Minhas CTs
    Busca de qualquer CT-e já na nossa base de dados tambem são GRÁTIS. (NÃO fazemos busca de CT-e direto na Receita Federal)
    Após solicitação, o endpoint pode ser usado para consultar o status.
        AVISO: Varias solicitações da mesma chave de acesso em menos de 1 segundo BLOQUEARÁ sua conta e API Meu Danfe!
        AVISO: Para evitar o bloqueio, favor aguardar ao menos 1 segundo para consultar o status da solicitação.
    """
    try:
        response = await client.put(f"fd/add/{key}")
        response.raise_for_status()
        return response
    except httpx.HTTPStatusError as e:
        msg = ERROR_MESSAGES.get(e.response.status_code, str(e))
        print(f"{key}: {msg}")
        return None


async def get_nfe(key: str, client: httpx.AsyncClient) -> httpx.Response | None:
    """
    URL Completa: https://api.meudanfe.com.br/v2/fd/get/xml/{Chave-Acesso}

    O download é feito simplesmente informando a Chave de Acesso no path {Chave-Acesso} e a Api-Key no header da requisição.
    A resposta é um objeto em JSON com os campos:
        name:   nome do arquivo sugerido, ex: "filename.xml"
        type:   tipo do documento, ex: "NFE"
        format: formato do conteúdo, ex: "XML"
        data:   conteúdo XML como string, ex: "<?xml version..."
    """
    try:
        response = await client.get(f"fd/get/xml/{key}")
        response.raise_for_status()
        return response
    except httpx.HTTPStatusError as e:
        msg = ERROR_MESSAGES.get(e.response.status_code, str(e))
        print(f"{key}: {msg}")
        return None


def save_nfe(filename: str, data: str, out_dir: Path) -> None:
    """Write XML data to out_dir/filename, creating the full directory tree if needed."""
    path = out_dir / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")
    print(f"Saved: {path}")


sem = asyncio.Semaphore(10)


async def process_key(key: str, client: httpx.AsyncClient, save: bool = False, out_dir: Path = ROOT_DIR) -> None:
    """
    Orchestrates the full lifecycle of fetching one NFe/CTe by its 44-char access key.

    Flow:
      1. Acquire a semaphore slot to cap concurrent API requests (avoids account blocking).
      2. Submit the key to the Meu DANFE queue via PUT fd/add/{key}.
      3. Poll the same endpoint every second until the API reports a terminal status
         (OK, NOT_FOUND, or ERROR).  The 1-second sleep is mandatory — the API blocks
         accounts that repeat the same key faster than that.
      4. On OK, download the XML; if `save` is True, persist it using the filename
         returned by the API (falls back to "{key}.xml"); otherwise print the data.

    Args:
        key:    44-character NFe/CTe access key (Chave de Acesso).
        client: Shared async HTTP client, pre-configured with base URL and auth headers.
        save:   When True, write the XML to disk instead of printing it.
    """
    # Limit concurrency: at most `sem` keys are in-flight at once to respect rate limits.
    async with sem:
        # Submit the key for queuing/searching; None means an HTTP error was already logged.
        response = await find_and_add_nfe(key, client)
        if response is None:
            return

        # Poll until the API moves the request out of transient states (WAITING / SEARCHING).
        # Sleep first to satisfy the ≥1 s between identical-key requests requirement.
        while response.json().get("status") not in TERMINAL_STATUSES:
            await asyncio.sleep(1)
            response = await find_and_add_nfe(key, client)
            if response is None:
                return

        # Dispatch on the terminal status: download XML on success, log anything else.
        status = response.json().get("status")
        if status == "OK":
            nfe_response = await get_nfe(key, client)
            if nfe_response is None:
                return
            payload = nfe_response.json()
            filename = payload.get("name") or f"{key}.xml"
            data = payload.get("data", "")
            if save:
                save_nfe(filename, data, out_dir)
            else:
                print(data)
        else:
            print(f"{key}: {status}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Meu DANFE downloader")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--key", help="Single 44-char NFe/CTe access key")
    group.add_argument("--file", type=Path, help="File with one access key per line")
    parser.add_argument(
        "--save",
        action="store_true",
        default=False,
        help="Save each XML to disk using the filename returned by the API (default: print to stdout)",
    )
    parser.add_argument(
        "--out", "-o",
        type=Path,
        default=None,
        help="Directory where XML files are saved when --save is set (default: directory of app.py)",
    )
    return parser.parse_args()


def load_keys(args: argparse.Namespace) -> list[str]:
    if args.key:
        return [args.key]
    return [line.strip() for line in args.file.read_text().splitlines() if line.strip()]


async def amain() -> None:
    args = parse_args()
    keys = load_keys(args)
    out_dir: Path = (args.out or ROOT_DIR).resolve()
    if args.save:
        out_dir.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(base_url=BASE_URL, headers=HEADERS) as client:
        await asyncio.gather(*(process_key(k, client, save=args.save, out_dir=out_dir) for k in keys))


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
