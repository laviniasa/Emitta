"""Lê XMLs de notas antigas da empresa (emitidas em outro sistema) e aproveita o que dá:

- serviços que ela já emitia (para o contador liberar);
- clientes (tomadores) para aparecerem como "clientes salvos" no app;
- faturamento, para o resumo do ano e o limite do MEI;
- alíquota do ISS usada, para conferir com o cadastro;
- clientes que se repetem todo mês com o mesmo valor (sugestão de nota automática).

Aceita:
- NFS-e nacional (NFSe/DPS do Emissor Nacional): <cTribNac>, <toma>, <vServ>, <pAliq>.
- NFS-e municipal no padrão ABRASF (a maioria das prefeituras): <ItemListaServico> ("14.01"),
  <TomadorServico>, <ValorServicos>, <Aliquota>. Um arquivo pode ter várias notas (lote).

Prefeituras com leiaute próprio (ex.: São Paulo) não trazem o item da lista; o arquivo
é marcado como "sem serviço", mas o resto (cliente, valor) é aproveitado quando encontrado.
Nada é gravado aqui: só leitura. Quem grava é o contador, ao confirmar.
"""
from __future__ import annotations

import re
from collections import Counter, OrderedDict, defaultdict
from decimal import Decimal, InvalidOperation

from lxml import etree

LIMITE_ARQUIVOS = 30
LIMITE_BYTES = 1_000_000

_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, recover=False, remove_comments=True)


def _digitos(t: str | None) -> str:
    return re.sub(r"\D", "", t or "")


def _primeiro(no, *nomes: str) -> str:
    """Texto do primeiro elemento (em qualquer profundidade dentro de `no`) com um desses nomes."""
    for nome in nomes:
        achado = no.xpath(f".//*[local-name()='{nome}']/text()")
        for t in achado:
            if t and t.strip():
                return t.strip()
    return ""


def _no(no, *nomes: str):
    for nome in nomes:
        r = no.xpath(f".//*[local-name()='{nome}']")
        if r:
            return r[0]
    return None


def _centavos(texto: str) -> int:
    try:
        return int((Decimal(texto.replace(",", ".")) * 100).quantize(Decimal("1")))
    except (InvalidOperation, ValueError):
        return 0


def _aliquota(texto: str) -> str | None:
    """ISS em % ("2.00"). ABRASF às vezes manda 0.02 (fração)."""
    if not texto:
        return None
    try:
        v = Decimal(texto.replace(",", "."))
    except InvalidOperation:
        return None
    if 0 < v < 1:
        v *= 100
    return f"{v.quantize(Decimal('0.01'))}" if v > 0 else None


def _ler_nota(no, catalogo: dict) -> dict:
    """Uma nota (nacional ou ABRASF) a partir do nó que a contém."""
    descricao = (_primeiro(no, "xDescServ", "Discriminacao") or "")[:160]
    codigos = []
    for c in no.xpath(".//*[local-name()='cTribNac']/text()"):
        if _digitos(c) in catalogo:
            codigos.append(_digitos(c))
    if not codigos:
        for item in no.xpath(".//*[local-name()='ItemListaServico']/text()"):
            d = _digitos(item)
            if len(d) == 3:  # "1.05" -> "0105"
                d = "0" + d
            if len(d) >= 4:
                codigos += sorted(k for k in catalogo if k.startswith(d[:4]))
    codigos = list(OrderedDict.fromkeys(codigos))
    tomador = _no(no, "toma", "TomadorServico", "Tomador")
    doc = nome = ""
    if tomador is not None:
        doc = _digitos(_primeiro(tomador, "CNPJ", "Cnpj", "CPF", "Cpf"))
        nome = _primeiro(tomador, "xNome", "RazaoSocial", "NomeRazaoSocial")
    prestador = _no(no, "prest", "emit", "PrestadorServico", "Prestador", "IdentificacaoPrestador")
    cnpj_prestador = _digitos(_primeiro(prestador, "CNPJ", "Cnpj")) if prestador is not None else ""
    data = (_primeiro(no, "dCompet", "Competencia") or _primeiro(no, "dhEmi", "dhProc", "DataEmissao"))[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data or ""):
        data = ""
    numero = _primeiro(no, "nNFSe", "Numero")
    chave = ""
    inf = no if etree.QName(no).localname == "infNFSe" else _no(no, "infNFSe")
    if inf is not None and inf.get("Id"):
        chave = _digitos(inf.get("Id"))
    if not chave:
        chave = f"{cnpj_prestador}-{numero}" if numero else ""
    cancelada = bool(no.xpath(".//*[local-name()='NfseCancelamento' or local-name()='CancelamentoNfse']"))
    return {
        "codigos": codigos, "descricao": descricao, "tomador_documento": doc if len(doc) in (11, 14) else "",
        "tomador_nome": nome[:150], "valor_centavos": _centavos(_primeiro(no, "vServ", "ValorServicos")),
        "aliquota": _aliquota(_primeiro(no, "pAliq", "Aliquota")), "data": data, "numero": numero,
        "chave": chave, "cnpj_prestador": cnpj_prestador, "cancelada": cancelada,
    }


def ler_arquivo(conteudo: bytes, catalogo: dict) -> dict:
    """Devolve {"notas": [...], "erro": str|None}."""
    try:
        raiz = etree.fromstring(conteudo, _PARSER)
    except etree.XMLSyntaxError:
        return {"notas": [], "erro": "não é um XML válido"}
    # cada nota: infNFSe (nacional) ou CompNfse/InfNfse (ABRASF); senão, o arquivo todo é uma nota (ex.: só a DPS)
    nos = raiz.xpath("//*[local-name()='CompNfse']") or raiz.xpath("//*[local-name()='infNFSe']") \
        or raiz.xpath("//*[local-name()='InfNfse']") or [raiz]
    return {"notas": [_ler_nota(n, catalogo) for n in nos], "erro": None}


def analisar(arquivos: list[tuple[str, bytes]], catalogo: dict, cnpj_empresa: str,
             aliquota_cadastro: str | None = None) -> dict:
    servicos: "OrderedDict[str, dict]" = OrderedDict()
    avisos: list[str] = []
    notas: list[dict] = []
    vistas: set[str] = set()
    for nome, conteudo in arquivos:
        r = ler_arquivo(conteudo, catalogo)
        if r["erro"]:
            avisos.append(f"{nome}: não é um XML válido.")
            continue
        sem_servico = True
        for n in r["notas"]:
            if n["cnpj_prestador"] and n["cnpj_prestador"] != cnpj_empresa:
                avisos.append(f"{nome}: nota nº {n['numero'] or '?'} é de outra empresa (o CNPJ não bate) e foi ignorada.")
                continue
            if n["codigos"]:
                sem_servico = False
            for cod in n["codigos"]:
                item = servicos.setdefault(cod, {"codigo": cod, "notas": 0, "exemplo": n["descricao"],
                                                 "descricao": catalogo[cod].get("descricao", "")})
                item["notas"] += 1
                if not item["exemplo"] and n["descricao"]:
                    item["exemplo"] = n["descricao"]
            if n["cancelada"] or not n["chave"] or n["chave"] in vistas:
                continue
            vistas.add(n["chave"])
            notas.append({k: n[k] for k in ("chave", "numero", "data", "valor_centavos", "tomador_documento",
                                            "tomador_nome", "descricao", "aliquota")} | {"codigo_servico": (n["codigos"] or [None])[0]})
        if sem_servico:
            avisos.append(f"{nome}: não achamos o código do serviço (alguns municípios usam leiaute próprio).")

    # clientes (tomadores) com a última nota de cada um
    clientes: dict[str, dict] = {}
    for n in sorted(notas, key=lambda x: x["data"] or ""):
        if n["tomador_documento"]:
            clientes[n["tomador_documento"]] = {"documento": n["tomador_documento"], "nome": n["tomador_nome"],
                                                "valor_centavos": n["valor_centavos"], "data": n["data"]}
    # alíquota usada x cadastrada
    aliquotas = Counter(n["aliquota"] for n in notas if n["aliquota"])
    aliquota = None
    if aliquotas:
        usada = aliquotas.most_common(1)[0][0]
        if aliquota_cadastro and Decimal(usada) != Decimal(str(aliquota_cadastro)):
            aliquota = {"nas_notas": usada, "no_emitta": f"{Decimal(str(aliquota_cadastro)):.2f}"}
    # mesmo cliente, mesmo valor, em 3 meses ou mais: sugere nota automática
    por_cliente = defaultdict(list)
    for n in notas:
        if n["tomador_documento"] and n["data"] and n["valor_centavos"] > 0:
            por_cliente[(n["tomador_documento"], n["valor_centavos"])].append(n)
    automaticas = []
    for (doc, valor), lista in por_cliente.items():
        meses = {n["data"][:7] for n in lista}
        if len(meses) >= 3:
            dia = Counter(min(int(n["data"][8:10]), 28) for n in lista).most_common(1)[0][0]
            ultima = max(lista, key=lambda x: x["data"])
            automaticas.append({"documento": doc, "nome": ultima["tomador_nome"], "valor_centavos": valor, "meses": len(meses),
                                "dia": dia, "codigo_servico": ultima["codigo_servico"], "descricao": ultima["descricao"]})
    automaticas.sort(key=lambda a: -a["meses"])
    datas = sorted(n["data"] for n in notas if n["data"])
    return {
        "lidos": len(notas), "servicos": sorted(servicos.values(), key=lambda s: (-s["notas"], s["codigo"])),
        "notas": notas, "clientes": sorted(clientes.values(), key=lambda c: c["nome"]),
        "faturamento": {"notas": len(notas), "total_centavos": sum(n["valor_centavos"] for n in notas),
                        "de": datas[0] if datas else None, "ate": datas[-1] if datas else None},
        "aliquota": aliquota, "automaticas": automaticas[:10], "avisos": avisos[:20],
    }
