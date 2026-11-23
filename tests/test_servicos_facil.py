"""Facilidades para liberar serviços: importar de XML de notas antigas e "mais usados no escritório"."""

import base64

import pytest

pytest.importorskip("fastapi")

from .test_api import app, auth, contador, contador_aprovado, criar_empresa  # noqa: E402,F401

NACIONAL = """<?xml version="1.0" encoding="UTF-8"?>
<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse"><infNFSe><DPS><infDPS>
<prest><CNPJ>11222333000181</CNPJ></prest>
<serv><cServ><cTribNac>140101</cTribNac><xDescServ>Revisão do carro do cliente</xDescServ></cServ></serv>
</infDPS></DPS></infNFSe></NFSe>"""

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
        arq("nota1.xml", NACIONAL), arq("nota2.xml", NACIONAL), arq("municipal.xml", ABRASF),
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
