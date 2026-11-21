from logging.config import fileConfig

from alembic import context

from mesa import modelos  # noqa: F401  (registra as tabelas em Base.metadata)
from mesa.db import Base, engine

if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def rodar() -> None:
    conexao_existente = context.config.attributes.get("connection")
    if conexao_existente is not None:  # usada pelos testes
        context.configure(connection=conexao_existente, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return

    with engine().connect() as conexao:
        context.configure(connection=conexao, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


rodar()
