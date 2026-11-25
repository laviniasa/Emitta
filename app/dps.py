"""Montagem do XML da DPS (Declaração de Prestação de Serviço) e do pedido
de cancelamento, no padrão nacional da NFS-e.

IMPORTANTE: os nomes de tags seguem o leiaute nacional, mas ANTES de ir para
homologação valide contra os XSDs oficiais (gov.br/nfse > Documentação técnica)
usando `validar_xsd`. Campos de tributação variam conforme o regime da empresa.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from lxml import etree

NS_NFSE = "http://www.sped.fazenda.gov.br/nfse"
VERSAO_LEIAUTE = "1.01"
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
    competencia: date | None = None  # data em que o serviço foi prestado
    leiaute: str = "nt009"  # "nt004" na produção até 30/11/2026 (ver Config.leiaute)
    iss_retido: bool = False  # retido pelo tomador (cliente PJ)
    aliquota_iss: str = "0"  # % do ISS (só vai no XML quando a regra exige)
    reg_ap_trib_sn: str = "1"  # regime de apuração do Simples (só ME/EPP)
    p_tot_trib_sn: str = "0.00"  # % aproximado de tributos do Simples (ME/EPP)
    codigo_municipal: str | None = None  # cTribMun: complemento exigido por algumas prefeituras
    # Reforma Tributária (IBS/CBS) — Anexo VIII: NBS, indicador da operação e classificação tributária
    nbs: str | None = None  # 9 dígitos, sem pontos
    cind_op: str | None = None  # 6 dígitos
    cclass_trib: str | None = None  # 6 dígitos (os 3 primeiros são o CST)
    info_compl: str | None = None  # informações complementares (até 2000 caracteres)
    # endereço do tomador: {"cmun", "cep", "logradouro", "numero", "complemento", "bairro"}
    tomador_end: dict | None = None


_TROCAS = {"\u2013": "-", "\u2014": "-", "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
           "\u2026": "...", "\u2022": "-", "\u00a0": " ", "\u20ac": "EUR"}


def texto_leiaute(texto: str | None, quebra: str = " ") -> str:
    """O leiaute nacional só aceita uma linha, com caracteres até o Latin-1 (sem emoji, sem
    aspas curvas) e sem espaço no começo ou no fim. Ajusta o texto sem mudar o sentido."""
    t = str(texto or "")
    linhas = [l.strip() for l in t.replace("\r", "\n").split("\n") if l.strip()]
    t = quebra.join(linhas)
    t = "".join(_TROCAS.get(ch, ch) for ch in t)
    t = "".join(ch if (" " <= ch <= "\u00ff") else " " for ch in t.replace("\t", " "))
    return " ".join(t.split())


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
    _sub(inf, "verAplic", d.versao_aplicativo[:20])
    _sub(inf, "serie", str(int(d.serie)))  # aplicativo próprio: série de 1 a 49999
    _sub(inf, "nDPS", str(d.numero))
    _sub(inf, "dCompet", (d.competencia or d.emitida_em.date()).isoformat())
    _sub(inf, "tpEmit", "1")  # 1 = emitido pelo prestador
    if d.leiaute == "nt009":
        _sub(inf, "finNFSe", "0")  # 0 = NFS-e regular (obrigatório na NT 009; a NT 004 recusa)
    _sub(inf, "cLocEmi", d.municipio_ibge)

    prest = _sub(inf, "prest")
    _sub(prest, "CNPJ", d.prestador_cnpj)
    reg = _sub(prest, "regTrib")
    _sub(reg, "opSimpNac", d.opcao_simples)
    if d.opcao_simples == "3":
        _sub(reg, "regApTribSN", d.reg_ap_trib_sn)
    _sub(reg, "regEspTrib", "0")

    toma = _sub(inf, "toma")
    _sub(toma, d.tomador_tipo, d.tomador_documento)
    _sub(toma, "xNome", texto_leiaute(d.tomador_nome)[:300])
    if endereco_valido(d.tomador_end):
        e = d.tomador_end
        end = _sub(toma, "end")
        nac = _sub(end, "endNac")
        _sub(nac, "cMun", e["cmun"])
        _sub(nac, "CEP", e["cep"])
        _sub(end, "xLgr", texto_leiaute(e["logradouro"])[:255])
        _sub(end, "nro", (texto_leiaute(e.get("numero")) or "S/N")[:60])
        if texto_leiaute(e.get("complemento")):
            _sub(end, "xCpl", texto_leiaute(e["complemento"])[:156])
        _sub(end, "xBairro", (texto_leiaute(e.get("bairro")) or "Centro")[:60])

    serv = _sub(inf, "serv")
    loc = _sub(serv, "locPrest")
    _sub(loc, "cLocPrestacao", d.municipio_ibge)
    cserv = _sub(serv, "cServ")
    _sub(cserv, "cTribNac", d.codigo_servico.zfill(6))
    if d.codigo_municipal:
        _sub(cserv, "cTribMun", d.codigo_municipal)
    if d.nbs:
        _sub(cserv, "cNBS", d.nbs)  # no leiaute, o NBS vem antes da descrição
    _sub(cserv, "xDescServ", texto_leiaute(d.descricao)[:2000])
    if texto_leiaute(d.info_compl):
        _sub(_sub(serv, "infoCompl"), "xInfComp", texto_leiaute(d.info_compl, " / ")[:2000])

    valores = _sub(inf, "valores")
    vprest = _sub(valores, "vServPrest")
    _sub(vprest, "vServ", d.valor)
    trib = _sub(valores, "trib")
    trib_mun = _sub(trib, "tribMun")
    _sub(trib_mun, "tribISSQN", "1")  # 1 = operação tributável
    # 1 = não retido; 2 = retido pelo tomador; 3 = retido pelo intermediário.
    _sub(trib_mun, "tpRetISSQN", "2" if d.iss_retido else "1")
    if aliquota_vai_no_xml(d.opcao_simples, d.reg_ap_trib_sn, d.iss_retido):
        _sub(trib_mun, "pAliq", f"{float(d.aliquota_iss):.2f}")
    # Valor aproximado dos tributos: o formato muda conforme o regime.
    tot = _sub(trib, "totTrib")
    if d.opcao_simples == "3":  # ME/EPP do Simples: percentual do Simples
        _sub(tot, "pTotTribSN", f"{float(d.p_tot_trib_sn):.2f}")
    elif d.opcao_simples == "2":  # MEI
        _sub(tot, "indTotTrib", "0")
    else:  # fora do Simples
        p = _sub(tot, "pTotTrib")
        for campo in ("pTotTribFed", "pTotTribEst", "pTotTribMun"):
            _sub(p, campo, "0.00")

    if d.leiaute == "nt009" and ibscbs_vai_no_xml(d):  # opcional em 2026; só no leiaute novo
        g = _sub(inf, "IBSCBS")
        # pessoa física (CPF) costuma ser uso ou consumo pessoal; empresa (CNPJ), não
        _sub(g, "indFinal", "1" if d.tomador_tipo == "CPF" else "0")
        _sub(g, "cIndOp", d.cind_op)
        _sub(g, "indDest", "0")  # o destinatário é o próprio tomador
        trib = _sub(_sub(g, "valores"), "trib")
        _sub(trib, "CST", d.cclass_trib[:3])  # os 3 primeiros dígitos da classificação são o CST
        _sub(trib, "cClassTrib", d.cclass_trib)

    return raiz


def endereco_valido(e: dict | None) -> bool:
    """Endereço nacional mínimo: município IBGE (7), CEP (8) e logradouro."""
    if not e:
        return False
    return (str(e.get("cmun") or "").isdigit() and len(str(e["cmun"])) == 7
            and str(e.get("cep") or "").isdigit() and len(str(e["cep"])) == 8
            and bool(texto_leiaute(e.get("logradouro"))))


def ibscbs_vai_no_xml(d: "DadosDPS") -> bool:
    """O grupo IBS/CBS (opcional em 2026) só vai com o endereço do tomador: sem ele o
    Emissor Nacional recusa com E0239."""
    return bool(d.nbs and d.cind_op and d.cclass_trib) and endereco_valido(d.tomador_end)


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
    leiaute: str = "nt009"


def montar_pedido_cancelamento(d: DadosCancelamento) -> etree._Element:
    raiz = etree.Element(
        f"{{{NS_NFSE}}}pedRegEvento", nsmap={None: NS_NFSE}, versao=VERSAO_LEIAUTE
    )
    inf = _sub(raiz, "infPedReg")
    if d.leiaute == "nt009":
        # NT 009: Id = "PRE" + chave de acesso (50) + código do evento (6) = 59 caracteres
        inf.set("Id", f"PRE{d.chave_acesso}{CODIGO_EVENTO_CANCELAMENTO}")
    else:
        # NT 004: + número do pedido (3) = 62 caracteres, e o nPedRegEvento no corpo
        inf.set("Id", f"PRE{d.chave_acesso}{CODIGO_EVENTO_CANCELAMENTO}{d.numero_pedido:03d}")
    _sub(inf, "tpAmb", d.tp_amb)
    _sub(inf, "verAplic", d.versao_aplicativo)
    _sub(inf, "dhEvento", d.quando.isoformat(timespec="seconds"))
    _sub(inf, "CNPJAutor", d.autor_cnpj)
    _sub(inf, "chNFSe", d.chave_acesso)
    if d.leiaute != "nt009":
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


def aliquota_vai_no_xml(opcao_simples: str, reg_ap_trib_sn: str, iss_retido: bool) -> bool:
    """Regras do leiaute para o campo pAliq (alíquota do ISS):
    MEI nunca informa; ME/EPP que recolhe tudo pelo Simples só informa quando
    o ISS é retido; os demais informam (quando o município não tem convênio,
    a regra exata depende dele: conferir na homologação)."""
    if opcao_simples == "2":
        return False
    if opcao_simples == "3" and reg_ap_trib_sn in ("", "1"):
        return iss_retido
    return True


def para_bytes(xml: etree._Element) -> bytes:
    # Sem quebras nem indentação: o hash da assinatura depende disso.
    return etree.tostring(xml, xml_declaration=True, encoding="UTF-8")
