"""Facilidades para liberar serviços: importar de XML de notas antigas e "mais usados no escritório"."""

import base64

import pytest

pytest.importorskip("fastapi")

from .test_api import app, auth, contador, contador_aprovado, criar_empresa  # noqa: E402,F401

NACIONAL = """<?xml version="1.0" encoding="UTF-8"?>
<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse"><infNFSe Id="NFS35503082211222333000181000000000000126110000000001"><nNFSe>1</nNFSe>
<DPS><infDPS><dhEmi>2026-03-10T10:00:00-03:00</dhEmi><dCompet>2026-03-10</dCompet>
<prest><CNPJ>11222333000181</CNPJ></prest>
<toma><CNPJ>11444777000161</CNPJ><xNome>Padaria Pão Quente ME</xNome></toma>
<serv><cServ><cTribNac>140101</cTribNac><xDescServ>Revisão do carro do cliente</xDescServ></cServ></serv>
<valores><vServPrest><vServ>350.00</vServ></vServPrest><trib><tribMun><pAliq>2.00</pAliq></tribMun></trib></valores>
</infDPS></DPS></infNFSe></NFSe>"""


def abrasf_lote(cnpj_prestador="11222333000181"):
    notas = "".join(f"""<CompNfse><Nfse><InfNfse><Numero>{n}</Numero><DataEmissao>2026-{m:02d}-05T09:00:00</DataEmissao>
<Servico><Valores><ValorServicos>1200.00</ValorServicos><Aliquota>0.02</Aliquota></Valores><ItemListaServico>17.19</ItemListaServico>
<Discriminacao>Honorários contábeis</Discriminacao></Servico>
<PrestadorServico><IdentificacaoPrestador><CpfCnpj><Cnpj>{cnpj_prestador}</Cnpj></CpfCnpj></IdentificacaoPrestador></PrestadorServico>
<TomadorServico><IdentificacaoTomador><CpfCnpj><Cnpj>27384956000190</Cnpj></CpfCnpj></IdentificacaoTomador><RazaoSocial>Clínica Sorriso Leve</RazaoSocial></TomadorServico>
</InfNfse></Nfse></CompNfse>""" for n, m in [(10, 4), (11, 5), (12, 6)])
    return f'<?xml version="1.0"?><ListaNfse>{notas}</ListaNfse>'


ABRASF = """<?xml version="1.0"?>
<CompNfse><Nfse><InfNfse><Servico><ItemListaServico>17.19</ItemListaServico>
<Discriminacao>Honorários contábeis de outubro</Discriminacao></Servico>
<PrestadorServico><IdentificacaoPrestador><CpfCnpj><Cnpj>99888777000166</Cnpj></CpfCnpj></IdentificacaoPrestador></PrestadorServico>
</InfNfse></Nfse></CompNfse>"""

BOMBA = """<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>
<x><cTribNac>&b;</cTribNac></x>"""


def arq(nome, texto):
    return {"nome": nome, "conteudo_base64": base64.b64encode(texto.encode()).decode()}


def test_importa_servicos_de_xml(contador):
    cid = criar_empresa(contador)
    r = contador.post(f"/contador/clientes/{cid}/servicos/importar-xml", json={"arquivos": [
        arq("nota1.xml", NACIONAL), arq("nota2.xml", NACIONAL.replace("Revisão", "Outra revisão")), arq("municipal.xml", ABRASF), arq("lote.xml", abrasf_lote()),
        arq("ruim.xml", "isto não é xml"), arq("bomba.xml", BOMBA)]})
    assert r.status_code == 200, r.text
    d = r.json()
    cods = {s["codigo"]: s for s in d["servicos"]}
    assert cods["140101"]["notas"] == 2 and "Revisão" in cods["140101"]["exemplo"]
    assert "171901" in cods  # 17.19 do padrão ABRASF vira o código nacional
    assert any("outra empresa" in a for a in d["avisos"])
    assert any("ruim.xml" in a for a in d["avisos"])
    # nada foi liberado sozinho
    assert not any(s["liberado"] for s in contador.get(f"/contador/clientes/{cid}/servicos").json())


def test_importar_xml_so_do_dono(app, auth, contador):
    cid = criar_empresa(contador)
    outro = contador_aprovado(app, auth, "Carlos", "carlos@outro.com")
    assert outro.post(f"/contador/clientes/{cid}/servicos/importar-xml", json={"arquivos": [arq("a.xml", NACIONAL)]}).status_code == 404


def test_mais_usados_no_escritorio(app, auth, contador):
    a = criar_empresa(contador)
    b = criar_empresa(contador, cnpj="11.444.777/0001-61")
    contador.put(f"/contador/clientes/{a}/servicos", json={"servicos": [{"codigo": "140101"}, {"codigo": "171901"}]})
    contador.put(f"/contador/clientes/{b}/servicos", json={"servicos": [{"codigo": "140101"}]})
    lista = contador.get("/contador/servicos/mais-usados").json()
    assert lista[0] == {"codigo": "140101", "empresas": 2} and lista[1]["codigo"] == "171901"
    outro = contador_aprovado(app, auth, "Carlos", "carlos@outro.com")
    assert outro.get("/contador/servicos/mais-usados").json() == []


def test_importacao_completa_clientes_faturamento_aliquota_e_automatica(app, auth, contador):
    from .test_api import entrar_como_empresa
    cid = criar_empresa(contador)  # ISS cadastrado: 3%
    contador.put(f"/contador/clientes/{cid}/servicos", json={"servicos": [{"codigo": "140101"}, {"codigo": "171901"}]})
    r = contador.post(f"/contador/clientes/{cid}/servicos/importar-xml",
                      json={"arquivos": [arq("nacional.xml", NACIONAL), arq("lote.xml", abrasf_lote())]}).json()
    assert r["lidos"] == 4  # 1 nacional + 3 do lote
    assert r["faturamento"]["total_centavos"] == 35000 + 3 * 120000
    assert r["aliquota"] == {"nas_notas": "2.00", "no_emitta": "3.00"}
    auto = r["automaticas"][0]
    assert auto["documento"] == "27384956000190" and auto["meses"] == 3 and auto["dia"] == 5 and auto["codigo_servico"] == "171901"
    assert {c["documento"] for c in r["clientes"]} == {"11444777000161", "27384956000190"}

    salvo = contador.post(f"/contador/clientes/{cid}/importacao", json={"notas": r["notas"]}).json()
    assert salvo == {"novas": 4, "total": 4}
    assert contador.post(f"/contador/clientes/{cid}/importacao", json={"notas": r["notas"]}).json()["novas"] == 0  # não duplica
    ano = contador.get(f"/contador/clientes/{cid}/resumo-ano?ano=2026").json()
    assert ano["total_centavos"] >= 35000 + 360000 and ano["importadas"] == 4 and "importadas" in ano["observacao"]

    empresa = entrar_como_empresa(app, contador, cid)
    salvos = empresa.get(f"/app/{cid}/clientes-salvos").json()
    assert {c["nome"] for c in salvos} == {"Padaria Pão Quente ME", "Clínica Sorriso Leve"}
    assert next(c for c in salvos if c["nome"] == "Clínica Sorriso Leve")["valor"] == "1200.00"

    assert contador.delete(f"/contador/clientes/{cid}/importacao").status_code == 204
    assert contador.get(f"/contador/clientes/{cid}/importacao").json() == {"total": 0}
    assert empresa.get(f"/app/{cid}/clientes-salvos").json() == []


def test_lote_de_outra_empresa_e_ignorado(contador):
    cid = criar_empresa(contador)
    r = contador.post(f"/contador/clientes/{cid}/servicos/importar-xml", json={"arquivos": [arq("lote.xml", abrasf_lote("99888777000166"))]}).json()
    assert r["lidos"] == 0 and r["notas"] == [] and any("outra empresa" in a for a in r["avisos"])
