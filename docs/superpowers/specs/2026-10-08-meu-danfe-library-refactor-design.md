# Refatorar `meu-danfe-downloader` em biblioteca importável

> **Addendum (2026-10-08, antes da execução):** o XML de origem usado para
> gerar `test_output.xlsx` não existe em nenhum lugar desta máquina (o
> diretório OneDrive referenciado pelo notebook/`pdf_key_extractor.py` já
> foi removido). **`test_output.xlsx` não pode servir de baseline de
> regressão como a Fase 1.2 original previa** — não há como diferenciar
> contra uma fonte conhecida. Ruling: a verificação do parser passa a usar
> fixtures XML sintéticas (`nfe_multi_det.xml`, `nfe_single_det.xml`,
> `nfe_sparse.xml`), que já estavam no desenho de testes original como
> plano B. `test_output.xlsx` permanece no disco, ignorado pelo git, sem
> uso neste refactor.
>
> O `.gitignore` tinha um bug (`.csv` em vez de `*.csv`) que não excluía
> nenhum `.csv` de verdade — corrigido no commit de baseline, antes do
> primeiro `git add`, junto com excludes explícitos para `notas.tsv` e
> `test_output.xlsx`.

## Context

Hoje o projeto só é utilizável por linha de comando. Qualquer outra ferramenta que queira
buscar/parsear NFe tem duas opções ruins: chamar `app.py` via subprocess, ou reimplementar a
lógica. Três cópias do cliente já existem e divergiram (`app.py` async, uma cópia sync antiga
em `notas-nb.ipynb`, e `extract_key` duplicado entre o notebook e `pdf_key_extractor.py` com
regex diferente). A causa raiz é estrutural:

- **`pyproject.toml` não tem `[build-system]`** → o projeto não é instalável por nada.
- Layout plano, sem namespace de pacote.
- `app.py:9-10` lê `.env` e faz `config["MEU_DANFE_API_KEY"]` **em tempo de import** → `import`
  quebra com `KeyError` sem `.env`.
- Erros são `print()`ados e as funções retornam `None` (`app.py:52-55,73-76`); retornam
  `httpx.Response` cru e o chamador faz `.json().get("status")` (`app.py:117`).
- `sem = asyncio.Semaphore(10)` é global de módulo (`app.py:87`) → preso ao event loop errado.
- A regra que mais importa — **não repetir a mesma chave em menos de 1 s, sob pena de bloqueio
  da conta** — é só um `await asyncio.sleep(1)` solto no loop de polling (`app.py:118`).

**Resultado pretendido:** um pacote `meu_danfe` instalável e tipado, com a máquina de estados, o
mapeamento de erros e o controle de 1 s/chave encapsulados, de modo que nenhum consumidor precise
recriá-los nem possa violá-los por acidente. Os CLIs de hoje passam a ser cascas finas sobre a
biblioteca, e um servidor HTTP opcional atende consumidores não-Python.

**Decisões do usuário (fixas):** superfície pública cobre cliente + parsing + extração de chaves
de PDF; o projeto não tem nenhuma dependência nem conhecimento de outro projeto (ex.: `uau`);
núcleo async com facade síncrona; servidor HTTP incluído como extra opcional, bind local com
token obrigatório e endpoints de alto nível (lote).

---

## Layout alvo (src-layout)

```
src/meu_danfe/
├── __init__.py          # re-exports públicos, __all__, logging NullHandler
├── py.typed             # marcador PEP 561
├── __main__.py          # python -m meu_danfe → cli.download:main
├── config.py            # MeuDanfeConfig (frozen) + from_env(); ÚNICO leitor de ambiente
├── exceptions.py        # árvore de exceções + ERROR_MESSAGES verbatim + mapa status→classe
├── models.py            # DocumentStatus, AddResult, XmlDocument, FetchResult
├── keys.py              # normalize/validate/load de chaves; existing_keys_in_dir
├── pacing.py            # KeyPacer: gate ≥1s por chave + limite de concorrência por cliente
├── client.py            # MeuDanfeAsyncClient: add/get_xml/wait_for/fetch/fetch_many/iter_fetch
├── sync_client.py       # MeuDanfeClient: facade sync sobre o cliente async
├── storage.py           # save_xml() com sanitização de nome de arquivo
├── nfe/
│   ├── columns.json     # MOVIDO da raiz; package data
│   ├── columns.py       # default_columns()/load_columns() via importlib.resources
│   └── parser.py        # parse_xml, extract_rows (+ _get/_resolve_path/_serialize)
├── pdf.py               # extract_keys / extract_keys_from_dir        [extra: pdf]
├── excel.py             # rows_to_dataframe / write_excel             [extra: excel]
├── cli/
│   ├── _common.py       # setup de logging, argparse compartilhado, exit codes
│   ├── download.py      # era app.py
│   ├── to_excel.py      # era xml_to_excel.py
│   └── pdf_keys.py      # era pdf_key_extractor.py
└── server/              # [extra: server]
    ├── app.py           # create_app(): FastAPI, lifespan com UM cliente compartilhado
    ├── auth.py          # dependência de token (secrets.compare_digest)
    ├── schemas.py       # modelos pydantic de request/response
    └── __main__.py      # python -m meu_danfe.server (uvicorn, bind 127.0.0.1)
tests/                   # ver seção de verificação
notebooks/notas-nb.ipynb # MOVIDO; importa a biblioteca, duplicatas removidas
data/                    # gitignored: chaves_nfe.csv, notas.tsv, todo.csv, out.csv
```

`filter_files.py` é **removido**: sua única ideia reaproveitável vira `keys.existing_keys_in_dir()`;
o resto é manipulação de dados específica do autor, não comportamento de biblioteca.

## API pública

```python
class DocumentStatus(StrEnum):            # WAITING/SEARCHING/NOT_FOUND/OK/ERROR
    is_terminal: bool                     # {NOT_FOUND, OK, ERROR} = TERMINAL_STATUSES de hoje
    is_success: bool

@dataclass(frozen=True, slots=True)
class XmlDocument:                        # campos name/type/format/data da resposta da API
    key: str; name: str; doc_type: str; content_format: str; data: str
    raw: Mapping[str, Any]
    safe_filename: str
    def write_to(self, out_dir: Path, *, filename=None, overwrite=False) -> Path

@dataclass(frozen=True, slots=True)
class FetchResult:                        # devolvido por fetch_many/iter_fetch; NUNCA levanta
    key: str; status: DocumentStatus | None
    document: XmlDocument | None; error: MeuDanfeError | None; polls: int
    ok: bool

class MeuDanfeAsyncClient:
    def __init__(self, api_key=None, *, base_url=DEFAULT_BASE_URL, config=None,
                 max_concurrency=10, timeout=30.0,
                 transport=None, http_client=None,          # seams de teste / pool próprio
                 clock=time.monotonic, sleep=asyncio.sleep, # seams de teste
                 logger=None): ...
    @classmethod
    def from_env(cls, **overrides) -> Self
    async def __aenter__/__aexit__/aclose
    async def add(key) -> AddResult
    async def get_xml(key) -> XmlDocument
    async def wait_for(key, *, max_polls=None, poll_interval=None) -> AddResult
    async def fetch(key) -> XmlDocument                     # add→wait_for→get_xml; levanta
    async def fetch_many(keys) -> list[FetchResult]
    def iter_fetch(keys) -> AsyncIterator[FetchResult]      # resultados conforme completam

class MeuDanfeClient:   # superfície idêntica, sem async; __enter__/__exit__/close
```

```python
# meu_danfe.nfe
ColumnMap = Mapping[str, Sequence[str | int]]
def parse_xml(source: str | bytes | Path | IO[bytes]) -> dict[str, Any]
def extract_rows(document, columns: ColumnMap | None = None) -> list[dict[str, Any]]
def iter_rows_from_dir(source, columns=None, *, recursive=False,
                       on_error: Literal["warn","raise","skip"] = "warn")
def default_columns() -> ColumnMap          # cacheado, importlib.resources
def load_columns(path: Path) -> ColumnMap   # mapa do consumidor

# meu_danfe.pdf                                              [extra: pdf]
ACCESS_KEY_IN_TEXT_RE = re.compile(r"\d(?:[ .\-]*\d){43}")   # verbatim de pdf_key_extractor.py:13
def extract_keys(source: Path | bytes | IO[bytes], *, dedupe=True) -> list[str]
def extract_keys_from_dir(root, *, recursive=True, pattern="*.pdf") -> dict[Path, list[str]]

# meu_danfe.keys
def normalize_key(raw) -> str; def validate_key(raw, *, check_digit=False) -> str
def load_keys(path) -> list[str]; def existing_keys_in_dir(d, *, pattern="*.xml") -> set[str]
```

Uso pelo consumidor:

```python
async with MeuDanfeAsyncClient(api_key="...") as client:          # 1. baixar em lote
    for r in await client.fetch_many(keys):
        if r.ok: r.document.write_to(Path("./xmls"))
        else:    log.error("%s: %s", r.key, r.error)

with MeuDanfeClient.from_env() as client:                          # 1b. consumidor sync
    doc = client.fetch(key)                                        # regra de 1s continua valendo

rows = extract_rows(parse_xml(Path("nota.xml")))                   # 2. parsear (1 linha por <det>)
keys = extract_keys(Path("danfe.pdf"))                             # 3. chaves de um PDF
```

## Config

`MeuDanfeConfig` frozen com `api_key`, `base_url`, `timeout`, `max_concurrency`,
`min_key_interval=1.0`, `max_polls=30`, `allow_unsafe_interval=False`. `__repr__` mascara a
api_key (hoje ela vive num `HEADERS` global, `app.py:12`, e sai em qualquer repr/log).

- Argumentos explícitos são primários: `MeuDanfeAsyncClient("chave")` funciona sem ambiente nenhum.
  **Nada em `meu_danfe` toca `os.environ` ou disco em tempo de import** — fixado por teste.
- `from_env()` é opt-in, lê `os.environ`, aceita um mapping injetado para testes. `.env` só é lido
  se `dotenv_path=` for passado (import lazy de `python-dotenv`); só o CLI passa isso.
- `MEU_DANFE_API_KEY` ausente/vazia → `ConfigurationError` com mensagem acionável, nunca `KeyError`.
- `MEU_DANFE_API_URL` ausente → `DEFAULT_BASE_URL = "https://api.meudanfe.com.br/v2/"`, não `""`
  (hoje `""` gera `httpx.UnsupportedProtocol` de dentro do httpx).
- `min_key_interval < 1.0` → `ConfigurationError`, a menos que `allow_unsafe_interval=True`.

## Exceções

`ERROR_MESSAGES` migra **verbatim** (mesmas 6 chaves, mesmas strings em português) para
`exceptions.py`; cada classe carrega sua mensagem. `str(exc)` renderiza `f"{key}: {message}"` —
exatamente o formato que `app.py` imprime hoje, então a saída do CLI não muda.

```
MeuDanfeError
├── ConfigurationError, MissingDependencyError, InvalidAccessKeyError
├── MalformedResponseError          # corpo sem JSON ou sem campo `status`
├── TransportError                  # envolve httpx.TransportError/TimeoutException
├── PollTimeoutError                # .key .polls .last_status
├── DocumentUnavailableError        # captura comum de "não há XML"
│   ├── DocumentNotFoundError       → HTTP 404
│   ├── NotFoundStatusError         → status terminal NOT_FOUND
│   └── SearchFailedError           → status terminal ERROR
└── MeuDanfeAPIError                # .status_code .key .message .response
    ├── InvalidKeyResponseError  400   ├── AuthenticationError      401
    ├── InsufficientBalanceError 402   ├── ApiKeyReplacedError       403
    ├── DownloadRequestError     500   └── UnexpectedStatusError     outros
```

## Pacing — o núcleo do valor

`KeyPacer` em `pacing.py`, com `async with pacer.slot(key)` envolvendo **toda** requisição:

1. **Primitivas criadas na primeira utilização dentro do loop em execução** e cacheadas por loop —
   elimina o risco de event loop errado do `Semaphore` global atual.
2. **`asyncio.Lock` por chave**: serializa todas as requisições daquela chave. Hoje isso não ocorre
   porque `process_key` é chamado uma vez por chave, mas um consumidor de biblioteca pode fazê-lo.
3. **Gate monotônico**: `wait = min_interval - (clock() - last_seen[key])`. O timestamp é gravado num
   `finally:` na **saída**, então o intervalo medido é do fim da requisição anterior ao início da
   próxima — conservador, nunca abaixo de 1 s.
4. **Vale para todos os endpoints daquela chave** — `add`, cada poll e `get_xml`. O aviso do
   fornecedor é sobre a chave, não sobre a URL, e hoje não há intervalo algum entre o último
   `fd/add` e o `fd/get/xml`.
5. **Não é contornável**: nenhum método público faz requisição sem passar pelo `slot`.
6. **Memória limitada**: `OrderedDict` com teto de chaves rastreadas, podando entradas antigas sem
   lock ativo — um serviço de vida longa não acumula um lock por chave processada.
7. **`clock`/`sleep` injetáveis** → os testes provam o intervalo de 1 s em tempo falso, sem dormir.
8. Concorrência vem de `config.max_concurrency` (default 10, igual ao semáforo atual).

Limitação a documentar em negrito no README: o pacing é por processo (com um registry de
`KeyPacer` por hash da api_key, é por processo inteiro em vez de por cliente). **Entre processos
não há coordenação** — é a única forma de o consumidor ainda bloquear a conta.

## Sync vs async

Núcleo async é canônico. A facade sync roda o **mesmo** `MeuDanfeAsyncClient` num event loop
dedicado, em thread daemon própria do cliente (`_LoopRunner` com
`asyncio.run_coroutine_threadsafe`). Cada método é `return self._runner.run(self._async.fetch(key))`
— **zero lógica duplicada**.

Por que não `asyncio.run()` por chamada: cria um loop novo a cada vez, descartando (a) o pool de
conexões do httpx e (b) o estado do `KeyPacer` — o que **silenciosamente quebraria a regra de 1 s
entre duas chamadas sync consecutivas para a mesma chave**. É exatamente a falha que a refatoração
existe para evitar; há teste fixando isso. Por que não um `httpx.Client` paralelo: duplicaria a
máquina de estados.

## CLIs

Cascas de ~60 linhas: parse de args → monta config → chama a biblioteca → formata → exit code.

```toml
[project.scripts]
meu-danfe = meu-danfe-download = "meu_danfe.cli.download:main"
meu-danfe-to-excel              = "meu_danfe.cli.to_excel:main"
meu-danfe-pdf-keys              = "meu_danfe.cli.pdf_keys:main"
```

- `download`: flags de hoje preservadas (`--key`/`--file` mutuamente exclusivas, `--save`,
  `--out`/`-o`). Novas: `--concurrency`, `--timeout`, `--poll-interval`, `--max-polls`,
  `--env-file`, `--log-level`, `--exclude-existing-in DIR` (pula chaves já baixadas — economiza
  R$ 0,03 cada, substituindo `filter_files.py`). Exit codes: 0 ok, 2 argparse, 3 falhas parciais,
  4 config, 1 inesperado.
- `to_excel`: `--source`/`--file`, `--name`, `--out` preservadas, com os mesmos `metavar`.
  Novas: `--columns PATH`, `--recursive`.
- `pdf_keys`: o `WD` hardcoded vira `--source` obrigatório; o `chaves_nfe.csv` hardcoded vira
  `--out` (default stdout); `--append/--no-append` com default **overwrite** (o modo `"a"` atual é
  por que `chaves_nfe.csv` acumulou ~2392 linhas com duplicação pesada) e `--dedupe`.

`uv run python app.py` deixa de funcionar na fase 6.2; `uv run meu-danfe` é o substituto. Durante
as fases 1-5 os arquivos da raiz continuam como shims, então o repositório nunca fica quebrado.

## Servidor HTTP (extra opcional)

Só para consumidores não-Python. `create_app()` em `server/app.py`, FastAPI.

- **Um único cliente compartilhado** criado no `lifespan` da aplicação. Isso é obrigatório: um
  cliente por request recriaria o `KeyPacer` e perderia a garantia de 1 s/chave.
- **Token obrigatório sempre**: `MEU_DANFE_SERVER_TOKEN`, comparado com `secrets.compare_digest`,
  em header próprio — distinto da `Api-Key` do Meu DANFE, que nunca sai do processo. A aplicação
  **se recusa a subir** sem token configurado.
- **Bind em `127.0.0.1`** por padrão; qualquer outro host exige `--allow-remote` explícito (e
  continua exigindo token).
- Endpoints de alto nível apenas:
  - `POST /v1/documents/fetch` — corpo `{keys: [...], parse: bool}`. Faz fila+polling+download e
    responde **NDJSON em streaming** via `iter_fetch`, um resultado por linha conforme completam.
    Evita timeout de proxy em lotes grandes sem precisar de fila de jobs.
  - `POST /v1/documents/parse` — XML no corpo ou upload → linhas parseadas.
  - `POST /v1/pdf/keys` — upload de PDF → chaves.
  - `GET /healthz` — sem auth.
- **Proteção de custo**: `max_keys_per_request` configurável e log do total de polls/custo estimado
  por request (cada chave nova custa R$ 0,03 e o servidor gasta saldo real de quem o sobe).

## Empacotamento

```toml
[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[project]
name = "meu-danfe-downloader"      # nome de distribuição mantido; nome de import é meu_danfe
requires-python = ">=3.12"
dependencies = ["httpx>=0.27", "xmltodict>=0.13"]

[project.optional-dependencies]
excel = ["pandas>=2.2", "openpyxl>=3.1"];  pdf = ["pymupdf>=1.24"]
dotenv = ["python-dotenv>=1.0"];           server = ["fastapi>=0.115", "uvicorn>=0.30"]
cli = ["meu-danfe-downloader[excel,pdf,dotenv]"];  all = ["meu-danfe-downloader[cli,server]"]

[tool.hatch.build.targets.wheel]
packages = ["src/meu_danfe"]

[dependency-groups]
dev = ["pytest>=8", "pytest-asyncio>=0.24", "mypy>=1.11", "ruff>=0.6", "jupyter", "ipython>=9"]
```

- **Dependências de runtime caem de 8 para 2.** `pandas`/`openpyxl` (as mais pesadas, puxam numpy),
  `pymupdf` e `python-dotenv` viram extras; `requests` e `ipython` saem do runtime (`requests` só
  servia à cópia duplicada no notebook, que será removida).
- `columns.json` e `py.typed` entram no wheel automaticamente (hatchling inclui não-`.py` dentro do
  pacote); `columns.json` é lido via `importlib.resources`, com `functools.cache` — funciona dentro
  de um wheel zipado, ao contrário do `Path(__file__).parent` atual.
- Piso `>=3.12`: verificado que os quatro módulos atuais fazem parse sob 3.12; o mais novo que o
  plano introduz é `StrEnum`/`Self` (3.11+). `.python-version` fica em 3.14 para dev local.
- Instalação pelo consumidor: `uv add --editable ../meu-danfe-downloader` (co-desenvolvimento),
  `uv add "meu-danfe-downloader @ file:///..."`, ou `git+ssh://...` **depois** do `git init`.

## Ordenação da implementação

Cada passo é verificável de forma independente. `[MOVE]` = relocação pura, saída deve ser
idêntica; `[COMP]` = mudança de comportamento intencional.

**Fase 0 — tornar o trabalho seguro**
- 0.1 `[COMP]` `git init`; **confirmar que `.gitignore` exclui `.env` antes do primeiro `git add`**
  (o arquivo tem 24 variáveis, 22 herdadas de outro projeto); commit da árvore atual como baseline.
- 0.2 `[COMP]` Adicionar `[build-system]`, `[tool.hatch...]`, `src/meu_danfe/__init__.py` vazio e
  `py.typed`. Scripts da raiz intocados.
- 0.3 Adicionar grupo `dev`, `tests/conftest.py` com o guard autouse anti-rede, e um teste trivial.

**Fase 1 — movimentações puras**
- 1.1 `[MOVE]` `columns.json` → `src/meu_danfe/nfe/columns.json` + `nfe/columns.py`.
- 1.2 `[MOVE]` `_get`/`_serialize`/`_resolve_path`/`_extract_rows`/`_parse_xml` → `nfe/parser.py`,
  públicos e com parâmetro `columns=`. `xml_to_excel.py` da raiz vira shim de 5 linhas.
- 1.3 `[MOVE]` `extract_key` + regex → `pdf.py` como `extract_keys`; `pdf_key_extractor.py` vira
  shim com `WD` parametrizado.

**Fase 2 — config e exceções**
- 2.1 `[MOVE+COMP]` `exceptions.py` com `ERROR_MESSAGES` verbatim e o mapa status→classe.
- 2.2 `[COMP]` `config.py` + `from_env`. **É o passo que desbloqueia o consumidor.**

**Fase 3 — pacing**
- 3.1 `[COMP]` `models.py` + `pacing.py`.

**Fase 4 — cliente async**
- 4.1 `[COMP]` `client.py` com a máquina de estados, `max_polls` e `return_exceptions`.
- 4.2 `[COMP]` `storage.py` com sanitização de nome.
- 4.3 Re-exports em `__init__.py`, `__all__`, `logging.NullHandler`.

**Fase 5 — facade sync**
- 5.1 `[COMP]` `sync_client.py` + `_LoopRunner`.

**Fase 6 — CLIs**
- 6.1 `[COMP]` `cli/` + registro de `[project.scripts]`.
- 6.2 `[COMP]` Remover `app.py`, `xml_to_excel.py`, `pdf_key_extractor.py`, `filter_files.py` da raiz.

**Fase 7 — servidor HTTP**
- 7.1 `[COMP]` `server/` com cliente compartilhado no lifespan, token obrigatório, bind local,
  os quatro endpoints e o limite de chaves por request.

**Fase 8 — notebook, docs, higiene de dados**
- 8.1 `[COMP]` Reescrever `notas-nb.ipynb` para importar a biblioteca; remover `LiveServerSession`,
  o `find_and_add_nfe`/`get_nfe` sync com `except:` pelado e o `extract_key` duplicado. Mover para
  `notebooks/`. Corrigir a célula de mapeamento (ela troca `CNPJ Destinatário` com
  `Razão Social Destinatário`; o `columns.json` está correto).
- 8.2 `[COMP]` Criar `.env.example` só com o que este projeto usa. **Não ler, imprimir, mover nem
  podar o `.env`** — as outras 22 variáveis podem estar em uso por outro projeto; podá-las é um
  passo separado, com autorização explícita.
- 8.3 Reescrever `README.md` e `CLAUDE.md`: biblioteca primeiro, depois CLI, tabela de extras.
  Corrigir o exemplo de `MEU_DANFE_API_URL` — a documentação mostra o host sem `/v2`, embora o
  `.env` real já use `https://api.meudanfe.com.br/v2/`. Corrigir também a afirmação de que o
  notebook usa SharePoint/SQL Server/Graph: ele não usa nada disso.
- 8.4 `[COMP]` Mover `chaves_nfe.csv`, `notas.tsv`, `todo.csv`, `out.csv`, `test_output.xlsx` para
  `data/` gitignored — `chaves_nfe.csv` tem ~2392 chaves de acesso reais e não deve ser commitado
  (depois de `test_output.xlsx` servir de baseline na fase 1.2).

**Fase 9 — piso de Python e smoke test**
- 9.1 `[COMP]` `requires-python = ">=3.12"`, afrouxar o pin de pandas, `uv lock`.
- 9.2 Num diretório descartável (não num projeto real): `uv init`, `uv add --editable <este repo>`,
  rodar os três trechos de uso contra fixtures locais.

## Bugs corrigidos no caminho

Além dos problemas estruturais acima, estes são corrigidos como consequência:

| # | Bug | Onde |
|---|---|---|
| B1 | Loop de polling sem limite: se a API nunca sair de `WAITING`/`SEARCHING`, roda para sempre, um PUT por segundo | `app.py:117-121` |
| B2 | `asyncio.gather` **sem `return_exceptions=True`**: um `ConnectError` numa chave cancela todas as outras em voo, inclusive já pagas | `app.py:173` |
| B3 | Path traversal: o `name` **vindo da API** é concatenado sem sanitização, e `mkdir(parents=True)` agrava. `Path("/out") / "/etc/x.xml"` → `/etc/x.xml` | `app.py:79-83` |
| B4 | Diretório de saída default é o diretório do código (`ROOT_DIR`) → escreveria em `site-packages` após instalado. Passa a ser o cwd | `app.py:90`, `xml_to_excel.py:69` |
| B5 | `.json()` chamado 3× por poll sem guarda: corpo não-JSON levanta `JSONDecodeError`; corpo sem `status` devolve `None`, que não está em `TERMINAL_STATUSES` → loop infinito | `app.py:117,124` |
| B6 | Sem pacing entre o último poll e o download — o aviso do fornecedor é sobre a chave, não o endpoint | `app.py:117→126` |
| B7 | `read_text(encoding="utf-8")` fixo: NFe declarando `ISO-8859-1` (comum em arquivos antigos) corrompe ou levanta. Passar bytes, que `xmltodict` honra via declaração XML | `xml_to_excel.py:57` |
| B8 | `save_keys` abre em `"a"` sem dedupe → cada execução duplica o arquivo | `pdf_key_extractor.py:19` |
| B9 | `filter_files.py` não tem guard `__main__`: todo o IO roda no **import** e levanta se o diretório não existir | `filter_files.py` |
| B10 | api_key em `HEADERS` global de módulo → sai em qualquer repr/log | `app.py:12` |

## Fora de escopo (requer aprovação separada)

- **`columns.json` tem 10 colunas com caminhos duplicados**: `CST/CSOSN`, `Base de Cálculo ICMS`,
  `Alíquota ICMS` e `Valor ICMS` resolvem todas para o mesmo dict `det[i].imposto.ICMS`; outras seis
  resolvem para `det[i].imposto`. É um mapeamento inacabado, não um bug da refatoração — preservar
  byte-a-byte é o que torna a fase 1.2 verificável. Corrigir depois.
- **`_resolve_path` substitui todo literal `0`** do caminho pelo índice do `det`, tornando
  inexpressível o índice 0 de qualquer outra lista. Sugestão futura: aceitar `"*"` como sentinela.
- **Validação mod-11 do dígito verificador** (evitaria pagar R$ 0,03 por erro de digitação): é
  comportamento novo, e uma implementação subtilmente errada rejeita chaves **válidas** — pior que
  perder 3 centavos. Entra como `check_digit=False` por default, validado contra `chaves_nfe.csv`
  antes de virar default.
- **Poda das 22 variáveis não usadas do `.env`.**
- Trocar o escritor de Excel (pandas → openpyxl puro) para largar numpy.

## Verificação

Suite com `pytest` + `pytest-asyncio` (`asyncio_mode = "auto"`), usando `httpx.MockTransport` (sem
dependência extra; o parâmetro `transport=` é um seam que queremos de todo modo). **Nenhum teste
toca a rede nem gasta R$ 0,03**: fixture autouse faz `AsyncHTTPTransport.handle_async_request`
levantar.

- `test_import_without_env.py` — **o teste de regressão mais importante**: com `MEU_DANFE_*` fora do
  ambiente e sem `.env` em disco, `import meu_danfe` funciona e `from_env({})` levanta
  `ConfigurationError`, não `KeyError`.
- `test_pacing.py` — com `FakeClock`: duas aquisições de `slot("K")` ≥1,0 s em tempo falso; chaves
  distintas progridem em paralelo; pico de requisições em voo ≤ `max_concurrency`;
  `min_interval=0.5` levanta; importar `pacing` sem loop em execução não cria primitiva asyncio.
- `test_client_state_machine.py` — `WAITING→SEARCHING→OK→download`; `NOT_FOUND` e `ERROR` nos tipos
  certos; `SEARCHING` travado levanta `PollTimeoutError` após `max_polls`; corpo não-JSON levanta
  `MalformedResponseError`; um `ConnectError` numa chave **não** aborta as demais em `fetch_many`.
- `test_exceptions.py` — itera `ERROR_MESSAGES` e afirma que cada código resolve para uma classe com
  `.message` string-igual ao original (fidelidade das mensagens em português).
- `test_sync_facade.py` — a suite da fase 4 parametrizada nos dois clientes dá resultados idênticos;
  dois `fetch(k)` sequenciais para a mesma chave ficam ≥1 s em tempo falso (prova que o estado do
  pacer sobrevive entre chamadas); `close()` encerra a thread sem `ResourceWarning` nem travar.
- `test_storage.py` — `name` da API valendo `../../etc/passwd` e `/etc/passwd` ficam ambos dentro de
  `out_dir`.
- `test_parser.py` — fixtures `nfe_multi_det.xml` (3 itens → 3 linhas, campos da nota repetidos),
  `nfe_single_det.xml` (fixa `force_list=("det",)`; sem ele um item único é dict e `len()` conta
  chaves), `nfe_sparse.xml` (campos ausentes → células vazias).
- `test_server.py` — `TestClient`: sem token → 401; token errado → 401; `/healthz` sem auth → 200;
  `fetch` acima de `max_keys_per_request` → 413; o streaming NDJSON emite uma linha por chave; o app
  recusa subir sem token; bind não-loopback sem `--allow-remote` é recusado.

Verificação end-to-end por fase, além dos testes:

```bash
uv build && uv run --isolated --with dist/*.whl python -c "import meu_danfe"  # instalável limpo
uv run -p 3.12 pytest && uv run -p 3.14 pytest                                # piso e teto
uv run meu-danfe --help                       # flags --key/--file/--save/--out,-o preservadas
uv run meu-danfe-to-excel --file <xml> --name x && diff <(...) test_output.xlsx  # baseline fase 1.2
git ls-files | grep -c '^\.env$'              # deve ser 0
rg 'ROOT_DIR|dotenv_values|^sem = ' src/      # só deve casar em cli/ e config.py
```

Uma única consulta real contra a API (custo R$ 0,03), com uma chave que você escolher, fecha o
ciclo ao final — mas só depois de toda a suite passar com transporte mockado.

## Arquivos críticos

- `pyproject.toml` — `[build-system]`, extras, `[project.scripts]`, piso de Python
- `app.py` → `src/meu_danfe/{client,sync_client,config,exceptions,models,pacing,storage}.py` + `cli/download.py`
- `xml_to_excel.py` → `src/meu_danfe/nfe/parser.py`, `excel.py`, `cli/to_excel.py`
- `pdf_key_extractor.py` → `src/meu_danfe/pdf.py` + `cli/pdf_keys.py`
- `columns.json` → `src/meu_danfe/nfe/columns.json` (movido, conteúdo preservado)
- `filter_files.py` → removido; vira `keys.existing_keys_in_dir()`
- `notas-nb.ipynb` → `notebooks/`, duplicatas removidas
