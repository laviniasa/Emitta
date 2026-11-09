"""Montagem do XML da DPS (Declaração de Prestação de Serviço) e do pedido
de cancelamento, no padrão nacional da NFS-e.

IMPORTANTE: os nomes de tags seguem o leiaute nacional, mas ANTES de ir para
homologação valide contra os XSDs oficiais (gov.br/nfse > Documentação técnica)
usando `validar_xsd`. Campos de tributação variam conforme o regime da empresa.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from lxml import etree

NS_NFSE = "http://www.sped.fazenda.gov.br/nfse"
VERSAO_LEIAUTE = "1.00"
CODIGO_EVENTO_CANCELAMENTO = "101101"


@dataclass(frozen=True)
class DadosDPS:
    tp_amb: str  # "1" produção, "2" homologação
    versao_aplicativo: str
    emitida_em: datetime  # com fuso horário
    serie: str
    numero: int
    municipio_ibge: str
    prestador_cnpj: str
    opcao_simples: str  # 1 não optante, 2 MEI, 3 ME/EPP
    tomador_tipo: str  # "CPF" ou "CNPJ"
    tomador_documento: str
    tomador_nome: str
    codigo_servico: str  # código de tributação nacional, 6 dígitos
    descricao: str
    valor: str  # "1500.00"


def _sub(pai: etree._Element, tag: str, texto: str | None = None) -> etree._Element:
    el = etree.SubElement(pai, f"{{{NS_NFSE}}}{tag}")
    if texto is not None:
        el.text = texto
    return el


def id_dps(municipio_ibge: str, cnpj: str, serie: str, numero: int) -> str:
    """'DPS' + município(7) + tipo de inscrição(1: 2=CNPJ) + inscrição(14)
    + série(5) + número(15) = 45 caracteres."""
    return f"DPS{municipio_ibge:0>7}2{cnpj:0>14}{serie:0>5}{numero:015d}"


def montar_dps(d: DadosDPS) -> etree._Element:
    raiz = etree.Element(f"{{{NS_NFSE}}}DPS", nsmap={None: NS_NFSE}, versao=VERSAO_LEIAUTE)
    inf = _sub(raiz, "infDPS")
    inf.set("Id", id_dps(d.municipio_ibge, d.prestador_cnpj, d.serie, d.numero))

    _sub(inf, "tpAmb", d.tp_amb)
    _sub(inf, "dhEmi", d.emitida_em.isoformat(timespec="seconds"))
    _sub(inf, "verAplic", d.versao_aplicativo)
    _sub(inf, "serie", d.serie)
    _sub(inf, "nDPS", str(d.numero))
    _sub(inf, "dCompet", d.emitida_em.date().isoformat())
    _sub(inf, "tpEmit", "1")  # 1 = emitido pelo prestador
    _sub(inf, "cLocEmi", d.municipio_ibge)

    prest = _sub(inf, "prest")
    _sub(prest, "CNPJ", d.prestador_cnpj)
    reg = _sub(prest, "regTrib")
    _sub(reg, "opSimpNac", d.opcao_simples)
    _sub(reg, "regEspTrib", "0")

    toma = _sub(inf, "toma")
    _sub(toma, d.tomador_tipo, d.tomador_documento)
    _sub(toma, "xNome", d.tomador_nome)

    serv = _sub(inf, "serv")
    loc = _sub(serv, "locPrest")
    _sub(loc, "cLocPrestacao", d.municipio_ibge)
    cserv = _sub(serv, "cServ")
    _sub(cserv, "cTribNac", d.codigo_servico)
    _sub(cserv, "xDescServ", d.descricao)

    valores = _sub(inf, "valores")
    vprest = _sub(valores, "vServPrest")
    _sub(vprest, "vServ", d.valor)
    trib = _sub(valores, "trib")
    trib_mun = _sub(trib, "tribMun")
    _sub(trib_mun, "tribISSQN", "1")  # 1 = operação tributável
    _sub(trib_mun, "tpRetISSQN", "1")  # 1 = não retido
    tot = _sub(trib, "totTrib")
    _sub(tot, "indTotTrib", "0")  # conferir: empresas do Simples podem exigir pTotTribSN

    return raiz


@dataclass(frozen=True)
class DadosCancelamento:
    tp_amb: str
    versao_aplicativo: str
    quando: datetime
    autor_cnpj: str
    chave_acesso: str
    codigo_motivo: str
    texto_motivo: str
    numero_pedido: int = 1


def montar_pedido_cancelamento(d: DadosCancelamento) -> etree._Element:
    raiz = etree.Element(
        f"{{{NS_NFSE}}}pedRegEvento", nsmap={None: NS_NFSE}, versao=VERSAO_LEIAUTE
    )
    inf = _sub(raiz, "infPedReg")
    inf.set("Id", f"PRE{d.chave_acesso}{CODIGO_EVENTO_CANCELAMENTO}{d.numero_pedido:03d}")
    _sub(inf, "tpAmb", d.tp_amb)
    _sub(inf, "verAplic", d.versao_aplicativo)
    _sub(inf, "dhEvento", d.quando.isoformat(timespec="seconds"))
    _sub(inf, "CNPJAutor", d.autor_cnpj)
    _sub(inf, "chNFSe", d.chave_acesso)
    _sub(inf, "nPedRegEvento", str(d.numero_pedido))
    evento = _sub(inf, f"e{CODIGO_EVENTO_CANCELAMENTO}")
    _sub(evento, "xDesc", "Cancelamento de NFS-e")
    _sub(evento, "cMotivo", d.codigo_motivo)
    _sub(evento, "xMotivo", d.texto_motivo)
    return raiz


def validar_xsd(xml: etree._Element, arquivo_xsd: Path) -> list[str]:
    """Valida contra o XSD oficial. Devolve a lista de erros (vazia = válido)."""
    esquema = etree.XMLSchema(etree.parse(str(arquivo_xsd)))
    if esquema.validate(xml):
        return []
    return [str(erro) for erro in esquema.error_log]


def para_bytes(xml: etree._Element) -> bytes:
    return etree.tostring(xml, xml_declaration=False, encoding="utf-8")
