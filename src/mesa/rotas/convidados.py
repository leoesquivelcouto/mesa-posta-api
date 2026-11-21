from typing import Annotated

from fastapi import APIRouter, File, Query, Response, UploadFile
from sqlalchemy import func, select

from mesa.deps import Db, Editores, Todos
from mesa.erros import ErroApp
from mesa.esquemas import (
    AtribuirMesa,
    ConvidadoAtualizar,
    ConvidadoEntrada,
    ConvidadoSaida,
    ImportacaoSaida,
    PaginaConvidados,
    Resposta,
)
from mesa.modelos import Convidado
from mesa.servicos import atribuir_mesa, buscar_convidado, fazer_checkin, importar_csv, saida

router = APIRouter(prefix="/eventos/{evento_id}/convidados", tags=["convidados"])

TAMANHO_MAXIMO = 1_000_000  # 1 MB é muito mais do que uma lista de casamento precisa


@router.get("", response_model=PaginaConvidados)
def listar(
    a: Todos,
    db: Db,
    busca: Annotated[str | None, Query(max_length=60, description="Parte do nome")] = None,
    resposta: Resposta | None = None,
    mesa_id: int | None = None,
    sem_mesa: bool = False,
    presente: bool | None = None,
    limite: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginaConvidados:
    filtros = [Convidado.evento_id == a.evento.id]
    if busca:
        termo = busca.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filtros.append(Convidado.nome.ilike(f"%{termo}%"))
    if resposta:
        filtros.append(Convidado.resposta == resposta)
    if mesa_id is not None:
        filtros.append(Convidado.mesa_id == mesa_id)
    if sem_mesa:
        filtros.append(Convidado.mesa_id.is_(None))
    if presente is not None:
        filtros.append(Convidado.checkin_em.is_not(None) if presente else Convidado.checkin_em.is_(None))

    total = db.scalar(select(func.count()).select_from(Convidado).where(*filtros)) or 0
    itens = db.scalars(
        select(Convidado).where(*filtros).order_by(Convidado.nome, Convidado.id).limit(limite).offset(offset)
    )
    return PaginaConvidados(itens=[saida(c) for c in itens], total=total, limite=limite, offset=offset)


@router.post("", status_code=201, response_model=ConvidadoSaida)
def criar(dados: ConvidadoEntrada, a: Editores, db: Db) -> ConvidadoSaida:
    convidado = Convidado(evento_id=a.evento.id, **dados.model_dump())
    db.add(convidado)
    db.commit()
    return saida(convidado)


@router.post("/importar", response_model=ImportacaoSaida)
async def importar(a: Editores, db: Db, arquivo: Annotated[UploadFile, File()]) -> ImportacaoSaida:
    """CSV com cabeçalho. Colunas aceitas: nome (obrigatória), telefone, email, grupo."""
    conteudo = await arquivo.read(TAMANHO_MAXIMO + 1)
    if len(conteudo) > TAMANHO_MAXIMO:
        raise ErroApp(413, "arquivo_grande", "O arquivo passa de 1 MB.")
    importados, ignorados = importar_csv(db, a.evento.id, conteudo)
    return ImportacaoSaida(importados=importados, ignorados=ignorados)


@router.get("/{convidado_id}", response_model=ConvidadoSaida)
def obter(convidado_id: int, a: Todos, db: Db) -> ConvidadoSaida:
    return saida(buscar_convidado(db, a.evento.id, convidado_id))


@router.patch("/{convidado_id}", response_model=ConvidadoSaida)
def atualizar(convidado_id: int, dados: ConvidadoAtualizar, a: Editores, db: Db) -> ConvidadoSaida:
    """Também serve para o cerimonial registrar uma resposta recebida por telefone."""
    convidado = buscar_convidado(db, a.evento.id, convidado_id, travar=True)
    mudancas = dados.model_dump(exclude_unset=True)
    if "nome" in mudancas and mudancas["nome"] is None:
        raise ErroApp(422, "dados_invalidos", "O nome não pode ficar vazio.")
    if "resposta" in mudancas:
        if mudancas["resposta"] is None:
            raise ErroApp(422, "dados_invalidos", "A resposta não pode ficar vazia.")
        if mudancas["resposta"] != convidado.resposta:
            convidado.respondido_em = func.now()
        if mudancas["resposta"] == "recusado":
            convidado.mesa_id = None
    for campo, valor in mudancas.items():
        setattr(convidado, campo, valor)
    db.commit()
    db.refresh(convidado)
    return saida(convidado)


@router.delete("/{convidado_id}", status_code=204)
def excluir(convidado_id: int, a: Editores, db: Db) -> Response:
    db.delete(buscar_convidado(db, a.evento.id, convidado_id))
    db.commit()
    return Response(status_code=204)


@router.put("/{convidado_id}/mesa", response_model=ConvidadoSaida)
def definir_mesa(convidado_id: int, dados: AtribuirMesa, a: Editores, db: Db) -> ConvidadoSaida:
    """Coloca o convidado numa mesa (ou tira, com mesa_id null). 409 se a mesa estiver cheia."""
    return saida(atribuir_mesa(db, a.evento.id, convidado_id, dados.mesa_id))


@router.post("/{convidado_id}/checkin", response_model=ConvidadoSaida)
def checkin_manual(convidado_id: int, a: Todos, db: Db) -> ConvidadoSaida:
    """Check-in pela busca de nome, para quem chegou sem o QR code."""
    return saida(fazer_checkin(db, a.evento.id, convidado_id))
