from datetime import datetime, timedelta, timezone

from lxml import etree

from app.assinatura import assinar, verificar
from app.certificados import certificado_de_teste
from app.dps import DadosCancelamento, DadosDPS, id_dps, montar_dps, montar_pedido_cancelamento

FUSO = timezone(timedelta(hours=-3))
NS = {"n": "http://www.sped.fazenda.gov.br/nfse"}


def dados(**mudar):
    base = dict(
        tp_amb="2", versao_aplicativo="teste", emitida_em=datetime(2026, 11, 9, 13, 40, tzinfo=FUSO),
        serie="1", numero=7, municipio_ibge="3550308", prestador_cnpj="11222333000181",
        opcao_simples="3", tomador_tipo="CNPJ", tomador_documento="11444777000161",
        tomador_nome="Cliente Exemplo Ltda", codigo_servico="010101",
        descricao="Sistema sob encomenda", valor="1500.00",
    )
    base.update(mudar)
    return DadosDPS(**base)


def test_id_da_dps_tem_45_caracteres():
    ident = id_dps("3550308", "11222333000181", "1", 7)
    assert len(ident) == 45
    assert ident == "DPS355030821122233300018100001000000000000007"


def test_dps_contem_campos_principais():
    xml = montar_dps(dados())
    assert xml.findtext("n:infDPS/n:serv/n:cServ/n:cTribNac", namespaces=NS) == "010101"
    assert xml.findtext("n:infDPS/n:toma/n:CNPJ", namespaces=NS) == "11444777000161"
    assert xml.findtext("n:infDPS/n:valores/n:vServPrest/n:vServ", namespaces=NS) == "1500.00"
    assert xml.findtext("n:infDPS/n:dhEmi", namespaces=NS) == "2026-11-09T13:40:00-03:00"


def test_tomador_cpf_usa_tag_cpf():
    xml = montar_dps(dados(tomador_tipo="CPF", tomador_documento="52998224725"))
    assert xml.findtext("n:infDPS/n:toma/n:CPF", namespaces=NS) == "52998224725"


def test_assinatura_valida_e_detecta_alteracao():
    xml = montar_dps(dados())
    assinar(xml, "infDPS", certificado_de_teste())
    assert verificar(xml)

    # Mudar o valor depois de assinar precisa invalidar a assinatura.
    xml.find("n:infDPS/n:valores/n:vServPrest/n:vServ", NS).text = "9999.00"
    assert not verificar(xml)


def test_assinatura_sobrevive_a_ida_e_volta_em_texto():
    xml = montar_dps(dados())
    assinar(xml, "infDPS", certificado_de_teste())
    relido = etree.fromstring(etree.tostring(xml))
    assert verificar(relido)


def test_pedido_de_cancelamento_assinado():
    chave = "1" * 50
    xml = montar_pedido_cancelamento(DadosCancelamento(
        tp_amb="2", versao_aplicativo="teste", quando=datetime(2026, 11, 9, tzinfo=FUSO),
        autor_cnpj="11222333000181", chave_acesso=chave, codigo_motivo="1", texto_motivo="Erro na emissão",
    ))
    assert xml.find("n:infPedReg", NS).get("Id") == f"PRE{chave}101101"
    assert xml.findtext("n:infPedReg/n:e101101/n:cMotivo", namespaces=NS) == "1"
    assinar(xml, "infPedReg", certificado_de_teste())
    assert verificar(xml)


def test_dps_segue_xsd_oficial_v101():
    """A DPS assinada passa no XSD oficial 1.01 (com finNFSe), que vai junto do app."""
    from datetime import datetime, timedelta, timezone
    from pathlib import Path

    from app import dps
    from app.assinatura import assinar
    from app.certificados import certificado_de_teste

    xsd = Path(__file__).parent.parent / "app" / "xsd" / "DPS_v1.01.xsd"
    agora = datetime(2026, 11, 14, 14, 0, tzinfo=timezone(timedelta(hours=-3)))
    for opcao in ("1", "2", "3"):
        d = dps.DadosDPS(tp_amb="2", versao_aplicativo="Emitta-0.1", emitida_em=agora, serie="1", numero=1,
                         municipio_ibge="3550308", prestador_cnpj="27384956000190", opcao_simples=opcao,
                         tomador_tipo="CPF", tomador_documento="52998224725", tomador_nome="Carla Mendes",
                         codigo_servico="060201", descricao="Limpeza de pele", valor="1.00", aliquota_iss="2")
        xml = dps.montar_dps(d)
        assinar(xml, "infDPS", certificado_de_teste())
        assert dps.validar_xsd(xml, xsd) == []
        assert xml.find(".//{http://www.sped.fazenda.gov.br/nfse}finNFSe").text == "0"


def test_codigo_municipal_vai_no_xml_e_passa_no_xsd():
    from datetime import datetime, timedelta, timezone
    from pathlib import Path

    from app import dps
    from app.assinatura import assinar
    from app.certificados import certificado_de_teste

    d = dps.DadosDPS(tp_amb="2", versao_aplicativo="Emitta-0.1",
                     emitida_em=datetime(2026, 11, 14, 14, 0, tzinfo=timezone(timedelta(hours=-3))),
                     serie="1", numero=1, municipio_ibge="3304557", prestador_cnpj="27384956000190",
                     opcao_simples="3", tomador_tipo="CPF", tomador_documento="52998224725",
                     tomador_nome="Carla", codigo_servico="010401", descricao="Sistema", valor="1.00",
                     codigo_municipal="003")
    xml = dps.montar_dps(d)
    assinar(xml, "infDPS", certificado_de_teste())
    assert xml.find(".//{http://www.sped.fazenda.gov.br/nfse}cTribMun").text == "003"
    assert dps.validar_xsd(xml, Path(__file__).parent.parent / "app" / "xsd" / "DPS_v1.01.xsd") == []
