"""Regras de negócio. As rotas só traduzem HTTP; o que importa acontece aqui."""

import csv
import io
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from mesa.config import config
from mesa.erros import ErroApp, nao_encontrado
from mesa.esquemas import ConvidadoEntrada, ConvidadoSaida, ConviteSaida, Resumo
from mesa.modelos import Convidado, Evento, Mesa
from mesa.seguranca import hash_token, novo_token_convite

LIMITE_IMPORTACAO = 2000


def agora() -> datetime:
    return datetime.now(UTC)


def saida(c: Convidado) -> ConvidadoSaida:
    return ConvidadoSaida.model_validate(c)


def buscar_convidado(db: Session, evento_id: int, convidado_id: int, *, travar: bool = False) -> Convidado:
    consulta = select(Convidado).where(Convidado.id == convidado_id, Convidado.evento_id == evento_id)
    if travar:
        consulta = consulta.with_for_update()
    convidado = db.scalar(consulta)
    if convidado is None:
        raise nao_encontrado("Convidado")
    return convidado


def _ocupados(db: Session, mesa_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Convidado).where(Convidado.mesa_id == mesa_id)) or 0


# --- mesas --------------------------------------------------------------------------------------


def atribuir_mesa(db: Session, evento_id: int, convidado_id: int, mesa_id: int | None) -> Convidado:
    """Coloca o convidado numa mesa sem nunca passar da capacidade.

    Dois pedidos simultâneos para o último lugar: o `FOR UPDATE` na linha da mesa faz o segundo esperar o
    primeiro terminar; quando ele conta os ocupados, já vê o lugar tomado e recebe 409. Os bloqueios são
    sempre na mesma ordem (convidado, depois mesa), o que evita deadlock.
    """
    convidado = buscar_convidado(db, evento_id, convidado_id, travar=True)
    if mesa_id is None:
        convidado.mesa_id = None
        db.commit()
        return convidado

    if convidado.resposta == "recusado":
        raise ErroApp(409, "convidado_recusou", "Este convidado recusou o convite e não pode ocupar lugar.")

    mesa = db.scalar(select(Mesa).where(Mesa.id == mesa_id, Mesa.evento_id == evento_id).with_for_update())
    if mesa is None:
        raise nao_encontrado("Mesa")
    if convidado.mesa_id == mesa.id:
        db.commit()
        return convidado

    ocupados = _ocupados(db, mesa.id)
    if ocupados >= mesa.capacidade:
        raise ErroApp(
            409,
            "mesa_lotada",
            f"A mesa {mesa.nome} já está com {ocupados} de {mesa.capacidade} lugares ocupados.",
        )
    convidado.mesa_id = mesa.id
    db.commit()
    return convidado


def alterar_mesa(db: Session, evento_id: int, mesa_id: int, nome: str | None, capacidade: int | None) -> Mesa:
    mesa = db.scalar(select(Mesa).where(Mesa.id == mesa_id, Mesa.evento_id == evento_id).with_for_update())
    if mesa is None:
        raise nao_encontrado("Mesa")
    if capacidade is not None:
        ocupados = _ocupados(db, mesa.id)
        if capacidade < ocupados:
            raise ErroApp(
                409,
                "capacidade_menor_que_ocupacao",
                f"A mesa tem {ocupados} convidados; tire alguns antes de reduzir para {capacidade} lugares.",
            )
        mesa.capacidade = capacidade
    if nome is not None:
        mesa.nome = nome
    return mesa


# --- convites (RSVP) ----------------------------------------------------------------------------


def link_convite(token: str) -> str:
    return f"{config().url_publica}/c/{token}"


def gerar_convites(db: Session, evento_id: int, regenerar: bool) -> list[ConviteSaida]:
    """Cria o link de cada convidado. O token só existe nesta resposta; o banco guarda o hash.

    Sem `regenerar`, só quem ainda não tem convite recebe um. Com `regenerar`, todos os links antigos
    deixam de funcionar (útil se uma lista vazou).
    """
    consulta = select(Convidado).where(Convidado.evento_id == evento_id).order_by(Convidado.nome)
    if not regenerar:
        consulta = consulta.where(Convidado.token_hash.is_(None))
    convites = []
    for convidado in db.scalars(consulta):
        token, convidado.token_hash = novo_token_convite()
        convites.append(
            ConviteSaida(
                convidado_id=convidado.id,
                nome=convidado.nome,
                telefone=convidado.telefone,
                link=link_convite(token),
            )
        )
    db.commit()
    return convites


def convidado_pelo_token(db: Session, token: str, *, travar: bool = False) -> tuple[Convidado, Evento]:
    consulta = select(Convidado).where(Convidado.token_hash == hash_token(token))
    if travar:
        consulta = consulta.with_for_update()
    convidado = db.scalar(consulta)
    if convidado is None:
        raise ErroApp(404, "convite_invalido", "Convite não encontrado. Confira o link recebido.")
    evento = db.get(Evento, convidado.evento_id)
    assert evento is not None
    return convidado, evento


def prazo_encerrado(evento: Evento) -> bool:
    return evento.prazo_rsvp is not None and agora() > evento.prazo_rsvp


def responder_convite(
    db: Session, token: str, resposta: str, restricao: str | None
) -> tuple[Convidado, Evento]:
    convidado, evento = convidado_pelo_token(db, token, travar=True)
    if prazo_encerrado(evento):
        raise ErroApp(
            410, "prazo_encerrado", "O prazo para confirmar presença terminou. Fale com o cerimonial."
        )
    convidado.resposta = resposta
    convidado.respondido_em = agora()
    convidado.restricao_alimentar = restricao
    if resposta == "recusado":
        convidado.mesa_id = None  # libera o lugar
    db.commit()
    return convidado, evento


# --- check-in -----------------------------------------------------------------------------------


def extrair_token(codigo: str) -> str:
    """O QR code traz o link inteiro do convite; o token é o último trecho."""
    return codigo.strip().rstrip("/").rsplit("/", 1)[-1]


def fazer_checkin(db: Session, evento_id: int, convidado_id: int) -> Convidado:
    """Marca a entrada uma única vez, mesmo com dois recepcionistas lendo o mesmo QR ao mesmo tempo.

    O UPDATE só altera a linha se `checkin_em` ainda for nulo; o PostgreSQL garante que apenas um
    dos dois pedidos encontra a linha nessa condição.
    """
    marcado = db.scalar(
        update(Convidado)
        .where(Convidado.id == convidado_id, Convidado.evento_id == evento_id, Convidado.checkin_em.is_(None))
        .values(checkin_em=func.now())
        .returning(Convidado.id)
    )
    db.commit()
    convidado = buscar_convidado(db, evento_id, convidado_id)
    db.refresh(convidado)
    if marcado is None:
        assert convidado.checkin_em is not None
        raise ErroApp(
            409,
            "checkin_repetido",
            f"{convidado.nome} já fez check-in.",
            {"checkin_em": convidado.checkin_em.isoformat()},
        )
    return convidado


def checkin_por_codigo(db: Session, evento_id: int, codigo: str) -> Convidado:
    convidado_id = db.scalar(
        select(Convidado.id).where(
            Convidado.token_hash == hash_token(extrair_token(codigo)), Convidado.evento_id == evento_id
        )
    )
    if convidado_id is None:
        raise ErroApp(404, "convite_invalido", "QR code não reconhecido para este evento.")
    return fazer_checkin(db, evento_id, convidado_id)


# --- importação de planilha ---------------------------------------------------------------------

_COLUNAS = {
    "nome": "nome",
    "telefone": "telefone",
    "celular": "telefone",
    "whatsapp": "telefone",
    "email": "email",
    "e-mail": "email",
    "grupo": "grupo",
    "familia": "grupo",
    "família": "grupo",
}


def _chave(nome: str, telefone: str | None) -> str:
    return f"{nome.casefold()}|{telefone or ''}"


def importar_csv(db: Session, evento_id: int, conteudo: bytes) -> tuple[int, list[str]]:
    """Importa convidados de um CSV exportado do Excel ou do Google Planilhas.

    Tudo ou nada: se alguma linha tiver erro, nada é gravado e a resposta lista cada linha a corrigir.
    Quem já existe no evento (mesmo nome e telefone) ou se repete no arquivo é ignorado e informado.
    """
    try:
        texto = conteudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = conteudo.decode("cp1252")  # Excel no Windows salva CSV assim
    try:
        dialeto = csv.Sniffer().sniff(texto[:2048], delimiters=";,\t")
    except csv.Error:
        dialeto = csv.excel
    leitor = csv.DictReader(io.StringIO(texto), dialect=dialeto)

    cabecalho = {c: _COLUNAS.get(c.strip().casefold()) for c in (leitor.fieldnames or [])}
    if "nome" not in cabecalho.values():
        raise ErroApp(
            422,
            "planilha_invalida",
            "A planilha precisa de uma coluna 'nome'.",
            {"colunas_encontradas": list(cabecalho)},
        )

    existentes = {
        _chave(n, t)
        for n, t in db.execute(
            select(Convidado.nome, Convidado.telefone).where(Convidado.evento_id == evento_id)
        )
    }
    novos: list[Convidado] = []
    ignorados: list[str] = []
    erros: list[dict] = []
    for linha in leitor:
        numero = leitor.line_num  # linha física no arquivo, como o usuário vê no Excel
        dados = {cabecalho[k]: (v or "").strip() or None for k, v in linha.items() if k and cabecalho.get(k)}
        if not any(dados.values()):
            continue
        if len(novos) + len(ignorados) >= LIMITE_IMPORTACAO:
            raise ErroApp(413, "planilha_grande", f"Envie no máximo {LIMITE_IMPORTACAO} convidados por vez.")
        try:
            entrada = ConvidadoEntrada(**dados)
        except ValidationError as e:
            erros.append(
                {
                    "linha": numero,
                    "erros": [f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()],
                }
            )
            continue
        chave = _chave(entrada.nome, entrada.telefone)
        if chave in existentes:
            ignorados.append(f"linha {numero}: {entrada.nome}")
            continue
        existentes.add(chave)
        novos.append(Convidado(evento_id=evento_id, **entrada.model_dump()))

    if erros:
        raise ErroApp(
            422,
            "planilha_com_erros",
            "Corrija as linhas indicadas e envie de novo. Nada foi importado.",
            erros,
        )
    db.add_all(novos)
    db.commit()
    return len(novos), ignorados


# --- painel -------------------------------------------------------------------------------------


def resumo(db: Session, evento_id: int) -> Resumo:
    c = Convidado
    linha = db.execute(
        select(
            func.count(),
            func.count().filter(c.resposta == "confirmado"),
            func.count().filter(c.resposta == "recusado"),
            func.count().filter(c.resposta == "pendente"),
            func.count(c.checkin_em),
            func.count(c.mesa_id),
            func.count().filter(c.resposta == "confirmado", c.mesa_id.is_(None)),
        ).where(c.evento_id == evento_id)
    ).one()
    lugares = db.scalar(
        select(func.coalesce(func.sum(Mesa.capacidade), 0)).where(Mesa.evento_id == evento_id)
    )
    return Resumo(
        convidados=linha[0],
        confirmados=linha[1],
        recusados=linha[2],
        pendentes=linha[3],
        presentes=linha[4],
        sentados=linha[5],
        confirmados_sem_mesa=linha[6],
        lugares=lugares or 0,
    )
