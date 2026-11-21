"""Aplicação FastAPI. Rodar com: uvicorn mesa.app:app --no-access-log"""

import logging
import re
import time

from fastapi import FastAPI, Request, Response
from sqlalchemy import text

from mesa import __version__, erros
from mesa.deps import Db
from mesa.rotas import auth, convidados, convites, eventos, mesas

logger = logging.getLogger("mesa")

# Nunca registrar o token do convite: ele é a credencial do convidado.
_TOKEN_NA_URL = re.compile(r"(/convite/|/c/)[^/]+")


def criar_app() -> FastAPI:
    app = FastAPI(
        title="Mesa Posta",
        version=__version__,
        description="Convidados, confirmação de presença, mesas e check-in para cerimonial de casamentos.",
    )
    erros.registrar(app)

    @app.middleware("http")
    async def registrar_requisicao(request: Request, call_next) -> Response:
        inicio = time.perf_counter()
        resposta = await call_next(request)
        caminho = _TOKEN_NA_URL.sub(r"\1***", request.url.path)
        duracao = (time.perf_counter() - inicio) * 1000
        logger.info("%s %s %s %.0fms", request.method, caminho, resposta.status_code, duracao)
        return resposta

    for modulo in (auth, eventos, mesas, convidados, convites):
        app.include_router(modulo.router)

    @app.get("/saude", tags=["infra"])
    def saude(db: Db) -> dict[str, str]:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "versao": __version__}

    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
app = criar_app()
