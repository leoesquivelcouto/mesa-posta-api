from fastapi import APIRouter, Response
from sqlalchemy import func, select

from mesa.deps import Cerimonial, Db, Todos, UsuarioAtual
from mesa.erros import ErroApp, nao_encontrado
from mesa.esquemas import EventoAtualizar, EventoEntrada, EventoSaida, MembroEntrada, MembroSaida, Resumo
from mesa.modelos import Evento, Membro, Usuario
from mesa.servicos import resumo

router = APIRouter(prefix="/eventos", tags=["eventos"])


def _saida(evento: Evento, papel: str) -> EventoSaida:
    return EventoSaida(
        id=evento.id,
        nome=evento.nome,
        data=evento.data,
        local=evento.local,
        prazo_rsvp=evento.prazo_rsvp,
        papel=papel,
    )


@router.post("", status_code=201, response_model=EventoSaida)
def criar(dados: EventoEntrada, usuario: UsuarioAtual, db: Db) -> EventoSaida:
    """Quem cria o evento entra nele como cerimonial."""
    evento = Evento(**dados.model_dump())
    db.add(evento)
    db.flush()
    db.add(Membro(evento_id=evento.id, usuario_id=usuario.id, papel="cerimonial"))
    db.commit()
    return _saida(evento, "cerimonial")


@router.get("", response_model=list[EventoSaida])
def listar(usuario: UsuarioAtual, db: Db) -> list[EventoSaida]:
    linhas = db.execute(
        select(Evento, Membro.papel)
        .join(Membro, Membro.evento_id == Evento.id)
        .where(Membro.usuario_id == usuario.id)
        .order_by(Evento.data, Evento.id)
    )
    return [_saida(evento, papel) for evento, papel in linhas]


@router.get("/{evento_id}", response_model=EventoSaida)
def obter(a: Todos) -> EventoSaida:
    return _saida(a.evento, a.papel)


@router.patch("/{evento_id}", response_model=EventoSaida)
def atualizar(dados: EventoAtualizar, a: Cerimonial, db: Db) -> EventoSaida:
    for campo, valor in dados.model_dump(exclude_unset=True).items():
        if campo in ("nome", "data") and valor is None:
            raise ErroApp(422, "dados_invalidos", f"O campo {campo} não pode ficar vazio.")
        setattr(a.evento, campo, valor)
    db.commit()
    return _saida(a.evento, a.papel)


@router.delete("/{evento_id}", status_code=204)
def excluir(a: Cerimonial, db: Db) -> Response:
    db.delete(a.evento)
    db.commit()
    return Response(status_code=204)


@router.get("/{evento_id}/resumo", response_model=Resumo)
def painel(a: Todos, db: Db) -> Resumo:
    return resumo(db, a.evento.id)


# --- equipe do evento ---------------------------------------------------------------------------


def _membros(db: Db, evento_id: int) -> list[MembroSaida]:
    linhas = db.execute(
        select(Usuario.id, Usuario.nome, Usuario.email, Membro.papel)
        .join(Membro, Membro.usuario_id == Usuario.id)
        .where(Membro.evento_id == evento_id)
        .order_by(Usuario.nome)
    )
    return [MembroSaida(usuario_id=i, nome=n, email=e, papel=p) for i, n, e, p in linhas]


@router.get("/{evento_id}/membros", response_model=list[MembroSaida])
def listar_membros(a: Cerimonial, db: Db) -> list[MembroSaida]:
    return _membros(db, a.evento.id)


@router.put("/{evento_id}/membros", response_model=list[MembroSaida])
def definir_membro(dados: MembroEntrada, a: Cerimonial, db: Db) -> list[MembroSaida]:
    """Adiciona alguém à equipe pelo e-mail da conta, ou troca o papel de quem já está."""
    usuario = db.scalar(select(Usuario).where(Usuario.email == dados.email.lower()))
    if usuario is None:
        raise ErroApp(
            404, "usuario_nao_encontrado", "Não há conta com este e-mail. Peça para a pessoa se cadastrar."
        )
    membro = db.get(Membro, (a.evento.id, usuario.id))
    if membro is None:
        db.add(Membro(evento_id=a.evento.id, usuario_id=usuario.id, papel=dados.papel))
    else:
        if membro.papel == "cerimonial" and dados.papel != "cerimonial":
            _garantir_outro_cerimonial(db, a.evento.id)
        membro.papel = dados.papel
    db.commit()
    return _membros(db, a.evento.id)


@router.delete("/{evento_id}/membros/{usuario_id}", status_code=204)
def remover_membro(usuario_id: int, a: Cerimonial, db: Db) -> Response:
    membro = db.get(Membro, (a.evento.id, usuario_id))
    if membro is None:
        raise nao_encontrado("Membro")
    if membro.papel == "cerimonial":
        _garantir_outro_cerimonial(db, a.evento.id)
    db.delete(membro)
    db.commit()
    return Response(status_code=204)


def _garantir_outro_cerimonial(db: Db, evento_id: int) -> None:
    total = db.scalar(
        select(func.count())
        .select_from(Membro)
        .where(Membro.evento_id == evento_id, Membro.papel == "cerimonial")
    )
    if (total or 0) <= 1:
        raise ErroApp(409, "ultimo_cerimonial", "O evento precisa de ao menos um cerimonial.")
