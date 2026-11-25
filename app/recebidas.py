"""Notas recebidas: NFS-e em que a empresa é a tomadora, distribuídas pelo ADN.

O ADN (Ambiente de Dados Nacional) entrega, em lotes de até 50, os documentos ligados
ao CNPJ do certificado: GET /contribuintes/DFe/{NSU}?cnpjConsulta=...  Cada item traz
NSU, ChaveAcesso, TipoDocumento (NFSE ou EVENTO) e ArquivoXml (gzip + base64).
O Emittaê guarda só as notas em que a empresa é a tomadora (as que ela emitiu já estão
no próprio Emittaê) e marca como canceladas as que receberem evento de cancelamento.
"""

from __future__ import annotations

import base64
import gzip
from decimal import Decimal, InvalidOperation

from lxml import etree

TAMANHO_LOTE = 50
MAX_LOTES_POR_BUSCA = 20  # até 1.000 documentos por clique; a próxima busca continua do NSU salvo


def _local(el) -> str:
    return etree.QName(el).localname


def _achar(raiz, *caminho):
    """Primeiro elemento que segue o caminho de nomes locais (ignora namespace)."""
    atual = [raiz]
    for nome in caminho:
        prox = []
        for el in atual:
            prox.extend(f for f in el.iter() if f is not el and _local(f) == nome)
        if not prox:
            return None
        atual = prox[:1]
    return atual[0]


def _texto(raiz, *caminho) -> str | None:
    el = _achar(raiz, *caminho)
    return el.text.strip() if el is not None and el.text else None


def _centavos(valor: str | None) -> int | None:
    try:
        return int((Decimal(valor) * 100).quantize(Decimal("1"))) if valor else None
    except InvalidOperation:
        return None


def abrir_xml(arquivo: str) -> str:
    """ArquivoXml do ADN: gzip + base64 (aceita também o XML puro ou só base64)."""
    texto = (arquivo or "").strip()
    if texto.startswith("<"):
        return texto
    bruto = base64.b64decode(texto)
    try:
        return gzip.decompress(bruto).decode("utf-8")
    except OSError:
        return bruto.decode("utf-8")


def ler_nfse(xml: str) -> dict:
    """Campos do leiaute nacional que o painel mostra."""
    raiz = etree.fromstring(xml.encode("utf-8"))
    emit = _achar(raiz, "emit")
    toma = _achar(raiz, "toma")
    doc = lambda el: (_texto(el, "CNPJ") or _texto(el, "CPF")) if el is not None else None  # noqa: E731
    return {
        "numero": _texto(raiz, "nNFSe"),
        "emitida_em": _texto(raiz, "dhEmi") or _texto(raiz, "dhProc"),
        "emitente_documento": doc(emit),
        "emitente_nome": _texto(emit, "xNome") if emit is not None else None,
        "tomador_documento": doc(toma),
        "descricao": _texto(raiz, "xDescServ"),
        "codigo_servico": _texto(raiz, "cTribNac"),
        "valor_centavos": _centavos(_texto(raiz, "vServ") or _texto(raiz, "vLiq")),
    }


def ler_evento(xml: str) -> tuple[str | None, bool]:
    """(chave da nota, é cancelamento?) de um evento distribuído."""
    raiz = etree.fromstring(xml.encode("utf-8"))
    chave = _texto(raiz, "chNFSe")
    tipos = {_local(el) for el in raiz.iter()}
    cancelamento = bool(tipos & {"e101101", "e105102"})  # cancelamento / cancelamento por substituição
    return chave, cancelamento


def buscar(repo, sefin, cert, cliente) -> dict:
    """Lê os lotes novos do ADN para a empresa. Devolve {novas, canceladas, lotes, ult_nsu}."""
    nsu = cliente.adn_ult_nsu or 0
    novas = canceladas = lotes = 0
    for _ in range(MAX_LOTES_POR_BUSCA):
        resposta = sefin.distribuir_dfe(nsu, cliente.cnpj, cert)
        itens = resposta.get("LoteDFe") or []
        lotes += 1
        for item in itens:
            nsu_item = int(item.get("NSU") or 0)
            try:
                xml = abrir_xml(item.get("ArquivoXml") or "")
                tipo = (item.get("TipoDocumento") or "").upper()
                if tipo == "EVENTO":
                    chave, cancelou = ler_evento(xml)
                    if chave and cancelou:
                        repo.marcar_recebida_cancelada(cliente.id, chave)
                        canceladas += 1
                elif tipo in ("NFSE", ""):
                    dados = ler_nfse(xml)
                    if dados["tomador_documento"] == cliente.cnpj and dados["emitente_documento"] != cliente.cnpj:
                        chave = item.get("ChaveAcesso") or ""
                        if repo.guardar_nota_recebida(cliente.id, {**dados, "nsu": nsu_item, "chave": chave, "xml": xml}):
                            novas += 1
            except (ValueError, etree.XMLSyntaxError, OSError) as erro:
                print(f"[recebidas] NSU {nsu_item} ignorado: {erro}", flush=True)
            nsu = max(nsu, nsu_item)
        repo.avancar_nsu(cliente.id, nsu)
        if len(itens) < TAMANHO_LOTE:
            break
    return {"novas": novas, "canceladas": canceladas, "lotes": lotes, "ult_nsu": nsu}
