"""Entrada e saída da API (validação com Pydantic)."""

import re
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
)

Papel = Literal["cerimonial", "noivos", "recepcao"]
Resposta = Literal["pendente", "confirmado", "recusado"]


def normalizar_telefone(valor: str | None) -> str | None:
    """Guarda só os dígitos, com DDD: 10 (fixo) ou 11 (celular). Aceita +55 e máscaras."""
    if valor is None:
        return None
    digitos = re.sub(r"\D", "", valor)
    if not digitos:
        return None
    if len(digitos) in (12, 13) and digitos.startswith("55"):
        digitos = digitos[2:]
    if len(digitos) not in (10, 11):
        raise ValueError("telefone deve ter DDD e 8 ou 9 dígitos")
    return digitos


def _limpar(valor: object) -> object:
    """Remove espaços repetidos e nas pontas; texto vazio vira None. Outros tipos seguem para a validação."""
    if not isinstance(valor, str):
        return valor
    valor = " ".join(valor.split())
    return valor or None


Telefone = Annotated[str | None, AfterValidator(normalizar_telefone)]
Nome = Annotated[str, BeforeValidator(_limpar), Field(min_length=2, max_length=120)]
# O limite de tamanho fica no str de dentro: aplicado ao "str | None", ele quebraria com None (erro 500).
Grupo = Annotated[Annotated[str, Field(max_length=80)] | None, BeforeValidator(_limpar)]
Restricao = Annotated[Annotated[str, Field(max_length=200)] | None, BeforeValidator(_limpar)]


class Saida(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- contas -------------------------------------------------------------------------------------


class CadastroEntrada(BaseModel):
    nome: str = Field(min_length=2, max_length=120)
    email: EmailStr
    senha: str = Field(min_length=8, max_length=72)

    @field_validator("senha")
    @classmethod
    def _senha_cabe_no_bcrypt(cls, v: str) -> str:
        if len(v.encode()) > 72:
            raise ValueError("senha longa demais (máximo de 72 bytes)")
        return v


class UsuarioSaida(Saida):
    id: int
    nome: str
    email: str


class TokenSaida(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --- eventos e equipe ---------------------------------------------------------------------------


class EventoEntrada(BaseModel):
    nome: str = Field(min_length=2, max_length=120)
    data: date
    local: str | None = Field(default=None, max_length=200)
    prazo_rsvp: AwareDatetime | None = None


class EventoAtualizar(BaseModel):
    nome: str | None = Field(default=None, min_length=2, max_length=120)
    data: date | None = None
    local: str | None = Field(default=None, max_length=200)
    prazo_rsvp: AwareDatetime | None = None


class EventoSaida(Saida):
    id: int
    nome: str
    data: date
    local: str | None
    prazo_rsvp: datetime | None
    papel: Papel


class MembroEntrada(BaseModel):
    email: EmailStr
    papel: Papel


class MembroSaida(BaseModel):
    usuario_id: int
    nome: str
    email: str
    papel: Papel


class Resumo(BaseModel):
    convidados: int
    confirmados: int
    recusados: int
    pendentes: int
    presentes: int
    lugares: int
    sentados: int
    confirmados_sem_mesa: int


# --- mesas --------------------------------------------------------------------------------------


class MesaEntrada(BaseModel):
    nome: str = Field(min_length=1, max_length=60)
    capacidade: int = Field(ge=1, le=50)


class MesaAtualizar(BaseModel):
    nome: str | None = Field(default=None, min_length=1, max_length=60)
    capacidade: int | None = Field(default=None, ge=1, le=50)


class MesaSaida(Saida):
    id: int
    nome: str
    capacidade: int
    ocupados: int


class AtribuirMesa(BaseModel):
    mesa_id: int | None


# --- convidados ---------------------------------------------------------------------------------


class ConvidadoEntrada(BaseModel):
    nome: Nome
    telefone: Telefone = None
    email: EmailStr | None = None
    grupo: Grupo = None


class ConvidadoAtualizar(BaseModel):
    """Só os campos enviados são alterados; enviar null num campo opcional apaga o valor."""

    nome: Nome | None = None
    telefone: Telefone = None
    email: EmailStr | None = None
    grupo: Grupo = None
    resposta: Resposta | None = None
    restricao_alimentar: Restricao = None


class ConvidadoSaida(Saida):
    id: int
    nome: str
    telefone: str | None
    email: str | None
    grupo: str | None
    resposta: Resposta
    respondido_em: datetime | None
    restricao_alimentar: str | None
    mesa_id: int | None
    checkin_em: datetime | None
    tem_convite: bool


class PaginaConvidados(BaseModel):
    itens: list[ConvidadoSaida]
    total: int
    limite: int
    offset: int


class ImportacaoSaida(BaseModel):
    importados: int
    ignorados: list[str] = Field(description="Linhas que já existiam no evento ou se repetiam no arquivo.")


# --- convites e check-in ------------------------------------------------------------------------


class ConviteSaida(BaseModel):
    convidado_id: int
    nome: str
    telefone: str | None
    link: str


class ConvitePublico(BaseModel):
    evento: str
    data: date
    local: str | None
    prazo_rsvp: datetime | None
    prazo_encerrado: bool
    convidado: str
    resposta: Resposta
    restricao_alimentar: str | None


class RespostaEntrada(BaseModel):
    resposta: Literal["confirmado", "recusado"]
    restricao_alimentar: Restricao = None


class CheckinEntrada(BaseModel):
    codigo: str = Field(
        min_length=10, max_length=400, description="Link do convite lido do QR code, ou o token."
    )


class CheckinSaida(BaseModel):
    convidado: ConvidadoSaida
    mesa: str | None
    aviso: str | None
