"""Guias de imposto: o contador envia o PDF, a empresa vê, baixa e marca como pago."""

import base64

import pytest

pytest.importorskip("fastapi")

from .test_api import app, auth, contador_aprovado, criar_empresa, entrar_como_empresa  # noqa: F401

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def guia(**kw):
    base = {"tipo": "darf", "competencia": "2026-10", "valor": "350,00", "vencimento": "2026-11-20",
            "arquivo_nome": "darf-outubro.pdf", "arquivo_base64": base64.b64encode(PDF).decode()}
    base.update(kw)
    return base


def test_contador_envia_e_empresa_paga(app, auth):  # noqa: F811
    rafa = contador_aprovado(app, auth, "Rafa", "rafa@escritorio.com")
    cid = criar_empresa(rafa)
    r = rafa.post(f"/contador/clientes/{cid}/documentos", json=guia())
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["titulo"] == "DARF de outubro/2026" and doc["valor"] == "350,00" and doc["visto_em"] is None

    empresa = entrar_como_empresa(app, rafa, cid)
    lista = empresa.get(f"/app/{cid}/documentos").json()
    assert [d["id"] for d in lista] == [doc["id"]]
    r = empresa.get(lista[0]["arquivo"])
    assert r.status_code == 200 and r.content == PDF and r.headers["content-type"] == "application/pdf"

    r = empresa.post(f"/app/{cid}/documentos/{doc['id']}/pago", json={"pago": True})
    assert r.json()["situacao"] == "pago"
    visto = rafa.get(f"/contador/clientes/{cid}/documentos").json()[0]
    assert visto["visto_em"] and visto["pago_em"]

    # contador baixando não marca como visto pelo cliente (já estava), e pode apagar
    assert rafa.delete(f"/contador/clientes/{cid}/documentos/{doc['id']}").status_code == 204
    assert empresa.get(f"/app/{cid}/documentos").json() == []


def test_regras_do_envio(app, auth):  # noqa: F811
    rafa = contador_aprovado(app, auth, "Rafa", "rafa@escritorio.com")
    outro = contador_aprovado(app, auth, "Outro", "outro@escritorio.com")
    cid = criar_empresa(rafa)
    url = f"/contador/clientes/{cid}/documentos"
    assert rafa.post(url, json=guia(arquivo_base64=base64.b64encode(b"nao e pdf").decode())).status_code == 422
    assert rafa.post(url, json=guia(valor="abc")).status_code == 422
    assert rafa.post(url, json=guia(vencimento="20/11/2026")).status_code == 422
    assert outro.post(url, json=guia()).status_code == 404
    doc = rafa.post(url, json=guia(tipo="das", titulo="", competencia=None, valor=None)).json()
    assert doc["titulo"] == "DAS" and doc["valor"] is None
    # outra empresa não vê
    cid2 = criar_empresa(rafa, cnpj="11.444.777/0001-61")
    empresa2 = entrar_como_empresa(app, rafa, cid2, email="ze@outra.com")
    assert empresa2.get(f"/app/{cid}/documentos").status_code == 404
    assert empresa2.get(f"/app/{cid2}/documentos/{doc['id']}/arquivo").status_code == 404


def test_resumo_do_escritorio(app, auth):  # noqa: F811
    rafa = contador_aprovado(app, auth, "Rafa", "rafa@escritorio.com")
    outro = contador_aprovado(app, auth, "Outro", "outro@escritorio.com")
    cid = criar_empresa(rafa)
    rafa.post(f"/contador/clientes/{cid}/documentos", json=guia(vencimento="2020-01-10"))
    rafa.post(f"/contador/clientes/{cid}/documentos", json=guia(vencimento="2099-01-10"))
    r = rafa.get("/contador/resumo").json()
    assert r["guias"] == {"pendentes": 2, "vencidas": 1, "enviadas": 2}
    assert r["empresas"]["total"] == 1 and len(r["serie"]) == 14
    assert outro.get("/contador/resumo").json()["guias"]["enviadas"] == 0
