"""Catálogo de serviços (Códigos de Tributação Nacional).

A lista vem da planilha oficial do governo (Anexo B da NFS-e Nacional), convertida
para app/dados/servicos_nacional.json. Quando o governo publicar uma versão nova,
basta converter de novo (veja scripts/converter_anexo_b.py).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

PASTA = Path(__file__).parent / "dados"
ARQUIVO_PADRAO = PASTA / "servicos_nacional.json"
ARQUIVO_PALAVRAS = PASTA / "palavras_servicos.json"


@lru_cache
def carregar_catalogo(arquivo: Path = ARQUIVO_PADRAO) -> dict[str, dict]:
    dados = json.loads(arquivo.read_text(encoding="utf-8"))
    palavras = {}
    if ARQUIVO_PALAVRAS.exists():
        palavras = json.loads(ARQUIVO_PALAVRAS.read_text(encoding="utf-8"))
    catalogo = {}
    for s in dados["servicos"]:
        item = dict(s)
        if palavras.get(s["codigo"]):
            item["palavras"] = palavras[s["codigo"]]
        catalogo[s["codigo"]] = item
    return catalogo


def descricao_oficial(codigo: str) -> str | None:
    servico = carregar_catalogo().get(codigo)
    return servico["descricao"] if servico else None
