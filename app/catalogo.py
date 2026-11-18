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


ARQUIVO_ANEXO8 = PASTA / "anexo8.json"


@lru_cache
def carregar_anexo8() -> dict[str, dict]:
    """Anexo VIII (Reforma Tributária): item da LC 116 -> NBS, cIndOp e cClassTrib possíveis."""
    if not ARQUIVO_ANEXO8.exists():
        return {}
    return json.loads(ARQUIVO_ANEXO8.read_text(encoding="utf-8"))["itens"]


def opcoes_ibscbs(codigo: str) -> dict:
    """Opções de NBS e classificação tributária para um código de serviço (cTribNac de 6 dígitos)."""
    return carregar_anexo8().get(f"{codigo[:2]}.{codigo[2:4]}", {"nbs": [], "cclass": []})


def ibscbs_sugerido(codigo: str) -> dict:
    """Primeira opção do Anexo VIII: NBS, cIndOp e cClassTrib (o contador pode trocar)."""
    op = opcoes_ibscbs(codigo)
    if not op["nbs"]:
        return {"nbs": None, "cind_op": None, "cclass_trib": None}
    nbs = op["nbs"][0]
    cclass = next((c["codigo"] for c in op["cclass"] if c["codigo"] == "000001"), op["cclass"][0]["codigo"] if op["cclass"] else "000001")
    return {"nbs": nbs["codigo"], "cind_op": nbs["cind_op"], "cclass_trib": cclass}


def descricao_oficial(codigo: str) -> str | None:
    servico = carregar_catalogo().get(codigo)
    return servico["descricao"] if servico else None
