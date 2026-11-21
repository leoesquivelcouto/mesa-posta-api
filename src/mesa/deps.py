"""Dependências das rotas: sessão do banco, usuário logado e papel no evento."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from mesa.db import sessao
from mesa.erros import ErroApp, nao_encontrado
from mesa.modelos import Evento, Membro, Usuario
from mesa.seguranca import ler_jwt

Db = Annotated[Session, Depends(sessao)]

_oauth2 = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)

TODOS = ("cerimonial", "noivos", "recepcao")
EDITORES = ("cerimonial", "noivos")
CERIMONIAL = ("cerimonial",)


def usuario_atual(db: Db, token: Annotated[str | None, Depends(_oauth2)]) -> Usuario:
    usuario_id = ler_jwt(token) if token else None
    usuario = db.get(Usuario, usuario_id) if usuario_id else None
    if usuario is None:
        raise ErroApp(401, "nao_autenticado", "Faça login para continuar.")
    return usuario


UsuarioAtual = Annotated[Usuario, Depends(usuario_atual)]


@dataclass
class Acesso:
    evento: Evento
    papel: str
    usuario: Usuario


def acesso(*papeis: str) -> Callable[..., Acesso]:
    """Exige que o usuário seja membro do evento com um dos papéis indicados."""

    def dependencia(evento_id: int, usuario: UsuarioAtual, db: Db) -> Acesso:
        membro = db.get(Membro, (evento_id, usuario.id))
        if membro is None:
            # 404 em vez de 403: quem não participa do evento não descobre que ele existe.
            raise nao_encontrado("Evento")
        if membro.papel not in papeis:
            raise ErroApp(403, "sem_permissao", "Seu papel neste evento não permite esta ação.")
        evento = db.get(Evento, evento_id)
        assert evento is not None
        return Acesso(evento=evento, papel=membro.papel, usuario=usuario)

    return dependencia


Todos = Annotated[Acesso, Depends(acesso(*TODOS))]
Editores = Annotated[Acesso, Depends(acesso(*EDITORES))]
Cerimonial = Annotated[Acesso, Depends(acesso(*CERIMONIAL))]
