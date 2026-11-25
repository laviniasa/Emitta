"""Notas recorrentes (saem sozinhas todo mês) e contato do escritório no PDF."""

from datetime import datetime

import pytest

pytest.importorskip("fastapi")

from app import recorrentes  # noqa: E402
from .test_api import (  # noqa: E402,F401
    CNPJ_TOMADOR, app, auth, contador, contador_aprovado, criar_empresa, entrar_como_empresa,
)


def no_dia(monkeypatch, ano, mes, dia):
    monkeypatch.setattr(recorrentes, "agora_brasil", lambda: datetime(ano, mes, dia, 9, 0, tzinfo=recorrentes.FUSO))


@pytest.fixture
def empresa(app, contador):
    cid = criar_empresa(contador)
    contador.put(f"/contador/clientes/{cid}/servicos", json={"servicos": [{"codigo": "010101"}]})
    return cid, entrar_como_empresa(app, contador, cid)


def nova(c, cid, **mais):
    corpo = {"codigo_servico": "010101", "tomador_documento": CNPJ_TOMADOR, "tomador_nome": "Cliente Fiel Ltda",
             "valor": "350,00", "descricao": "Mensalidade de manutenção", "dia": 5, **mais}
    return c.post(f"/app/{cid}/recorrencias", json=corpo)


def notas(c, cid):
    return c.get(f"/app/{cid}/notas").json()


def test_emite_no_dia_uma_vez_por_mes(empresa, monkeypatch):
    cid, c = empresa
    no_dia(monkeypatch, 2026, 11, 2)
    r = nova(c, cid)
    assert r.status_code == 201, r.text
    assert r.json()["proxima"] == "2026-11-05" and r.json()["ativa"]

    no_dia(monkeypatch, 2026, 11, 4)
    assert c.get(f"/app/{cid}/recorrencias").status_code == 200
    assert notas(c, cid) == []

    no_dia(monkeypatch, 2026, 11, 6)  # o servidor estava parado no dia 5: sai no dia 6
    lista = c.get(f"/app/{cid}/recorrencias").json()
    assert lista[0]["ultima_nota"]["situacao"] == "autorizada"
    assert lista[0]["proxima"] == "2026-12-05"
    feitas = notas(c, cid)
    assert len(feitas) == 1 and feitas[0]["tomador"]["nome"] == "Cliente Fiel Ltda" and feitas[0]["valor"] == "350.00"

    c.get(f"/app/{cid}/recorrencias")  # de novo no mesmo mês: não duplica
    assert len(notas(c, cid)) == 1

    no_dia(monkeypatch, 2026, 12, 5)
    c.get(f"/app/{cid}/recorrencias")
    assert len(notas(c, cid)) == 2


def test_criada_depois_do_dia_comeca_no_mes_seguinte(empresa, monkeypatch):
    cid, c = empresa
    no_dia(monkeypatch, 2026, 11, 23)
    assert nova(c, cid, dia=23).json()["proxima"] == "2026-12-23"
    c.get(f"/app/{cid}/recorrencias")
    assert notas(c, cid) == []


def test_pausar_mudar_e_apagar(empresa, monkeypatch):
    cid, c = empresa
    no_dia(monkeypatch, 2026, 11, 2)
    rid = nova(c, cid).json()["id"]
    pausada = c.patch(f"/app/{cid}/recorrencias/{rid}", json={"ativa": False}).json()
    assert pausada["ativa"] is False and pausada["proxima"] is None
    no_dia(monkeypatch, 2026, 11, 10)
    c.get(f"/app/{cid}/recorrencias")
    assert notas(c, cid) == []
    # reativada depois do dia: não emite o mês que passou
    assert c.patch(f"/app/{cid}/recorrencias/{rid}", json={"ativa": True}).json()["proxima"] == "2026-12-05"
    mudou = c.patch(f"/app/{cid}/recorrencias/{rid}", json={"valor": "400", "dia": 15}).json()
    assert mudou["valor"] == "400.00" and mudou["proxima"] == "2026-11-15"
    assert c.delete(f"/app/{cid}/recorrencias/{rid}").status_code == 204
    assert c.get(f"/app/{cid}/recorrencias").json() == []


def test_erro_fica_registrado_e_da_para_tentar_de_novo(empresa, contador, monkeypatch):
    cid, c = empresa
    no_dia(monkeypatch, 2026, 11, 2)
    rid = nova(c, cid).json()["id"]
    # o contador tira o serviço: a nota do mês falha e não tenta sozinha de novo
    contador.put(f"/contador/clientes/{cid}/servicos", json={"servicos": [{"codigo": "010201"}]})
    no_dia(monkeypatch, 2026, 11, 5)
    rec = c.get(f"/app/{cid}/recorrencias").json()[0]
    assert rec["erro"] and rec["proxima"] is None
    assert notas(c, cid) == []
    contador.put(f"/contador/clientes/{cid}/servicos", json={"servicos": [{"codigo": "010101"}]})
    depois = c.post(f"/app/{cid}/recorrencias/{rid}/tentar").json()
    assert depois["erro"] is None and depois["ultima_nota"]["situacao"] == "autorizada"
    assert len(notas(c, cid)) == 1
    assert c.post(f"/app/{cid}/recorrencias/{rid}/tentar").status_code == 409


def test_validacoes_e_isolamento(app, auth, empresa, monkeypatch):
    cid, c = empresa
    no_dia(monkeypatch, 2026, 11, 2)
    assert nova(c, cid, codigo_servico="999999").status_code == 403
    assert nova(c, cid, tomador_documento="123").status_code == 422
    assert nova(c, cid, dia=31).status_code == 422
    assert nova(c, cid, valor="0").status_code in (400, 422)
    rid = nova(c, cid).json()["id"]
    outro = contador_aprovado(app, auth, "Carlos", "carlos@outro.com")
    assert outro.get(f"/app/{cid}/recorrencias").status_code == 404
    assert outro.delete(f"/app/{cid}/recorrencias/{rid}").status_code == 404


def test_contato_do_escritorio_no_pdf(empresa, contador, monkeypatch):
    cid, c = empresa
    assert contador.get("/contador/escritorio").json() == {"nome": None, "telefone": None, "email": None}
    assert contador.put("/contador/escritorio", json={"email": "sem-arroba"}).status_code == 422
    salvo = contador.put("/contador/escritorio", json={"nome": "Contabilidade Exemplo", "telefone": "(11) 3333-4444",
                                                       "email": "contato@exemplo.com.br"}).json()
    assert salvo["nome"] == "Contabilidade Exemplo"
    assert c.get("/contador/escritorio").status_code == 403  # a empresa não mexe nisso
    nota = c.post(f"/app/{cid}/notas", json={"codigo_servico": "010101", "tomador_documento": CNPJ_TOMADOR,
                                             "tomador_nome": "Cliente", "valor": "100"}).json()
    pdf = c.get(f"/app/{cid}/notas/{nota['id']}/pdf").content
    from io import BytesIO
    try:
        from pypdf import PdfReader
    except ImportError:
        pytest.skip("pypdf indisponível")
    texto = "".join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages)
    # o PDF é o DANFSe oficial (NT 008): só o que está no XML; o contato do escritório fica no app
    assert "DANFSe v2.0" in texto and "Documento Auxiliar da NFS-e" in texto
    assert "CONTABILIDADE RESPONSÁVEL" not in texto
    assert "NFS-e SEM VALIDADE JURÍDICA" in texto  # fora da produção



def test_empresa_ve_o_contato_do_escritorio(empresa, contador):
    cid, c = empresa
    assert c.get(f"/app/{cid}/escritorio").json() == {}
    contador.put("/contador/escritorio", json={"nome": "Contabilidade Exemplo", "telefone": "(11) 98888-7777", "email": None})
    r = c.get(f"/app/{cid}/escritorio").json()
    assert r["nome"] == "Contabilidade Exemplo" and r["telefone"] == "(11) 98888-7777"
    assert c.get(f"/app/{cid + 999}/escritorio").status_code in (403, 404)


def test_proxima_data():
    hoje = datetime(2026, 12, 20, tzinfo=recorrentes.FUSO)
    assert recorrentes.proxima_data({"ativa": 1, "dia": 5, "ultimo_mes": "2026-12"}, hoje) == "2027-01-05"
    assert recorrentes.proxima_data({"ativa": 1, "dia": 25, "ultimo_mes": None}, hoje) == "2026-12-25"
    assert recorrentes.mes_inicial(20, hoje) == "2026-12" and recorrentes.mes_inicial(21, hoje) is None
