"""Formato único de erro da API: {"erro": {"codigo", "mensagem", "detalhes"}}."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

CODIGOS_HTTP = {
    401: "nao_autenticado",
    403: "sem_permissao",
    404: "nao_encontrado",
    405: "metodo_nao_permitido",
}


class ErroApp(Exception):
    def __init__(self, status: int, codigo: str, mensagem: str, detalhes: Any = None):
        super().__init__(mensagem)
        self.status = status
        self.codigo = codigo
        self.mensagem = mensagem
        self.detalhes = detalhes


def nao_encontrado(o_que: str) -> ErroApp:
    return ErroApp(404, "nao_encontrado", f"{o_que} não encontrado.")


def _resposta(status: int, codigo: str, mensagem: str, detalhes: Any = None) -> JSONResponse:
    corpo: dict[str, Any] = {"codigo": codigo, "mensagem": mensagem}
    if detalhes is not None:
        corpo["detalhes"] = detalhes
    return JSONResponse({"erro": corpo}, status_code=status)


def registrar(app: FastAPI) -> None:
    @app.exception_handler(ErroApp)
    async def _app(_: Request, e: ErroApp) -> JSONResponse:
        return _resposta(e.status, e.codigo, e.mensagem, e.detalhes)

    @app.exception_handler(RequestValidationError)
    async def _validacao(_: Request, e: RequestValidationError) -> JSONResponse:
        detalhes = [
            {
                "campo": ".".join(str(p) for p in erro["loc"][1:]) or str(erro["loc"][0]),
                "mensagem": erro["msg"],
            }
            for erro in e.errors()
        ]
        return _resposta(422, "dados_invalidos", "Alguns campos estão inválidos.", detalhes)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException) -> JSONResponse:
        return _resposta(e.status_code, CODIGOS_HTTP.get(e.status_code, "erro_http"), str(e.detail))
