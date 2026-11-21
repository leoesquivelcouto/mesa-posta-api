from fastapi import APIRouter, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from mesa.deps import Db, Editores, Todos
from mesa.erros import ErroApp, nao_encontrado
from mesa.esquemas import MesaAtualizar, MesaEntrada, MesaSaida
from mesa.modelos import Convidado, Mesa
from mesa.servicos import alterar_mesa

router = APIRouter(prefix="/eventos/{evento_id}/mesas", tags=["mesas"])

NOME_EM_USO = ErroApp(409, "nome_em_uso", "Já existe uma mesa com este nome neste evento.")


def _com_ocupacao(db: Db, evento_id: int, mesa_id: int | None = None) -> list[MesaSaida]:
    consulta = (
        select(Mesa.id, Mesa.nome, Mesa.capacidade, func.count(Convidado.id))
        .outerjoin(Convidado, Convidado.mesa_id == Mesa.id)
        .where(Mesa.evento_id == evento_id)
        .group_by(Mesa.id)
        .order_by(Mesa.nome)
    )
    if mesa_id is not None:
        consulta = consulta.where(Mesa.id == mesa_id)
    return [MesaSaida(id=i, nome=n, capacidade=c, ocupados=o) for i, n, c, o in db.execute(consulta)]


@router.get("", response_model=list[MesaSaida])
def listar(a: Todos, db: Db) -> list[MesaSaida]:
    return _com_ocupacao(db, a.evento.id)


@router.post("", status_code=201, response_model=MesaSaida)
def criar(dados: MesaEntrada, a: Editores, db: Db) -> MesaSaida:
    mesa = Mesa(evento_id=a.evento.id, nome=dados.nome.strip(), capacidade=dados.capacidade)
    db.add(mesa)
    try:
        db.commit()
    except IntegrityError as e:
        raise NOME_EM_USO from e
    return MesaSaida(id=mesa.id, nome=mesa.nome, capacidade=mesa.capacidade, ocupados=0)


@router.patch("/{mesa_id}", response_model=MesaSaida)
def atualizar(mesa_id: int, dados: MesaAtualizar, a: Editores, db: Db) -> MesaSaida:
    alterar_mesa(db, a.evento.id, mesa_id, dados.nome, dados.capacidade)
    try:
        db.commit()
    except IntegrityError as e:
        raise NOME_EM_USO from e
    return _com_ocupacao(db, a.evento.id, mesa_id)[0]


@router.delete("/{mesa_id}", status_code=204)
def excluir(mesa_id: int, a: Editores, db: Db) -> Response:
    """Os convidados da mesa ficam sem mesa (a chave estrangeira faz isso no banco)."""
    mesa = db.scalar(select(Mesa).where(Mesa.id == mesa_id, Mesa.evento_id == a.evento.id))
    if mesa is None:
        raise nao_encontrado("Mesa")
    db.delete(mesa)
    db.commit()
    return Response(status_code=204)
