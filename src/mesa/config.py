"""Configuração lida de variáveis de ambiente (e de um arquivo .env, se existir)."""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _carregar_env(caminho: Path = Path(".env")) -> None:
    """Carrega um .env simples (CHAVE=valor) sem sobrescrever o que já está no ambiente."""
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip().strip("\"'"))


@dataclass(frozen=True)
class Config:
    database_url: str
    segredo_jwt: str
    jwt_minutos: int
    url_publica: str


@lru_cache
def config() -> Config:
    _carregar_env()
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise RuntimeError("Defina DATABASE_URL (veja .env.example).")
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgresql://")

    segredo = os.environ.get("SEGREDO_JWT", "")
    if len(segredo) < 32:
        raise RuntimeError("Defina SEGREDO_JWT com pelo menos 32 caracteres aleatórios.")

    return Config(
        database_url=url,
        segredo_jwt=segredo,
        jwt_minutos=int(os.environ.get("JWT_MINUTOS", "60")),
        url_publica=os.environ.get("URL_PUBLICA", "http://localhost:8000").rstrip("/"),
    )
