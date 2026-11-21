"""Conexão com o PostgreSQL. O engine é criado na primeira utilização, não na importação."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from mesa.config import config


class Base(DeclarativeBase):
    pass


@lru_cache
def engine() -> Engine:
    return create_engine(config().database_url, pool_pre_ping=True)


@lru_cache
def fabrica() -> sessionmaker[Session]:
    return sessionmaker(bind=engine(), expire_on_commit=False)


def sessao() -> Iterator[Session]:
    """Uma sessão por requisição. Ao sair sem commit, o que não foi confirmado é desfeito."""
    with fabrica()() as s:
        yield s
