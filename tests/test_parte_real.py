"""Testes das peças para a emissão real: CNPJ alfanumérico, competência,
retenção, leiaute por regime, assinatura, nota duplicada, certificado e PDF."""

from datetime import date, datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.fernet import Fernet
from cryptography.x509.oid import NameOID
from lxml import etree

from app import regras
from app.assinatura import ErroCertificado, _c14n, assinar, verificar
from app.certificados import ProvedorCertificados, abrir_certificado, certificado_de_teste, preparar_certificado
from app.dps import DadosDPS, montar_dps
from app.emissao import NotaEmProcessamento, RejeitadaPelaPrefeitura
from app.pdf_nota import gerar_pdf

from .conftest import CNPJ_PRESTADOR, CNPJ_TOMADOR

NS = {"n": "http://www.sped.fazenda.gov.br/nfse"}
FUSO = timezone(timedelta(hours=-3))


# ---------------------------------------------------------------- CNPJ alfanumérico

def test_cnpj_alfanumerico_exemplo_oficial_da_receita():
    doc = regras.validar_documento("12.ABC.345/01DE-35")
    assert doc == regras.Documento("CNPJ", "12ABC34501DE35")
    assert regras.validar_documento("12.abc.345/01de-35").numero == "12ABC34501DE35"
    with pytest.raises(regras.DocumentoInvalido):
        regras.validar_documento("12.ABC.345/01DE-36")
    with pytest.raises(regras.DocumentoInvalido):
        regras.validar_documento("12.ABC.345/01DE-3A")  # dígitos verificadores são sempre números


# ---------------------------------------------------------------- competência e retenção

def test_competencia():
    hoje = date(2026, 11, 10)
    assert regras.validar_competencia(None, hoje) == hoje
    assert regras.validar_competencia("2026-10-15", hoje) == date(2026, 10, 15)
    with pytest.raises(regras.ErroDeNegocio, match="futuro"):
        regras.validar_competencia("2026-11-11", hoje)
    with pytest.raises(regras.ErroDeNegocio, match="antiga"):
        regras.validar_competencia("2020-01-01", hoje)


def test_retencao():
    pj = regras.Documento("CNPJ", CNPJ_TOMADOR)
    pf = regras.Documento("CPF", "52998224725")
    regras.verificar_retencao(True, pj, "3")
    with pytest.raises(regras.ErroDeNegocio, match="CPF"):
        regras.verificar_retencao(True, pf, "3")
    with pytest.raises(regras.ErroDeNegocio, match="MEI"):
        regras.verificar_retencao(True, pj, "2")


# ---------------------------------------------------------------- leiaute

def dps(**mudar):
    base = dict(
        tp_amb="2", versao_aplicativo="teste", emitida_em=datetime(2026, 11, 10, 10, 0, tzinfo=FUSO),
        serie="1", numero=1, municipio_ibge="3550308", prestador_cnpj=CNPJ_PRESTADOR,
        opcao_simples="3", tomador_tipo="CNPJ", tomador_documento=CNPJ_TOMADOR,
        tomador_nome="Cliente", codigo_servico="10101", descricao="Serviço", valor="100.00",
        aliquota_iss="2.5", p_tot_trib_sn="6.00",
    )
    base.update(mudar)
    return montar_dps(DadosDPS(**base))


def t(xml, caminho):
    return xml.findtext(caminho, namespaces=NS)


def test_versao_competencia_e_codigo():
    xml = dps(competencia=date(2026, 10, 31))
    assert xml.get("versao") == "1.01"
    assert t(xml, "n:infDPS/n:dCompet") == "2026-10-31"
    assert t(xml, "n:infDPS/n:serv/n:cServ/n:cTribNac") == "010101"  # sempre 6 dígitos


def test_tributos_aproximados_por_regime():
    me = dps(opcao_simples="3")
    assert t(me, ".//n:totTrib/n:pTotTribSN") == "6.00"
    assert t(me, ".//n:regTrib/n:regApTribSN") == "1"
    mei = dps(opcao_simples="2")
    assert t(mei, ".//n:totTrib/n:indTotTrib") == "0"
    assert mei.find(".//n:regApTribSN", NS) is None
    fora = dps(opcao_simples="1")
    assert t(fora, ".//n:totTrib/n:pTotTrib/n:pTotTribFed") == "0.00"


def test_aliquota_e_retencao_no_xml():
    assert dps(opcao_simples="3").find(".//n:pAliq", NS) is None  # ME/EPP sem retenção: não informa
    retido = dps(opcao_simples="3", iss_retido=True)
    assert t(retido, ".//n:tribMun/n:tpRetISSQN") == "2"
    assert t(retido, ".//n:tribMun/n:pAliq") == "2.50"
    assert dps(opcao_simples="2").find(".//n:pAliq", NS) is None  # MEI nunca informa
    assert t(dps(opcao_simples="1"), ".//n:tribMun/n:pAliq") == "2.50"


def test_canonicalizacao_sem_xmlns_vazio():
    """O hash precisa ser calculado sem declarações xmlns="" espúrias."""
    xml = dps()
    assinar(xml, "infDPS", certificado_de_teste())
    for el in (xml.find("n:infDPS", NS), xml.find("{http://www.w3.org/2000/09/xmldsig#}Signature/"
                                                   "{http://www.w3.org/2000/09/xmldsig#}SignedInfo")):
        assert b'xmlns=""' not in _c14n(el)
    assert verificar(etree.fromstring(etree.tostring(xml)))
    assert "rsa-sha1" in etree.tostring(xml).decode()


# ---------------------------------------------------------------- nota duplicada

def emitir(servico, cliente, **mudar):
    dados = dict(codigo_servico="010101", tomador_documento=CNPJ_TOMADOR, tomador_nome="Cliente Ltda",
                 valor="100,00", chave_envio="envio-1")
    dados.update(mudar)
    return servico.emitir(cliente.id, **dados)


def test_mesmo_envio_duas_vezes_nao_duplica(servico, cliente, sefin):
    n1 = emitir(servico, cliente)
    n2 = emitir(servico, cliente)
    assert n1.id == n2.id
    assert len(sefin.enviados) == 1
    assert len(servico.repo.listar_notas(cliente.id)) == 1


def test_resposta_perdida_fica_processando_e_se_resolve_sem_duplicar(servico, cliente, sefin):
    sefin.cair_depois_de_autorizar = True
    with pytest.raises(NotaEmProcessamento) as e:
        emitir(servico, cliente)
    nota = e.value.nota
    assert servico.repo.buscar_nota(nota.id).situacao == "processando"

    # A pessoa toca em "Emitir" de novo (mesma chave): o Emitta consulta o governo.
    resolvida = emitir(servico, cliente)
    assert resolvida.id == nota.id and resolvida.situacao == "autorizada"
    assert resolvida.chave_acesso == sefin.autorizadas[nota.id_dps]
    assert len(sefin.enviados) == 1  # nunca reenviou
    assert len(servico.repo.listar_notas(cliente.id)) == 1


def test_verificar_reenvia_mesmo_xml_se_governo_nao_recebeu(servico, cliente, sefin):
    original = sefin.enviar_dps

    def falha_antes(*a):
        from app.sefin import SemResposta
        raise SemResposta("caiu antes de chegar")
    sefin.enviar_dps = falha_antes
    with pytest.raises(NotaEmProcessamento) as e:
        emitir(servico, cliente)
    sefin.enviar_dps = original
    nota = servico.verificar(cliente.id, e.value.nota.id)
    assert nota.situacao == "autorizada"
    assert nota.numero_dps == e.value.nota.numero_dps  # mesmo número, nada duplicado


def test_rejeitada_com_mesma_chave_nao_reenvia(servico, cliente, sefin):
    sefin.rejeitar_com = "E0712 Código incompatível"
    with pytest.raises(RejeitadaPelaPrefeitura):
        emitir(servico, cliente)
    with pytest.raises(RejeitadaPelaPrefeitura):
        emitir(servico, cliente)
    assert len(sefin.enviados) == 1


def test_competencia_e_retencao_gravadas(servico, cliente, relogio):
    nota = emitir(servico, cliente, competencia="2026-10-20", iss_retido=True)
    assert nota.competencia == "2026-10-20" and nota.iss_retido == 1
    assert "<tpRetISSQN>2</tpRetISSQN>" in nota.xml_dps
    with pytest.raises(regras.ErroDeNegocio):
        emitir(servico, cliente, chave_envio="x2", tomador_documento="529.982.247-25", iss_retido=True)


# ---------------------------------------------------------------- certificado

def gerar_pfx(cnpj: str, senha: str, dias: int = 365) -> bytes:
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"EMPRESA TESTE LTDA:{cnpj}")])
    agora = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(nome).issuer_name(nome).public_key(chave.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(agora - timedelta(days=2))
            .not_valid_after(agora + timedelta(days=dias)).sign(chave, hashes.SHA256()))
    return pkcs12.serialize_key_and_certificates(
        b"a1", chave, cert, None, serialization.BestAvailableEncryption(senha.encode()))


CHAVE_COFRE = Fernet.generate_key().decode()


def test_certificado_guardado_criptografado():
    pfx = gerar_pfx(CNPJ_PRESTADOR, "senha-do-a1")
    dados = preparar_certificado(pfx, "senha-do-a1", CNPJ_PRESTADOR, chave=CHAVE_COFRE)
    assert pfx not in dados["pfx_cifrado"] and b"senha-do-a1" not in dados["senha_cifrada"]
    assert dados["titular"].startswith("EMPRESA TESTE")
    cert = abrir_certificado(dados["pfx_cifrado"], dados["senha_cifrada"], chave=CHAVE_COFRE)
    assert cert.vence_em > datetime.now(timezone.utc)


def test_certificado_recusas():
    pfx = gerar_pfx(CNPJ_PRESTADOR, "certa")
    with pytest.raises(ErroCertificado, match="Senha"):
        preparar_certificado(pfx, "errada", CNPJ_PRESTADOR, chave=CHAVE_COFRE)
    with pytest.raises(ErroCertificado, match="outra empresa"):
        preparar_certificado(pfx, "certa", CNPJ_TOMADOR, chave=CHAVE_COFRE)
    vencido = gerar_pfx(CNPJ_PRESTADOR, "certa", dias=-1)
    with pytest.raises(ErroCertificado, match="venceu"):
        preparar_certificado(vencido, "certa", CNPJ_PRESTADOR, chave=CHAVE_COFRE)
    with pytest.raises(ErroCertificado, match="EMITTA_CHAVE_CERTIFICADOS"):
        preparar_certificado(pfx, "certa", CNPJ_PRESTADOR, chave="")


def test_emissao_usa_o_certificado_da_empresa(servico, cliente, sefin):
    dados = preparar_certificado(gerar_pfx(CNPJ_PRESTADOR, "x" * 10), "x" * 10, CNPJ_PRESTADOR, chave=CHAVE_COFRE)
    servico.repo.guardar_certificado(cliente.id, dados["pfx_cifrado"], dados["senha_cifrada"], dados["validade"], dados["titular"])
    servico.certificados = ProvedorCertificados(permitir_teste=False, chave=CHAVE_COFRE)
    emitir(servico, cliente)
    assinado = etree.fromstring(sefin.enviados[-1])
    assert verificar(assinado)
    assert "EMPRESA TESTE" in str(x509.load_der_x509_certificate(__import__("base64").b64decode(
        assinado.findtext(".//{http://www.w3.org/2000/09/xmldsig#}X509Certificate"))).subject)


def test_sem_certificado_fora_da_simulacao(servico, cliente):
    servico.certificados = ProvedorCertificados(permitir_teste=False, chave=CHAVE_COFRE)
    with pytest.raises(ErroCertificado, match="não cadastrado"):
        emitir(servico, cliente)


# ---------------------------------------------------------------- PDF

def test_pdf(servico, cliente):
    nota = emitir(servico, cliente, iss_retido=True)
    pdf = gerar_pdf(nota, servico.repo.buscar_cliente(cliente.id), "simulacao")
    assert pdf.startswith(b"%PDF") and len(pdf) > 2000
    cancelada = servico.cancelar(cliente.id, nota.id, "erro")
    assert gerar_pdf(cancelada, servico.repo.buscar_cliente(cliente.id), "producao").startswith(b"%PDF")
