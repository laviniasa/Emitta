"""PDF da nota para baixar e enviar ao cliente.

É uma representação simplificada da NFS-e com os dados principais e a chave
de acesso (a nota oficial pode sempre ser consultada pela chave no portal
nacional). Fora da produção, o PDF leva a marca "SEM VALOR FISCAL".
"""

from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .catalogo import carregar_catalogo
from .regras import centavos_para_texto

VERDE = colors.HexColor("#0E7C66")
NOITE = colors.HexColor("#0F2A24")
CINZA = colors.HexColor("#4B5563")
BORDA = colors.HexColor("#D1D5DB")
FUNDO = colors.HexColor("#F3F4F6")

_E = {
    "titulo": ParagraphStyle("titulo", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=NOITE),
    "sub": ParagraphStyle("sub", fontName="Helvetica", fontSize=9, leading=12, textColor=CINZA),
    "rotulo": ParagraphStyle("rotulo", fontName="Helvetica", fontSize=7.5, leading=10, textColor=CINZA),
    "valor": ParagraphStyle("valor", fontName="Helvetica", fontSize=10, leading=13),
    "forte": ParagraphStyle("forte", fontName="Helvetica-Bold", fontSize=10, leading=13),
    "secao": ParagraphStyle("secao", fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=VERDE),
    "chave": ParagraphStyle("chave", fontName="Courier", fontSize=9, leading=12, alignment=TA_CENTER),
    "total": ParagraphStyle("total", fontName="Helvetica-Bold", fontSize=13, leading=16, alignment=TA_RIGHT),
    "rodape": ParagraphStyle("rodape", fontName="Helvetica", fontSize=7.5, leading=10, textColor=CINZA, alignment=TA_CENTER),
}


def _dinheiro(centavos: int) -> str:
    inteiro, dec = centavos_para_texto(centavos).split(".")
    return "R$ " + f"{int(inteiro):,}".replace(",", ".") + "," + dec


def _doc(numero: str, tipo: str) -> str:
    if tipo == "CPF" and len(numero) == 11:
        return f"{numero[:3]}.{numero[3:6]}.{numero[6:9]}-{numero[9:]}"
    if len(numero) == 14:
        return f"{numero[:2]}.{numero[2:5]}.{numero[5:8]}/{numero[8:12]}-{numero[12:]}"
    return numero


def _campo(rotulo: str, valor: str, estilo: str = "valor") -> list:
    return [Paragraph(escape(rotulo), _E["rotulo"]), Paragraph(escape(valor or "-"), _E[estilo])]


def _bloco(titulo: str, linhas: list[list], larguras: list[float]) -> list:
    tabela = Table(linhas, colWidths=larguras)
    tabela.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDA),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return [Paragraph(titulo, _E["secao"]), Spacer(1, 2), tabela, Spacer(1, 8)]


def gerar_pdf(nota, cliente, ambiente: str) -> bytes:
    buffer = BytesIO()
    largura = A4[0] - 30 * mm
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm,
                            title=f"NFS-e {nota.numero_dps:06d} - {cliente.razao_social}", author="Emitta")
    sem_valor = ambiente != "producao"
    cancelada = nota.situacao == "cancelada"

    emitida = datetime.fromisoformat(nota.emitida_em)
    competencia = date.fromisoformat(nota.competencia) if nota.competencia else emitida.date()
    servico = carregar_catalogo().get(nota.codigo_servico, {})

    partes = [
        Table([[
            [Paragraph("NFS-e · Nota Fiscal de Serviço eletrônica", _E["titulo"]),
             Paragraph("Representação simplificada · padrão nacional", _E["sub"])],
            [Paragraph(f"Nº {nota.numero_dps:06d}", ParagraphStyle("n", parent=_E["titulo"], alignment=TA_RIGHT)),
             Paragraph(f"Emitida em {emitida:%d/%m/%Y %H:%M}", ParagraphStyle("d", parent=_E["sub"], alignment=TA_RIGHT))],
        ]], colWidths=[largura * 0.65, largura * 0.35]),
        Spacer(1, 8),
    ]

    avisos = []
    if sem_valor:
        avisos.append("AMBIENTE DE TESTE · SEM VALOR FISCAL")
    if cancelada:
        avisos.append("NOTA CANCELADA")
    if nota.situacao == "rejeitada":
        avisos.append("NOTA RECUSADA PELA PREFEITURA · NÃO EMITIDA")
    if avisos:
        aviso = Table([[Paragraph(" · ".join(avisos), ParagraphStyle(
            "aviso", fontName="Helvetica-Bold", fontSize=11, alignment=TA_CENTER, textColor=colors.HexColor("#B42318")))]],
            colWidths=[largura])
        aviso.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#B42318")),
                                   ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FEE4E2")),
                                   ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        partes += [aviso, Spacer(1, 8)]

    meia = largura / 2
    partes += _bloco("PRESTADOR DO SERVIÇO", [
        [_campo("Razão social", cliente.razao_social, "forte"), _campo("CNPJ", _doc(cliente.cnpj, "CNPJ"))],
        [_campo("Município", cliente.municipio_nome), _campo("Regime", {"1": "Não optante do Simples", "2": "MEI", "3": "Simples Nacional (ME/EPP)"}.get(cliente.opcao_simples, ""))],
    ], [meia, meia])
    partes += _bloco("TOMADOR DO SERVIÇO", [
        [_campo("Nome / razão social", nota.tomador_nome, "forte"), _campo(nota.tomador_tipo, _doc(nota.tomador_documento, nota.tomador_tipo))],
    ], [meia, meia])
    partes += _bloco("SERVIÇO", [
        [_campo("Código de tributação nacional", f"{servico.get('subitem', '')} ({nota.codigo_servico})"),
         _campo("Competência", f"{competencia:%d/%m/%Y}")],
        [_campo("Serviço", servico.get("descricao", "")), _campo("Local da prestação", cliente.municipio_nome)],
        [_campo("Descrição", nota.descricao), ""],
    ], [meia, meia])

    linhas_valores = [
        [Paragraph("Valor do serviço", _E["valor"]), Paragraph(_dinheiro(nota.valor_centavos), ParagraphStyle("v", parent=_E["valor"], alignment=TA_RIGHT))],
        [Paragraph(f"ISS ({cliente.aliquota_iss.replace('.', ',')}%)" + (" · retido pelo tomador" if nota.iss_retido else ""), _E["valor"]),
         Paragraph(_dinheiro(nota.iss_centavos), ParagraphStyle("v2", parent=_E["valor"], alignment=TA_RIGHT))],
        [Paragraph("Valor líquido", _E["forte"]),
         Paragraph(_dinheiro(nota.valor_centavos - (nota.iss_centavos if nota.iss_retido else 0)), _E["total"])],
    ]
    partes += _bloco("VALORES", linhas_valores, [largura * 0.7, largura * 0.3])

    if nota.chave_acesso:
        caixa = Table([[Paragraph("Chave de acesso", _E["rotulo"])], [Paragraph(nota.chave_acesso, _E["chave"])],
                       [Paragraph("Consulte a autenticidade pela chave de acesso no portal nacional da NFS-e (www.nfse.gov.br).", _E["rodape"])]],
                      colWidths=[largura])
        caixa.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), FUNDO), ("BOX", (0, 0), (-1, -1), 0.6, BORDA),
                                   ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        partes += [caixa, Spacer(1, 8)]

    if cancelada and nota.motivo_cancelamento:
        partes.append(Paragraph(escape(f"Cancelada em {datetime.fromisoformat(nota.cancelada_em):%d/%m/%Y %H:%M}. "
                                       f"Motivo: {nota.motivo_cancelamento}."), _E["sub"]))
        partes.append(Spacer(1, 6))

    partes.append(Paragraph("Gerado pelo Emitta", _E["rodape"]))

    def marca_dagua(canvas, _doc):
        if not (sem_valor or cancelada):
            return
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#B42318"))
        canvas.setFillAlpha(0.08)
        canvas.setFont("Helvetica-Bold", 54)
        canvas.translate(A4[0] / 2, A4[1] / 2)
        canvas.rotate(35)
        canvas.drawCentredString(0, 0, "CANCELADA" if cancelada else "SEM VALOR FISCAL")
        canvas.restoreState()

    doc.build(partes, onFirstPage=marca_dagua, onLaterPages=marca_dagua)
    return buffer.getvalue()
