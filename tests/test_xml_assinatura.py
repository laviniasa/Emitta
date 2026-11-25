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


def test_ibscbs_e_informacoes_complementares_passam_no_xsd():
    """Reforma Tributária: NBS, IBSCBS (cIndOp, CST, cClassTrib) e infoCompl seguem o XSD oficial."""
    from datetime import datetime, timedelta, timezone
    from pathlib import Path

    from app import dps
    from app.assinatura import assinar
    from app.catalogo import ibscbs_sugerido
    from app.certificados import certificado_de_teste

    sug = ibscbs_sugerido("060201")
    from app import regras
    END = {"cmun": "3550308", "cep": "01310100", "logradouro": "Avenida Paulista", "numero": "1000",
           "complemento": "Conj. 12", "bairro": "Bela Vista"}
    INFO = regras.info_complementar_com_tributos(regras.texto_tributos(1080, 0, 360), "Pagamento via Pix. Pedido 123.")
    assert sug == {"nbs": "126022000", "cind_op": "030101", "cclass_trib": "000001"}
    N = "{http://www.sped.fazenda.gov.br/nfse}"
    for opcao, tipo, doc in (("1", "CNPJ", "11444777000161"), ("3", "CPF", "52998224725"), ("2", "CPF", "52998224725")):
        d = dps.DadosDPS(tp_amb="2", versao_aplicativo="Emitta-0.1",
                         emitida_em=datetime(2026, 11, 18, 14, 0, tzinfo=timezone(timedelta(hours=-3))),
                         serie="1", numero=7, municipio_ibge="3550308", prestador_cnpj="27384956000190",
                         opcao_simples=opcao, tomador_tipo=tipo, tomador_documento=doc, tomador_nome="Carla",
                         codigo_servico="060201", descricao="Limpeza de pele", valor="180.00", aliquota_iss="2",
                         info_compl=INFO, tomador_end=END, **sug)
        xml = dps.montar_dps(d)
        assinar(xml, "infDPS", certificado_de_teste())
        assert dps.validar_xsd(xml, Path(__file__).parent.parent / "app" / "xsd" / "DPS_v1.01.xsd") == []
        assert xml.find(f".//{N}cNBS").text == "126022000"
        assert xml.find(f".//{N}IBSCBS/{N}cIndOp").text == "030101"
        assert xml.find(f".//{N}IBSCBS/{N}indFinal").text == ("1" if tipo == "CPF" else "0")
        assert xml.find(f".//{N}trib/{N}CST").text == "000"
        assert xml.find(f".//{N}xInfComp").text == INFO


def test_texto_livre_e_ajustado_ao_leiaute():
    from datetime import datetime, timedelta, timezone
    from pathlib import Path

    from app import dps
    from app.assinatura import assinar
    from app.certificados import certificado_de_teste

    assert dps.texto_leiaute("  Linha 1\nLinha 2  ", " / ") == "Linha 1 / Linha 2"
    assert dps.texto_leiaute("Ótimo “serviço” – feito ✅") == 'Ótimo "serviço" - feito'
    d = dps.DadosDPS(tp_amb="2", versao_aplicativo="Emitta-0.1",
                     emitida_em=datetime(2026, 11, 18, 14, 0, tzinfo=timezone(timedelta(hours=-3))),
                     serie="1", numero=1, municipio_ibge="3550308", prestador_cnpj="27384956000190",
                     opcao_simples="3", tomador_tipo="CPF", tomador_documento="52998224725",
                     tomador_nome="Carla 💅", codigo_servico="060201", descricao="Limpeza\nde pele ✨", valor="1.00",
                     info_compl="Pix\nobrigada 😊")
    xml = dps.montar_dps(d)
    assinar(xml, "infDPS", certificado_de_teste())
    assert dps.validar_xsd(xml, Path(__file__).parent.parent / "app" / "xsd" / "DPS_v1.01.xsd") == []


def test_sem_endereco_do_tomador_o_grupo_ibscbs_nao_vai():
    """E0239: com IBS/CBS, o tomador precisa de endereço nacional. Sem endereço, o grupo
    (opcional em 2026) fica de fora e a nota passa."""
    from pathlib import Path
    from app import dps
    from app.catalogo import ibscbs_sugerido
    N = "{http://www.sped.fazenda.gov.br/nfse}"
    base = dict(tp_amb="2", versao_aplicativo="Emitta-0.1",
                emitida_em=datetime(2026, 11, 18, 14, 0, tzinfo=timezone(timedelta(hours=-3))),
                serie="1", numero=8, municipio_ibge="3550308", prestador_cnpj="27384956000190",
                opcao_simples="3", tomador_tipo="CPF", tomador_documento="52998224725", tomador_nome="Carla",
                codigo_servico="060201", descricao="Limpeza de pele", valor="180.00", aliquota_iss="2",
                **ibscbs_sugerido("060201"))
    xml = dps.montar_dps(dps.DadosDPS(**base))
    assert xml.find(f".//{N}IBSCBS") is None and xml.find(f".//{N}toma/{N}end") is None
    assert xml.find(f".//{N}cNBS").text == "126022000"
    xml = dps.montar_dps(dps.DadosDPS(**base, tomador_end={"cmun": "3550308", "cep": "01310100", "logradouro": "Av. Paulista", "numero": "", "bairro": ""}))
    assinar(xml, "infDPS", certificado_de_teste())
    assert dps.validar_xsd(xml, Path(__file__).parent.parent / "app" / "xsd" / "DPS_v1.01.xsd") == []
    assert xml.find(f".//{N}toma/{N}end/{N}endNac/{N}CEP").text == "01310100"
    assert xml.find(f".//{N}toma/{N}end/{N}nro").text == "S/N"
    assert xml.find(f".//{N}IBSCBS") is not None


def test_leiaute_nt004_na_producao_ate_30_11(monkeypatch):
    """Produção do governo usa a NT 004 até 30/11/2026: sem finNFSe e sem grupo IBS/CBS;
    cancelamento com nPedRegEvento e Id de 62 caracteres."""
    from datetime import date as _date
    from app import config as cfg
    from app.dps import DadosCancelamento, DadosDPS, montar_dps, montar_pedido_cancelamento
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td

    class Hoje(_dt):
        dia = _dt(2026, 11, 25, 12, 0, tzinfo=_tz(_td(hours=-3)))
        @classmethod
        def now(cls, tz=None):
            return cls.dia
    monkeypatch.setattr(cfg, "datetime", Hoje)
    monkeypatch.delenv("NFSE_LEIAUTE", raising=False)
    base = dict(banco=None, pasta_certificados=None, pasta_xsd=None)
    assert cfg.Config(ambiente="producao", **base).leiaute == "nt004"
    assert cfg.Config(ambiente="homologacao", **base).leiaute == "nt009"
    Hoje.dia = _dt(2026, 12, 1, 0, 1, tzinfo=_tz(_td(hours=-3)))
    assert cfg.Config(ambiente="producao", **base).leiaute == "nt009"
    monkeypatch.setenv("NFSE_LEIAUTE", "nt004")
    assert cfg.Config(ambiente="producao", **base).leiaute == "nt004"

    comum = dict(tp_amb="1", versao_aplicativo="t", emitida_em=_dt(2026, 11, 25, 10, tzinfo=_tz(_td(hours=-3))),
                 serie="1", numero=7, municipio_ibge="3550308", prestador_cnpj="11222333000181", opcao_simples="2",
                 tomador_tipo="CNPJ", tomador_documento="11444777000161", tomador_nome="Cliente", codigo_servico="010101",
                 descricao="Serviço", valor="100.00", nbs="114052000")
    antigo = montar_dps(DadosDPS(**comum, leiaute="nt004"))
    novo = montar_dps(DadosDPS(**comum, leiaute="nt009"))
    ns = {"n": "http://www.sped.fazenda.gov.br/nfse"}
    assert not antigo.xpath("//n:finNFSe", namespaces=ns) and novo.xpath("//n:finNFSe", namespaces=ns)
    ordem = lambda x: [etree.QName(e).localname for e in x.find(".//n:cServ", ns)]
    assert ordem(antigo) == ["cTribNac", "xDescServ", "cNBS"] and ordem(novo) == ["cTribNac", "cNBS", "xDescServ"]

    # a nota antiga passa no XSD oficial da produção (app/xsd/nt004); a nova, não
    from pathlib import Path as _P
    from app.dps import validar_xsd
    xsd = _P(__file__).parent.parent / "app" / "xsd" / "nt004" / "DPS_v1.01.xsd"
    cert = certificado_de_teste()
    assinar(antigo, "infDPS", cert); assinar(novo, "infDPS", cert)
    assert validar_xsd(antigo, xsd) == []
    assert validar_xsd(novo, xsd) != []
