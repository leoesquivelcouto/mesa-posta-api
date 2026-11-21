import csv
import io
from typing import Literal

import segno
from fastapi import APIRouter, Response
from sqlalchemy import select

from mesa.deps import Cerimonial, Db, Todos
from mesa.esquemas import CheckinEntrada, CheckinSaida, ConvitePublico, ConviteSaida, RespostaEntrada
from mesa.modelos import Convidado, Evento, Mesa
from mesa.servicos import (
    checkin_por_codigo,
    convidado_pelo_token,
    gerar_convites,
    link_convite,
    prazo_encerrado,
    responder_convite,
    saida,
)

router = APIRouter(tags=["convites e check-in"])


@router.post("/eventos/{evento_id}/convites", response_model=list[ConviteSaida])
def gerar(a: Cerimonial, db: Db, regenerar: bool = False, formato: Literal["json", "csv"] = "json"):
    """Gera os links de confirmação. Guarde a resposta: os links não podem ser consultados de novo.

    Com `formato=csv`, a resposta abre direto no Excel para enviar os links por WhatsApp ou e-mail.
    """
    convites = gerar_convites(db, a.evento.id, regenerar)
    if formato == "json":
        return convites
    saida_csv = io.StringIO()
    escritor = csv.writer(saida_csv, delimiter=";")
    escritor.writerow(["nome", "telefone", "link"])
    escritor.writerows([c.nome, c.telefone or "", c.link] for c in convites)
    return Response(
        "﻿" + saida_csv.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="convites.csv"'},
    )


@router.post("/eventos/{evento_id}/checkin", response_model=CheckinSaida)
def checkin(dados: CheckinEntrada, a: Todos, db: Db) -> CheckinSaida:
    """Lê o QR code do convite na entrada. 409 se a pessoa já entrou."""
    convidado = checkin_por_codigo(db, a.evento.id, dados.codigo)
    mesa = db.scalar(select(Mesa.nome).where(Mesa.id == convidado.mesa_id)) if convidado.mesa_id else None
    aviso = None
    if convidado.resposta != "confirmado":
        aviso = "Convidado sem confirmação de presença: avise o cerimonial."
    elif mesa is None:
        aviso = "Convidado confirmado, mas ainda sem mesa."
    return CheckinSaida(convidado=saida(convidado), mesa=mesa, aviso=aviso)


# --- páginas públicas do convidado (sem login; o token do link é a credencial) -------------------


def _publico(convidado: Convidado, evento: Evento) -> ConvitePublico:
    return ConvitePublico(
        evento=evento.nome,
        data=evento.data,
        local=evento.local,
        prazo_rsvp=evento.prazo_rsvp,
        prazo_encerrado=prazo_encerrado(evento),
        convidado=convidado.nome,
        resposta=convidado.resposta,
        restricao_alimentar=convidado.restricao_alimentar,
    )


@router.get("/convite/{token}", response_model=ConvitePublico)
def ver_convite(token: str, db: Db) -> ConvitePublico:
    return _publico(*convidado_pelo_token(db, token))


@router.post("/convite/{token}", response_model=ConvitePublico)
def responder(token: str, dados: RespostaEntrada, db: Db) -> ConvitePublico:
    return _publico(*responder_convite(db, token, dados.resposta, dados.restricao_alimentar))


@router.get("/convite/{token}/qr.svg", response_class=Response)
def qr_code(token: str, db: Db) -> Response:
    """QR code com o link do convite, para apresentar na entrada."""
    convidado_pelo_token(db, token)  # 404 se o token não existir
    buffer = io.BytesIO()
    segno.make(link_convite(token), error="m").save(buffer, kind="svg", scale=8, border=2)
    return Response(
        buffer.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "private, max-age=3600"}
    )
