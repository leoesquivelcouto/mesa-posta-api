"""Esquema inicial: usuários, eventos, equipe, mesas e convidados.

Revision ID: 0001
Revises:
Create Date: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

agora = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "usuario",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nome", sa.String(120), nullable=False),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("senha_hash", sa.String(100), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False, server_default=agora),
    )
    op.create_table(
        "evento",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nome", sa.String(120), nullable=False),
        sa.Column("data", sa.Date, nullable=False),
        sa.Column("local", sa.String(200)),
        sa.Column("prazo_rsvp", sa.DateTime(timezone=True)),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False, server_default=agora),
    )
    op.create_table(
        "membro",
        sa.Column("evento_id", sa.Integer, sa.ForeignKey("evento.id", ondelete="CASCADE"), primary_key=True),
        sa.Column(
            "usuario_id", sa.Integer, sa.ForeignKey("usuario.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("papel", sa.String(20), nullable=False),
        sa.CheckConstraint("papel IN ('cerimonial', 'noivos', 'recepcao')", name="membro_papel_valido"),
    )
    op.create_index("membro_usuario_idx", "membro", ["usuario_id"])
    op.create_table(
        "mesa",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("evento_id", sa.Integer, sa.ForeignKey("evento.id", ondelete="CASCADE"), nullable=False),
        sa.Column("nome", sa.String(60), nullable=False),
        sa.Column("capacidade", sa.Integer, nullable=False),
        sa.UniqueConstraint("evento_id", "nome", name="mesa_nome_unico"),
        sa.UniqueConstraint("id", "evento_id", name="mesa_id_evento"),
        sa.CheckConstraint("capacidade BETWEEN 1 AND 50", name="mesa_capacidade_valida"),
    )
    op.create_table(
        "convidado",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("evento_id", sa.Integer, sa.ForeignKey("evento.id", ondelete="CASCADE"), nullable=False),
        sa.Column("nome", sa.String(120), nullable=False),
        sa.Column("telefone", sa.String(11)),
        sa.Column("email", sa.String(254)),
        sa.Column("grupo", sa.String(80)),
        sa.Column("resposta", sa.String(10), nullable=False, server_default="pendente"),
        sa.Column("respondido_em", sa.DateTime(timezone=True)),
        sa.Column("restricao_alimentar", sa.String(200)),
        sa.Column("mesa_id", sa.Integer),
        sa.Column("checkin_em", sa.DateTime(timezone=True)),
        sa.Column("token_hash", sa.String(64), unique=True),
        sa.Column("criado_em", sa.DateTime(timezone=True), nullable=False, server_default=agora),
        sa.CheckConstraint(
            "resposta IN ('pendente', 'confirmado', 'recusado')", name="convidado_resposta_valida"
        ),
        sa.CheckConstraint(
            "NOT (resposta = 'recusado' AND mesa_id IS NOT NULL)", name="convidado_recusado_sem_mesa"
        ),
    )
    # Chave composta: a mesa precisa ser do mesmo evento do convidado. Ao apagar a mesa, só mesa_id vira
    # NULL (a lista de colunas no SET NULL existe a partir do PostgreSQL 15; o SQLAlchemy não gera isso).
    op.execute(
        """
        ALTER TABLE convidado ADD CONSTRAINT convidado_mesa_mesmo_evento
            FOREIGN KEY (mesa_id, evento_id) REFERENCES mesa (id, evento_id) ON DELETE SET NULL (mesa_id)
        """
    )
    op.create_index("convidado_evento_nome_idx", "convidado", ["evento_id", "nome"])
    op.create_index("convidado_mesa_idx", "convidado", ["mesa_id"])


def downgrade() -> None:
    op.drop_table("convidado")
    op.drop_table("mesa")
    op.drop_table("membro")
    op.drop_table("evento")
    op.drop_table("usuario")
