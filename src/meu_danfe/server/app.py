"""Optional local HTTP server over the meu_danfe library, for non-Python
consumers. ONE MeuDanfeAsyncClient lives for the app's whole lifetime —
never one per request, which would reset the KeyPacer and lose pacing."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from meu_danfe.client import MeuDanfeAsyncClient
from meu_danfe.config import MeuDanfeConfig
from meu_danfe.nfe.parser import extract_rows, parse_xml
from meu_danfe.pdf import extract_keys
from meu_danfe.server.auth import require_token
from meu_danfe.server.schemas import DocumentOut, FetchRequest, FetchResultOut, KeysOut, ParseRequest, RowsOut
from meu_danfe.server.settings import ServerSettings

logger = logging.getLogger("meu_danfe.server")


def create_app(*, config: MeuDanfeConfig, settings: ServerSettings, transport=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with MeuDanfeAsyncClient(config=config, transport=transport) as client:
            app.state.client = client
            yield

    app = FastAPI(title="meu-danfe server", lifespan=lifespan)
    token_dep = require_token(settings)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/documents/fetch", dependencies=[Depends(token_dep)])
    async def fetch_documents(body: FetchRequest) -> StreamingResponse:
        if len(body.keys) > settings.max_keys_per_request:
            raise HTTPException(
                status_code=413, detail=f"Máximo de {settings.max_keys_per_request} chaves por requisição."
            )
        client: MeuDanfeAsyncClient = app.state.client

        async def _stream() -> AsyncIterator[bytes]:
            total_polls = 0
            async for result in client.iter_fetch(body.keys):
                total_polls += result.polls
                out = FetchResultOut(
                    key=result.key,
                    status=str(result.status) if result.status else None,
                    ok=result.ok,
                    error=str(result.error) if result.error else None,
                    document=(
                        DocumentOut(
                            key=result.document.key,
                            name=result.document.name,
                            doc_type=result.document.doc_type,
                            content_format=result.document.content_format,
                            data=result.document.data,
                        )
                        if result.document
                        else None
                    ),
                )
                yield (out.model_dump_json() + "\n").encode("utf-8")
            logger.info(
                "fetch batch complete: %d keys, %d polls (~R$ %.2f)",
                len(body.keys), total_polls, total_polls * 0.03,
            )

        return StreamingResponse(_stream(), media_type="application/x-ndjson")

    @app.post("/v1/documents/parse", dependencies=[Depends(token_dep)], response_model=RowsOut)
    async def parse_document(body: ParseRequest) -> RowsOut:
        return RowsOut(rows=extract_rows(parse_xml(body.xml)))

    @app.post("/v1/pdf/keys", dependencies=[Depends(token_dep)], response_model=KeysOut)
    async def pdf_keys(file: UploadFile) -> KeysOut:
        content = await file.read()
        return KeysOut(keys=extract_keys(content))

    return app
