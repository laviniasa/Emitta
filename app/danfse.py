"""DANFSe v2.0: o PDF da nota no modelo oficial do padrão nacional (Nota Técnica SE/CGNFS-e nº 008/2026).

Desde julho de 2026 o governo não gera mais o PDF pela API (ADN /danfse): quem emite é que
gera o DANFSe, no modelo do Anexo I da NT 008. Regras seguidas aqui:
- A4 retrato, uma página, borda de 1 pt e linhas de 0,5 pt entre os blocos;
- títulos dos blocos 7 pt negrito caixa alta; labels 6 pt negrito; conteúdo 7 pt;
- cinza claro (5%) no cabeçalho, nos títulos dos blocos, em "Emitente da NFS-e" e em
  "Valor Líquido da NFS-e + IBS/CBS";
- só imprime o que está no XML da NFS-e (campo vazio = "-"); reticências nos limites da NT;
- QR Code com a consulta pública; "CANCELADA" em marca d'água; em homologação,
  "NFS-e SEM VALIDADE JURÍDICA" em vermelho no cabeçalho.

Os dados vêm do XML autorizado (NFSe/infNFSe, que traz a DPS dentro). Se ele não estiver
disponível (simulação), usa a DPS enviada e os dados guardados da nota.
"""
from __future__ import annotations

import functools
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from lxml import etree
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import Color, black, white
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph

NS = "http://www.sped.fazenda.gov.br/nfse"
URL_CONSULTA = "https://www.nfse.gov.br/ConsultaPublica/?tpc=1&chave="

CINZA_5 = Color(0.95, 0.95, 0.95)
CINZA_MARCA = Color(0.65, 0.65, 0.65, alpha=0.45)  # K35
VERMELHO = Color(0.85, 0.0, 0.0)

FONTE = "Helvetica"          # métrica da Arial (fonte da NT)
FONTE_N = "Helvetica-Bold"

_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=True)

TP_EMIT = {"1": "Prestador", "2": "Tomador", "3": "Intermediário"}
C_STAT = {"100": "NFS-e Gerada", "101": "NFS-e de Substituição Gerada", "102": "NFS-e de Decisão Judicial",
          "103": "NFS-e Avulsa"}
FIN_NFSE = {"0": "NFS-e regular"}
OP_SIMP_NAC = {"1": "Não Optante", "2": "Optante - Microempreendedor Individual (MEI)",
               "3": "Optante - Microempresa ou Empresa de Pequeno Porte (ME/EPP)"}
REG_AP_TRIB_SN = {
    "1": "Regime de apuração dos tributos federais e municipal pelo Simples Nacional",
    "2": "Regime de apuração dos tributos federais pelo SN e o ISSQN pela NFS-e conforme respectiva legislação municipal do tributo",
    "3": "Regime de apuração dos tributos federais e municipal pela NFS-e conforme respectivas legislações federal e municipal de cada tributo",
}
TRIB_ISSQN = {"1": "Operação Tributável", "2": "Imunidade", "3": "Exportação de Serviço", "4": "Não Incidência"}
TP_RET_ISSQN = {"1": "Não Retido", "2": "Retido pelo Tomador", "3": "Retido pelo Intermediário"}
REG_ESP_TRIB = {"0": "Nenhum", "1": "Ato Cooperado (Cooperativa)", "2": "Estimativa", "3": "Microempresa Municipal",
                "4": "Notário ou Registrador", "5": "Profissional Autônomo", "6": "Sociedade de Profissionais"}


@functools.lru_cache(maxsize=1)
def _municipios() -> dict:
    arq = Path(__file__).parent / "dados" / "municipios_ibge.json"
    try:
        return json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def municipio_uf(codigo: str | None) -> str:
    """"3106200" -> "Belo Horizonte / MG"."""
    if not codigo:
        return "-"
    m = _municipios().get(str(codigo))
    return f"{m[0]} / {m[1]}" if m else str(codigo)


# ---------------------------------------------------------------- leitura do XML

class _Xml:
    """Busca por nome local (sem se preocupar com prefixo) dentro de infNFSe e da DPS."""

    def __init__(self, nfse: etree._Element | None, dps: etree._Element | None):
        self.nfse = nfse
        self.dps = dps

    @staticmethod
    def _busca(raiz, caminho: str):
        if raiz is None:
            return None
        partes = caminho.split("/")
        xp = ".//" + "/".join(f"*[local-name()='{p}']" for p in partes)
        r = raiz.xpath(xp)
        return r[0] if r else None

    def no_nfse(self, caminho):
        return self._busca(self.nfse, caminho)

    def no_dps(self, caminho):
        return self._busca(self.dps, caminho)

    def t(self, caminho: str, onde: str = "ambos") -> str | None:
        for raiz in ((self.nfse,) if onde == "nfse" else (self.dps,) if onde == "dps" else (self.nfse, self.dps)):
            n = self._busca(raiz, caminho)
            if n is not None and n.text and n.text.strip():
                return n.text.strip()
        return None


def _ler(texto: str | None):
    if not texto:
        return None
    try:
        return etree.fromstring(texto.encode("utf-8") if isinstance(texto, str) else texto, _PARSER)
    except etree.XMLSyntaxError:
        return None


def _montar_xml(nota) -> _Xml:
    raiz = _ler(getattr(nota, "xml_nfse", None))
    inf = None
    if raiz is not None:
        achado = raiz.xpath(".//*[local-name()='infNFSe']")
        inf = achado[0] if achado else (raiz if etree.QName(raiz).localname == "infNFSe" else None)
    dps = None
    if inf is not None:
        achado = inf.xpath(".//*[local-name()='infDPS']")
        dps = achado[0] if achado else None
    if dps is None:
        d = _ler(getattr(nota, "xml_dps", None))
        if d is not None:
            achado = d.xpath(".//*[local-name()='infDPS']")
            dps = achado[0] if achado else d
    return _Xml(inf, dps)


# ---------------------------------------------------------------- formatação

def _corta(texto: str | None, limite: int) -> str:
    if not texto:
        return "-"
    texto = " ".join(str(texto).split())
    return texto if len(texto) <= limite else texto[: limite - 3].rstrip() + "..."


def _doc(d: str | None) -> str:
    if not d:
        return "-"
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    return d


def _dinheiro(v: str | None) -> str:
    if v in (None, ""):
        return "-"
    try:
        q = Decimal(v).quantize(Decimal("0.01"))
    except InvalidOperation:
        return v
    inteiro, dec = f"{q:,.2f}".split(".")
    return f"R$ {inteiro.replace(',', '.')},{dec}"


def _pct(v: str | None) -> str:
    if v in (None, ""):
        return "-"
    try:
        return f"{Decimal(v).quantize(Decimal('0.01'))}".replace(".", ",") + "%"
    except InvalidOperation:
        return v


def _data(v: str | None, com_hora: bool = False) -> str:
    if not v:
        return "-"
    try:
        d = datetime.fromisoformat(v)
        return d.strftime("%d/%m/%Y %H:%M:%S" if com_hora else "%d/%m/%Y")
    except ValueError:
        return v[:10]


def _cep(v: str | None) -> str:
    if not v or len(v) != 8:
        return v or "-"
    return f"{v[:2]}.{v[2:5]}-{v[5:]}"


def _endereco(x: _Xml, base: str, onde: str) -> tuple[str, str, str]:
    """(endereço, município / UF, código IBGE / CEP) de prest|toma (DPS) ou emit (NFS-e)."""
    # DPS: end/xLgr... com end/endNac/{cMun,CEP}; NFS-e: emit/enderNac/{xLgr,...,cMun,UF,CEP}
    pega = (lambda c: x.t(f"{base}/{c}", onde) or x.t(f"{base}/endNac/{c}", onde))
    lgr = pega("xLgr")
    if not lgr:
        return "-", "-", "-"
    partes = [lgr, pega("nro"), pega("xCpl"), pega("xBairro")]
    cmun = pega("cMun")
    uf = pega("UF")
    mun = municipio_uf(cmun)
    if uf and mun == cmun:
        mun = f"{cmun} / {uf}"
    return (_corta(", ".join(p for p in partes if p), 77), _corta(mun, 37),
            f"{cmun or '-'} / {_cep(pega('CEP'))}")


def _cod_trib(nac: str | None, mun: str | None) -> str:
    if not nac:
        return "-"
    n = f"{nac[:2]}.{nac[2:4]}.{nac[4:6]}" if len(nac) == 6 else nac
    return f"{n} / {mun}" if mun else n


def _nbs(v: str | None) -> str:
    if not v:
        return "-"
    return f"{v[0]}.{v[1:5]}.{v[5:7]}.{v[7:9]}" if len(v) == 9 else v


# ---------------------------------------------------------------- desenho

_E_TITULO = ParagraphStyle("titulo", fontName=FONTE_N, fontSize=7, leading=8.4)
_E_LABEL = ParagraphStyle("label", fontName=FONTE_N, fontSize=6, leading=7)
_E_LABEL_ID = ParagraphStyle("label_id", fontName=FONTE_N, fontSize=7, leading=8.2)
_E_VALOR = ParagraphStyle("valor", fontName=FONTE, fontSize=7, leading=8.4)
_E_LINHA = ParagraphStyle("linha", fontName=FONTE_N, fontSize=7, leading=8.4, alignment=TA_CENTER)


class _Folha:
    def __init__(self, c: Canvas):
        self.c = c
        self.larg_pag, self.alt_pag = A4
        self.x0 = 0.30 * cm
        self.largura = 20.40 * cm
        self.y = self.alt_pag - 0.30 * cm
        self.pad = 0.10 * cm

    def _para(self, texto: str, estilo, largura: float):
        p = Paragraph(texto, estilo)
        _, h = p.wrap(largura, 10_000)
        return p, h

    def linha_h(self, y: float):
        self.c.setLineWidth(0.5)
        self.c.line(self.x0, y, self.x0 + self.largura, y)

    def bloco(self, linhas: list[list[tuple]], titulo: str | None = None, col_titulo: float = 0.25,
              cols: int = 4, label_id: bool = False):
        """Desenha linhas de células (label, valor, colunas, sombreado). Se houver título,
        ele ocupa a 1ª célula da 1ª linha (sombreada)."""
        self.linha_h(self.y)
        larg_col = self.largura / cols
        primeira = True
        for linha in linhas:
            celulas = list(linha)
            if titulo and primeira:
                celulas = [("__titulo__", titulo, 1, True)] + celulas
            # altura da linha = maior célula
            medidas = []
            for label, valor, span, sombra in celulas:
                w = larg_col * span - 2 * self.pad
                if label == "__titulo__":
                    p, h = self._para(escape(valor), _E_TITULO, w)
                    medidas.append((None, 0, p, h, span, sombra))
                    continue
                pl, hl = self._para(escape(label), _E_LABEL_ID if label_id else _E_LABEL, w) if label else (None, 0)
                pv, hv = self._para(escape(valor or "-").replace("\n", "<br/>"), _E_VALOR, w)
                medidas.append((pl, hl, pv, hv, span, sombra))
            alt = max(hl + hv for _, hl, _, hv, _, _ in medidas) + 2 * self.pad + 1
            x = self.x0
            for pl, hl, pv, hv, span, sombra in medidas:
                w = larg_col * span
                if sombra:
                    self.c.setFillColor(CINZA_5)
                    self.c.rect(x, self.y - alt, w, alt, stroke=0, fill=1)
                    self.c.setFillColor(black)
                yy = self.y - self.pad
                if pl is not None:
                    pl.drawOn(self.c, x + self.pad, yy - hl)
                    yy -= hl
                pv.drawOn(self.c, x + self.pad, yy - hv)
                x += w
            self.y -= alt
            primeira = False

    def faixa(self, texto: str):
        """Linha única de bloco suprimido (ex.: DESTINATÁRIO ... NÃO IDENTIFICADO NA NFS-e)."""
        self.linha_h(self.y)
        p, h = self._para(escape(texto), _E_LINHA, self.largura - 2 * self.pad)
        alt = max(h + 2, 0.32 * cm)
        p.drawOn(self.c, self.x0 + self.pad, self.y - alt + (alt - h) / 2)
        self.y -= alt


def _logo_nfse(c: Canvas, x: float, y_topo: float):
    """Marca da NFS-e (versão horizontal, 0,85 x 4,00 cm) desenhada em vetor."""
    verde = Color(0.20, 0.62, 0.30)
    azul = Color(0.27, 0.42, 0.55)
    base = y_topo - 0.68 * cm
    c.setFillColor(verde)
    c.setFont(FONTE_N, 22)
    c.drawString(x, base, "NFS")
    w = c.stringWidth("NFS", FONTE_N, 22)
    c.setFillColor(azul)
    c.setFont(FONTE_N, 15)
    c.drawString(x + w + 0.5, base, "e")
    w2 = w + c.stringWidth("e", FONTE_N, 15) + 4
    c.setFillColor(Color(0.35, 0.35, 0.35))
    c.setFont(FONTE, 7.5)
    c.drawString(x + w2, base + 9, "Nota Fiscal de")
    c.drawString(x + w2, base + 1, "Serviço eletrônica")
    c.setFillColor(black)


def _qr(c: Canvas, x: float, y: float, tamanho: float, conteudo: str):
    w = QrCodeWidget(conteudo, barLevel="M")
    b = w.getBounds()
    d = Drawing(tamanho, tamanho, transform=[tamanho / (b[2] - b[0]), 0, 0, tamanho / (b[3] - b[1]), 0, 0])
    d.add(w)
    renderPDF.draw(d, c, x, y)


def _totais_tributos(x: _Xml) -> str:
    """Linha obrigatória (Lei 12.741/2012), a partir do totTrib da DPS."""
    prefixo = "Totais aproximados dos Tributos cfe. Lei n° 12.741/2012:"
    sn = x.t("totTrib/pTotTribSN", "dps")
    if sn:
        return f"{prefixo} Simples Nacional (tributos unificados): {_pct(sn)};"
    if x.no_dps("totTrib/vTotTrib") is not None:
        return (f"{prefixo} Federais: {_dinheiro(x.t('vTotTrib/vTotTribFed', 'dps'))}; "
                f"Estaduais: {_dinheiro(x.t('vTotTrib/vTotTribEst', 'dps'))}; "
                f"Municipais: {_dinheiro(x.t('vTotTrib/vTotTribMun', 'dps'))};")
    if x.no_dps("totTrib/pTotTrib") is not None:
        return (f"{prefixo} Federais: {_pct(x.t('pTotTrib/pTotTribFed', 'dps'))}; "
                f"Estaduais: {_pct(x.t('pTotTrib/pTotTribEst', 'dps'))}; "
                f"Municipais: {_pct(x.t('pTotTrib/pTotTribMun', 'dps'))};")
    return f"{prefixo} Federais: -; Estaduais: -; Municipais: -;"


def gerar_danfse(nota, cliente=None, ambiente: str = "producao") -> bytes:
    x = _montar_xml(nota)
    buf = BytesIO()
    c = Canvas(buf, pagesize=A4)
    chave = (getattr(nota, "chave_acesso", None) or "").strip()
    numero = getattr(nota, "numero_nfse", None) or x.t("nNFSe", "nfse")
    c.setTitle(f"DANFSe {numero or ''} - {chave}")
    c.setAuthor("EmitHub")
    f = _Folha(c)
    larg = f.largura
    tp_amb = x.t("tpAmb", "dps") or ("2" if ambiente != "producao" else "1")

    # ---------- cabeçalho (sombreado)
    alt_cab = 1.30 * cm
    c.setFillColor(CINZA_5)
    c.rect(f.x0, f.y - alt_cab, larg, alt_cab, stroke=0, fill=1)
    c.setFillColor(black)
    _logo_nfse(c, f.x0 + 0.19 * cm, f.y - 0.14 * cm)
    meio = f.x0 + larg / 2
    c.setFont(FONTE_N, 9)
    c.drawCentredString(meio, f.y - 0.48 * cm, "DANFSe v2.0")
    c.drawCentredString(meio, f.y - 0.85 * cm, "Documento Auxiliar da NFS-e")
    if tp_amb == "2":
        c.setFillColor(VERMELHO)
        c.drawCentredString(meio, f.y - 1.20 * cm, "NFS-e SEM VALIDADE JURÍDICA")
        c.setFillColor(black)
    direita = f.x0 + larg - 0.2 * cm
    c_trib = x.t("cServ/cTribNac", "dps") or ""
    if not c_trib.startswith("99"):
        mun_emit = x.t("xLocEmi", "nfse")
        cmun_emit = x.t("emit/enderNac/cMun", "nfse") or x.t("cLocEmi", "dps")
        uf_emit = x.t("emit/enderNac/UF", "nfse") or (_municipios().get(str(cmun_emit), [None, None])[1])
        rotulo_mun = f"{mun_emit} / {uf_emit}" if mun_emit and uf_emit else municipio_uf(cmun_emit)
        c.setFont(FONTE, 8)
        c.drawRightString(direita, f.y - 0.48 * cm, f"Município: {rotulo_mun}")
    c.setFont(FONTE, 6)
    c.drawRightString(direita, f.y - 0.78 * cm, f"Ambiente Gerador: {x.t('ambGer', 'nfse') or '-'}")
    c.drawRightString(direita, f.y - 1.02 * cm, f"Tipo de Ambiente: {tp_amb}")
    f.y -= alt_cab

    # ---------- dados da NFS-e (labels em caixa alta 7 pt) + QR Code
    topo_id = f.y
    larg_dados = larg * 0.75
    f_id = _Folha(c)
    f_id.y = f.y
    f_id.largura = larg_dados
    sit = C_STAT.get(x.t("cStat", "nfse") or "", None)
    if getattr(nota, "situacao", "") == "cancelada":
        sit = "NFS-e Cancelada"
    f_id.linha_h = lambda y: None
    f_id.bloco([
        [("CHAVE DE ACESSO DA NFS-e", chave or "-", 3, False)],
        [("NÚMERO DA NFS-e", str(numero) if numero else "-", 1, False),
         ("COMPETÊNCIA DA NFS-e", _data(x.t("dCompet", "dps")), 1, False),
         ("DATA E HORA DA EMISSÃO DA NFS-e", _data(x.t("dhProc", "nfse"), True), 1, False)],
        [("NÚMERO DA DPS", x.t("nDPS", "dps") or str(getattr(nota, "numero_dps", "") or "-"), 1, False),
         ("SÉRIE DA DPS", x.t("serie", "dps") or "-", 1, False),
         ("DATA E HORA DA EMISSÃO DA DPS", _data(x.t("dhEmi", "dps"), True), 1, False)],
        [("EMITENTE DA NFS-e", TP_EMIT.get(x.t("tpEmit", "dps") or "", "-"), 1, True),
         ("SITUAÇÃO DA NFS-e", _corta(sit, 37), 1, False),
         ("FINALIDADE", _corta(FIN_NFSE.get(x.t("finNFSe", "dps") or "", None), 37), 1, False)],
    ], cols=3, label_id=True)
    # QR Code à direita
    tam = 1.75 * cm
    xq = f.x0 + larg_dados + (larg - larg_dados - tam) / 2
    if chave:
        _qr(c, xq, topo_id - 0.15 * cm - tam, tam, URL_CONSULTA + chave)
    p = Paragraph("A autenticidade desta NFS-e pode ser verificada pela leitura deste código QR ou pela "
                  "consulta da chave de acesso no portal nacional da NFS-e",
                  ParagraphStyle("qr", fontName=FONTE, fontSize=6, leading=7, alignment=TA_CENTER))
    wq = larg - larg_dados - 0.3 * cm
    _, hq = p.wrap(wq, 200)
    p.drawOn(c, f.x0 + larg_dados + 0.15 * cm, topo_id - 0.2 * cm - tam - hq)
    f.y = min(f_id.y, topo_id - 0.3 * cm - tam - hq)

    # ---------- prestador
    end_p, mun_p, ibge_p = _endereco(x, "emit/enderNac", "nfse")
    if end_p == "-":
        end_p, mun_p, ibge_p = _endereco(x, "prest/end", "dps")
    if mun_p == "-":
        mun_p = municipio_uf(x.t("cLocEmi", "dps"))
    doc_prest = x.t("emit/CNPJ", "nfse") or x.t("prest/CNPJ", "dps") or x.t("prest/CPF", "dps")
    f.bloco([
        [("CNPJ / CPF / NIF", _doc(doc_prest), 1, False),
         ("Indicador Municipal (Inscrição)", x.t("emit/IM", "nfse") or x.t("prest/IM", "dps") or "-", 1, False),
         ("Telefone", x.t("emit/fone", "nfse") or x.t("prest/fone", "dps") or "-", 1, False)],
        [("Nome / Nome Empresarial", _corta(x.t("emit/xNome", "nfse") or x.t("prest/xNome", "dps")
                                            or getattr(cliente, "razao_social", None), 77), 2, False),
         ("Município / Sigla UF", mun_p, 1, False), ("Código IBGE / CEP", ibge_p, 1, False)],
        [("Endereço", end_p, 2, False),
         ("E-mail", x.t("emit/email", "nfse") or x.t("prest/email", "dps") or "-", 2, False)],
        [("Simples Nacional na Data de Competência", _corta(OP_SIMP_NAC.get(x.t("regTrib/opSimpNac", "dps") or ""), 37), 1, False),
         ("Regime de Apuração Tributária pelo SN", _corta(REG_AP_TRIB_SN.get(x.t("regTrib/regApTribSN", "dps") or ""), 77), 3, False)],
    ], titulo="PRESTADOR / FORNECEDOR")

    # ---------- tomador
    if x.no_dps("toma") is not None:
        doc_t = x.t("toma/CNPJ", "dps") or x.t("toma/CPF", "dps") or x.t("toma/NIF", "dps")
        end_t, mun_t, ibge_t = _endereco(x, "toma/end", "dps")
        f.bloco([
            [("CNPJ / CPF / NIF", _doc(doc_t), 1, False),
             ("Indicador Municipal (Inscrição)", x.t("toma/IM", "dps") or "-", 1, False),
             ("Telefone", x.t("toma/fone", "dps") or "-", 1, False)],
            [("Nome / Nome Empresarial", _corta(x.t("toma/xNome", "dps"), 77), 2, False),
             ("Município / Sigla UF", mun_t, 1, False), ("Código IBGE / CEP", ibge_t, 1, False)],
            [("Endereço", end_t, 2, False), ("E-mail", x.t("toma/email", "dps") or "-", 2, False)],
        ], titulo="TOMADOR / ADQUIRENTE")
    else:
        f.faixa("TOMADOR/ADQUIRENTE DA OPERAÇÃO NÃO IDENTIFICADO NA NFS-e")
    f.faixa("DESTINATÁRIO DA OPERAÇÃO NÃO IDENTIFICADO NA NFS-e")
    f.faixa("INTERMEDIÁRIO DA OPERAÇÃO NÃO IDENTIFICADO NA NFS-e")

    # ---------- serviço
    loc_prest = x.t("xLocPrestacao", "nfse")
    cmun_prest = x.t("locPrest/cLocPrestacao", "dps")
    uf_prest = _municipios().get(str(cmun_prest), [None, None])[1] if cmun_prest else None
    if loc_prest:
        local = f"{loc_prest} / {uf_prest or '-'} / BR"
    else:
        local = f"{municipio_uf(cmun_prest)} / BR" if cmun_prest else "-"
    desc_trib = x.t("xTribMun", "nfse") or x.t("xTribNac", "nfse")
    if not desc_trib and getattr(nota, "codigo_servico", None):
        from .catalogo import carregar_catalogo
        desc_trib = carregar_catalogo().get(nota.codigo_servico, {}).get("descricao")
    f.bloco([
        [("Código de Tributação Nacional / Municipal", _cod_trib(x.t("cServ/cTribNac", "dps"), x.t("cServ/cTribMun", "dps")), 1, False),
         ("Código da NBS", _nbs(x.t("cServ/cNBS", "dps")), 1, False),
         ("Local da Prestação / Sigla UF / País", local, 1, False)],
        [("", _corta(desc_trib, 167), 4, False)],
        [("Descrição do Serviço", _corta(x.t("cServ/xDescServ", "dps"), 1297), 4, False)],
    ], titulo="SERVIÇO PRESTADO")

    # ---------- tributação municipal
    trib = x.t("tribMun/tribISSQN", "dps")
    if trib in ("1", "2", "3", "4"):
        loc_inc = x.t("xLocIncid", "nfse")
        cinc = x.t("cLocIncid", "nfse")
        uf_inc = _municipios().get(str(cinc), [None, None])[1] if cinc else None
        incid = f"{loc_inc} / {uf_inc or '-'} / BR" if loc_inc else "-"
        linhas = [
            [("Tipo de Tributação do ISSQN", TRIB_ISSQN.get(trib, "-"), 1, False),
             ("Município / Sigla UF / País da Incidência do ISSQN", incid, 2, False)],
        ]
        reg_esp = x.t("regTrib/regEspTrib", "dps")
        if reg_esp and reg_esp != "0":
            linhas.append([("Regime Especial de Tributação do ISSQN", REG_ESP_TRIB.get(reg_esp, reg_esp), 4, False)])
        linhas.append([
            ("BC ISSQN", _dinheiro(x.t("valores/vBC", "nfse")), 1, False),
            ("Alíquota Aplicada", _pct(x.t("valores/pAliqAplic", "nfse")), 1, False),
            ("Retenção do ISSQN", TP_RET_ISSQN.get(x.t("tribMun/tpRetISSQN", "dps") or "", "-"), 1, False),
            ("ISSQN Apurado", _dinheiro(x.t("valores/vISSQN", "nfse")), 1, False)])
        f.bloco(linhas, titulo="TRIBUTAÇÃO MUNICIPAL (ISSQN)")
    else:
        f.faixa("TRIBUTAÇÃO MUNICIPAL (ISSQN) - OPERAÇÃO NÃO SUJEITA AO ISSQN")

    # ---------- tributação federal
    f.bloco([
        [("IRRF", _dinheiro(x.t("tribFed/vRetIRRF", "dps")), 1, False),
         ("Contribuição Previdenciária - Retida", _dinheiro(x.t("tribFed/vRetCP", "dps")), 1, False),
         ("Contribuições Sociais - Retidas", _dinheiro(x.t("tribFed/vRetCSLL", "dps")), 1, False)],
        [("PIS - Débito Apuração Própria", _dinheiro(x.t("piscofins/vPis", "dps")), 1, False),
         ("COFINS - Débito Apuração Própria", _dinheiro(x.t("piscofins/vCofins", "dps")), 1, False),
         ("Descrição Contrib. Sociais - Retidas", x.t("piscofins/tpRetPisCofins", "dps") or "-", 2, False)],
    ], titulo="TRIBUTAÇÃO FEDERAL (EXCETO CBS)")

    # ---------- IBS / CBS
    cst = x.t("gIBSCBS/CST") or x.t("IBSCBS/valores/trib/gIBSCBS/CST")
    cclass = x.t("gIBSCBS/cClassTrib")
    ind = [x.t("IBSCBS/cIndOp", "dps") or "-", x.t("cLocalidadeIncid", "nfse") or "-",
           x.t("xLocalidadeIncid", "nfse") or "-", "-"]
    f.bloco([
        [("CST / cClassTrib", f"{cst or '-'} / {cclass or '-'}", 1, False),
         ("Indicador de Operação / Código IBGE Incidência / Município Incidência / Sigla UF", " / ".join(ind), 2, False)],
        [("Exclusões e Reduções da Base de Cálculo", _dinheiro(x.t("IBSCBS/valores/vCalcReeRepRes", "nfse")), 1, False),
         ("Base de Cálculo Após Exclusões e Reduções", _dinheiro(x.t("IBSCBS/valores/vBC", "nfse")), 1, False),
         ("Red. Alíquota IBS / Red. Alíquota CBS", f"{_pct(x.t('pRedAliqUF', 'nfse'))} / {_pct(x.t('pRedAliqCBS', 'nfse'))}", 1, False),
         ("Alíquota - IBS UF / IBS Mun", f"{_pct(x.t('uf/pIBSUF', 'nfse'))} / {_pct(x.t('mun/pIBSMun', 'nfse'))}", 1, False)],
        [("Alíq. Efetiva Municipal - IBS", _pct(x.t("mun/pAliqEfetMun", "nfse")), 1, False),
         ("Valor Apurado Municipal - IBS", _dinheiro(x.t("gIBSMunTot/vIBSMun", "nfse")), 1, False),
         ("Alíq. Efetiva Estadual - IBS", _pct(x.t("uf/pAliqEfetUF", "nfse")), 1, False),
         ("Valor Apurado Estadual - IBS", _dinheiro(x.t("gIBSUFTot/vIBSUF", "nfse")), 1, False)],
        [("Valor Total Apurado - IBS", _dinheiro(x.t("gIBS/vIBSTot", "nfse")), 1, False),
         ("Alíquota - CBS", _pct(x.t("fed/pCBS", "nfse")), 1, False),
         ("Alíquota Efetiva - CBS", _pct(x.t("fed/pAliqEfetCBS", "nfse")), 1, False),
         ("Valor Total Apurado - CBS", _dinheiro(x.t("gCBS/vCBS", "nfse")), 1, False)],
    ], titulo="TRIBUTAÇÃO IBS / CBS")

    # ---------- valor total
    v_ibs, v_cbs = x.t("gIBS/vIBSTot", "nfse"), x.t("gCBS/vCBS", "nfse")
    tot_ibscbs = None
    if v_ibs or v_cbs:
        tot_ibscbs = str(Decimal(v_ibs or "0") + Decimal(v_cbs or "0"))
    v_serv = x.t("vServPrest/vServ", "dps") or (f"{nota.valor_centavos / 100:.2f}" if getattr(nota, "valor_centavos", None) else None)
    f.bloco([
        [("Valor da Operação / Serviço", _dinheiro(v_serv), 1, False),
         ("Desconto Incondicionado", _dinheiro(x.t("vDescCondIncond/vDescIncond", "dps")), 1, False),
         ("Desconto Condicionado", _dinheiro(x.t("vDescCondIncond/vDescCond", "dps")), 1, False)],
        [("Total das Retenções (ISSQN / Federais)", _dinheiro(x.t("valores/vTotalRet", "nfse")), 1, False),
         ("Valor Líquido da NFS-e", _dinheiro(x.t("valores/vLiq", "nfse") or v_serv), 1, False),
         ("Total do IBS/CBS", _dinheiro(tot_ibscbs), 1, False),
         ("Valor Líquido da NFS-e + IBS/CBS", _dinheiro(x.t("totCIBS/vTotNF", "nfse")), 1, True)],
    ], titulo="VALOR TOTAL DA NFS-e")

    # ---------- informações complementares (até o fim da página)
    f.linha_h(f.y)
    c.setFillColor(CINZA_5)
    alt_tit = 0.42 * cm
    c.rect(f.x0, f.y - alt_tit, larg, alt_tit, stroke=0, fill=1)
    c.setFillColor(black)
    c.setFont(FONTE_N, 7)
    c.drawString(f.x0 + f.pad, f.y - alt_tit + 0.13 * cm, "INFORMAÇÕES COMPLEMENTARES")
    f.y -= alt_tit
    f.linha_h(f.y)
    info = []
    inf_comp = x.t("infoCompl/xInfComp", "dps")
    if inf_comp:
        info.append("Inf. Cont.: " + inf_comp)
    sub = x.t("subst/chSubstda", "dps")
    if sub:
        info.append("NFS-e Subst.: " + sub)
    for tag, rotulo in (("docRef", "Doc. Ref."), ("xPed", "Núm. Ped."), ("xItemPed", "Item Ped."), ("xOutInf", "Inf. A. T. Mun.")):
        v = x.t(tag, "dps")
        if v:
            info.append(f"{rotulo}: {v}")
    texto = _corta(" | ".join(info), 1997) if info else ""
    corpo = escape(texto) + ("<br/>" if texto else "") + escape(_totais_tributos(x))
    p = Paragraph(corpo, ParagraphStyle("info", fontName=FONTE, fontSize=7, leading=8.6, alignment=TA_LEFT))
    _, h = p.wrap(larg - 2 * f.pad, 10_000)
    p.drawOn(c, f.x0 + f.pad, f.y - f.pad - h)

    # ---------- borda da página (1 pt)
    c.setLineWidth(1)
    base = 0.30 * cm
    c.rect(f.x0, base, larg, f_topo(f) - base, stroke=1, fill=0)

    # ---------- marca d'água
    if getattr(nota, "situacao", "") == "cancelada":
        _marca(c, "CANCELADA")

    c.showPage()
    c.save()
    return buf.getvalue()


def f_topo(f: _Folha) -> float:
    return f.alt_pag - 0.30 * cm


def _marca(c: Canvas, texto: str):
    c.saveState()
    c.setFillColor(CINZA_MARCA)
    c.setFont(FONTE, 96)
    c.translate(A4[0] / 2, A4[1] / 2)
    c.rotate(45)
    c.drawCentredString(0, -30, texto)
    c.restoreState()
