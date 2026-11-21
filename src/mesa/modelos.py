"""Tabelas do banco. As regras que não podem falhar ficam como restrições no próprio PostgreSQL.

O esquema real é criado pelas migrações (migrations/versions); estes modelos são o mapeamento usado
pelo código.
"""

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from mesa.db import Base

PAPEIS = ("cerimonial", "noivos", "recepcao")
RESPOSTAS = ("pendente", "confirmado", "recusado")


class Usuario(Base):
    __tablename__ = "usuario"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    senha_hash: Mapped[str] = mapped_column(String(100))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Evento(Base):
    __tablename__ = "evento"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    data: Mapped[date] = mapped_column(Date)
    local: Mapped[str | None] = mapped_column(String(200))
    prazo_rsvp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Membro(Base):
    """Quem trabalha em cada evento e com qual papel."""

    __tablename__ = "membro"
    __table_args__ = (
        CheckConstraint("papel IN ('cerimonial', 'noivos', 'recepcao')", name="membro_papel_valido"),
    )

    evento_id: Mapped[int] = mapped_column(ForeignKey("evento.id", ondelete="CASCADE"), primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id", ondelete="CASCADE"), primary_key=True)
    papel: Mapped[str] = mapped_column(String(20))


class Mesa(Base):
    __tablename__ = "mesa"
    __table_args__ = (
        UniqueConstraint("evento_id", "nome", name="mesa_nome_unico"),
        # Alvo da chave estrangeira composta de convidado: garante que a mesa é do mesmo evento.
        UniqueConstraint("id", "evento_id", name="mesa_id_evento"),
        CheckConstraint("capacidade BETWEEN 1 AND 50", name="mesa_capacidade_valida"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    evento_id: Mapped[int] = mapped_column(ForeignKey("evento.id", ondelete="CASCADE"))
    nome: Mapped[str] = mapped_column(String(60))
    capacidade: Mapped[int]


class Convidado(Base):
    __tablename__ = "convidado"
    __table_args__ = (
        # Na migração: ON DELETE SET NULL (mesa_id), que apaga só a mesa, não o evento (PostgreSQL 15+).
        ForeignKeyConstraint(
            ["mesa_id", "evento_id"], ["mesa.id", "mesa.evento_id"], name="convidado_mesa_mesmo_evento"
        ),
        CheckConstraint(
            "resposta IN ('pendente', 'confirmado', 'recusado')", name="convidado_resposta_valida"
        ),
        CheckConstraint(
            "NOT (resposta = 'recusado' AND mesa_id IS NOT NULL)", name="convidado_recusado_sem_mesa"
        ),
        Index("convidado_evento_nome_idx", "evento_id", "nome"),
        Index("convidado_mesa_idx", "mesa_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    evento_id: Mapped[int] = mapped_column(ForeignKey("evento.id", ondelete="CASCADE"))
    nome: Mapped[str] = mapped_column(String(120))
    telefone: Mapped[str | None] = mapped_column(String(11))
    email: Mapped[str | None] = mapped_column(String(254))
    grupo: Mapped[str | None] = mapped_column(String(80))
    resposta: Mapped[str] = mapped_column(String(10), server_default="pendente")
    respondido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restricao_alimentar: Mapped[str | None] = mapped_column(String(200))
    mesa_id: Mapped[int | None]
    checkin_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Só o hash SHA-256 do token do convite fica no banco; o token aparece uma única vez, no link.
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def tem_convite(self) -> bool:
        return self.token_hash is not None
