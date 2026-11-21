from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from mesa.deps import Db, UsuarioAtual
from mesa.erros import ErroApp
from mesa.esquemas import CadastroEntrada, TokenSaida, UsuarioSaida
from mesa.modelos import Usuario
from mesa.seguranca import HASH_FALSO, confere_senha, criar_jwt, hash_senha

router = APIRouter(prefix="/auth", tags=["contas"])


@router.post("/cadastro", status_code=201, response_model=UsuarioSaida)
def cadastrar(dados: CadastroEntrada, db: Db) -> Usuario:
    usuario = Usuario(nome=dados.nome.strip(), email=dados.email.lower(), senha_hash=hash_senha(dados.senha))
    db.add(usuario)
    try:
        db.commit()
    except IntegrityError as e:
        raise ErroApp(409, "email_em_uso", "Já existe uma conta com este e-mail.") from e
    return usuario


@router.post("/login", response_model=TokenSaida)
def login(form: Annotated[OAuth2PasswordRequestForm, Depends()], db: Db) -> TokenSaida:
    """Recebe e-mail (no campo `username`) e senha; devolve um JWT válido por JWT_MINUTOS."""
    usuario = db.scalar(select(Usuario).where(Usuario.email == form.username.strip().lower()))
    senha_ok = confere_senha(form.password, usuario.senha_hash if usuario else HASH_FALSO)
    if usuario is None or not senha_ok:
        raise ErroApp(401, "credenciais_invalidas", "E-mail ou senha incorretos.")
    return TokenSaida(access_token=criar_jwt(usuario.id))


@router.get("/eu", response_model=UsuarioSaida)
def eu(usuario: UsuarioAtual) -> Usuario:
    return usuario
