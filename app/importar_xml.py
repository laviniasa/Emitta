"""Lê XMLs de notas antigas da empresa e descobre quais serviços ela já emitia.

Aceita:
- NFS-e nacional (DPS/NFSe do Emissor Nacional): código de tributação nacional em <cTribNac>.
- NFS-e municipal no padrão ABRASF (a maioria das prefeituras): item da lista em
  <ItemListaServico> ("14.01" ou "1401"), que vira os códigos nacionais desse subitem.

Notas de prefeituras com leiaute próprio (ex.: São Paulo, que usa um código municipal de
5 números) não trazem o item da lista; nesses casos o arquivo é marcado como "sem serviço".
"""
from __future__ import annotations

import re
from collections import OrderedDict

from lxml import etree

LIMITE_ARQUIVOS = 30
LIMITE_BYTES = 1_000_000

_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, recover=False, remove_comments=True)


def _textos(raiz, nome: str) -> list[str]:
    return [t.strip() for t in raiz.xpath(f"//*[local-name()='{nome}']/text()") if t and t.strip()]


def _digitos(t: str) -> str:
    return re.sub(r"\D", "", t or "")


def ler_arquivo(conteudo: bytes, catalogo: dict) -> dict:
    """Devolve {"codigos": [(codigo, descricao_da_nota)], "cnpjs": set, "erro": str|None}."""
    try:
        raiz = etree.fromstring(conteudo, _PARSER)
    except etree.XMLSyntaxError:
        return {"codigos": [], "cnpjs": set(), "erro": "não é um XML válido"}
    descricoes = _textos(raiz, "xDescServ") or _textos(raiz, "Discriminacao") or _textos(raiz, "Discriminação")
    descricao = (descricoes[0] if descricoes else "")[:160]
    achados: list[tuple[str, str]] = []
    for c in _textos(raiz, "cTribNac"):
        cod = _digitos(c)
        if cod in catalogo:
            achados.append((cod, descricao))
    if not achados:
        for item in _textos(raiz, "ItemListaServico"):
            d = _digitos(item)
            if len(d) == 3:  # "1.05" -> "0105"
                d = "0" + d
            sub = d[:4]
            candidatos = sorted(k for k in catalogo if k.startswith(sub)) if len(sub) == 4 else []
            achados += [(k, descricao) for k in candidatos]
    cnpjs = {_digitos(t) for t in _textos(raiz, "CNPJ") + _textos(raiz, "Cnpj")}
    return {"codigos": achados, "cnpjs": cnpjs, "erro": None if achados else "sem serviço reconhecido"}


def analisar(arquivos: list[tuple[str, bytes]], catalogo: dict, cnpj_empresa: str) -> dict:
    """Junta o resultado de vários XMLs: serviços (com quantas notas e um exemplo) e avisos."""
    servicos: "OrderedDict[str, dict]" = OrderedDict()
    avisos = []
    lidos = 0
    for nome, conteudo in arquivos:
        r = ler_arquivo(conteudo, catalogo)
        if r["erro"] == "não é um XML válido":
            avisos.append(f"{nome}: não é um XML válido.")
            continue
        lidos += 1
        if r["cnpjs"] and cnpj_empresa not in r["cnpjs"]:
            avisos.append(f"{nome}: parece ser nota de outra empresa (o CNPJ não bate).")
        if not r["codigos"]:
            avisos.append(f"{nome}: não achamos o código do serviço (alguns municípios usam leiaute próprio).")
        vistos = set()
        for cod, desc in r["codigos"]:
            if cod in vistos:
                continue
            vistos.add(cod)
            item = servicos.setdefault(cod, {"codigo": cod, "notas": 0, "exemplo": desc,
                                             "descricao": catalogo[cod].get("descricao", "")})
            item["notas"] += 1
            if not item["exemplo"] and desc:
                item["exemplo"] = desc
    lista = sorted(servicos.values(), key=lambda s: (-s["notas"], s["codigo"]))
    return {"lidos": lidos, "servicos": lista, "avisos": avisos[:20]}
