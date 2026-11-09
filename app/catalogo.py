"""Catálogo de serviços (Códigos de Tributação Nacional)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ARQUIVO_PADRAO = Path(__file__).parent / "dados" / "servicos_exemplo.json"


@lru_cache
def carregar_catalogo(arquivo: Path = ARQUIVO_PADRAO) -> dict[str, dict]:
    dados = json.loads(arquivo.read_text(encoding="utf-8"))
    return {s["codigo"]: s for s in dados["servicos"]}


def descricao_oficial(codigo: str) -> str | None:
    servico = carregar_catalogo().get(codigo)
    return servico["descricao"] if servico else None
