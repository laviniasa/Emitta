"""Guias de imposto: o contador envia o PDF, a empresa vê, baixa e marca como pago."""

import base64
import io
import zipfile

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


def test_notas_do_escritorio_e_zip(app, auth):  # noqa: F811
    import io
    import zipfile
    from .test_api import entrar_como_empresa as entrar
    rafa = contador_aprovado(app, auth, "Rafa", "rafa@escritorio.com")
    outro = contador_aprovado(app, auth, "Outro", "outro@escritorio.com")
    cid = criar_empresa(rafa)
    rafa.put(f"/contador/clientes/{cid}/servicos", json={"servicos": [{"codigo": "010101", "apelido": "Sistemas"}]})
    empresa = entrar(app, rafa, cid)
    for nome in ("Ana", "Bia"):
        r = empresa.post(f"/app/{cid}/notas", json={"codigo_servico": "010101", "tomador_documento": "52998224725",
                                                    "tomador_nome": nome, "valor": "100,00"})
        assert r.status_code in (200, 201), r.text
    notas = rafa.get("/contador/notas").json()
    assert len(notas) == 2 and notas[0]["empresa"] == "Minha Empresa ME"
    assert rafa.get("/contador/notas?situacao=cancelada").json() == []
    assert outro.get("/contador/notas").json() == []
    assert rafa.get("/contador/notas?mes=11-2026").status_code == 422
    r = rafa.get("/contador/notas/arquivos.zip?tipo=ambos")
    assert r.status_code == 200
    nomes = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert len(nomes) == 5 and all(n.startswith("Minha Empresa ME/") for n in nomes if not n.endswith(".csv"))
    planilha = zipfile.ZipFile(io.BytesIO(r.content)).read("planilha-notas-todas.csv").decode("utf-8-sig").splitlines()
    assert planilha[0].startswith("Empresa;CNPJ da empresa;Número") and len(planilha) == 3 and ";100,00;" in planilha[1]
    assert rafa.get("/contador/notas/planilha.csv").text.count("\n") == 3
    assert outro.get("/contador/notas/arquivos.zip").status_code == 404
    assert rafa.get("/contador/clientes").json()[0]["guias_vencidas"] == 0


def test_nota_com_ibscbs_e_informacoes_complementares(app, auth):  # noqa: F811
    from .test_api import entrar_como_empresa as entrar
    rafa = contador_aprovado(app, auth, "Rafa", "rafa@escritorio.com")
    cid = criar_empresa(rafa)
    r = rafa.put(f"/contador/clientes/{cid}/servicos", json={"servicos": [{"codigo": "060201", "apelido": "Limpeza de pele"}]})
    assert r.json()[0]["nbs"] == "126022000" and r.json()[0]["cclass_trib"] == "000001"  # sugestão do Anexo VIII
    op = rafa.get("/catalogo/171901/ibscbs").json()
    assert op["sugerido"]["cind_op"] == "100301" and any(c["codigo"] == "200052" for c in op["cclass"])
    assert rafa.put(f"/contador/clientes/{cid}/servicos", json={"servicos": [
        {"codigo": "060201", "nbs": "123"}]}).status_code == 422
    empresa = entrar(app, rafa, cid)
    r = empresa.post(f"/app/{cid}/notas", json={"codigo_servico": "060201", "tomador_documento": "52998224725",
                                                "tomador_nome": "Carla", "valor": "180,00",
                                                "informacoes_complementares": "Pagamento via Pix."})
    nota = r.json()
    assert nota["informacoes_complementares"].startswith("Totais aproximados dos Tributos cfe. Lei n° 12.741/2012:")
    assert nota["informacoes_complementares"].endswith(" / Pagamento via Pix.")
    assert nota["ibscbs"] is None  # tomador CPF sem endereço: grupo IBS/CBS fica de fora (E0239)
    pdf = empresa.get(nota["pdf"])
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    # tomador CNPJ: endereço vem da Receita e o grupo IBS/CBS vai na nota
    r = empresa.post(f"/app/{cid}/notas", json={"codigo_servico": "060201", "tomador_documento": "11444777000161",
                                                "tomador_nome": "Empresa Consultada", "valor": "300,00"})
    nota = r.json()
    assert r.status_code == 201, nota
    assert nota["ibscbs"] == {"nbs": "126022000", "cind_op": "030101", "cclass_trib": "000001"}
    assert empresa.get(nota["pdf"]).status_code == 200


def test_servicos_sugeridos_pelo_cnae_da_empresa(app, auth):  # noqa: F811
    rafa = contador_aprovado(app, auth, "Rafa", "rafa@escritorio.com")
    cid = rafa.post("/contador/clientes", json={"cnpj": "11444777000161", "razao_social": "Empresa Consultada",
                                                "municipio_ibge": "3550308", "municipio_nome": "São Paulo",
                                                "aliquota_iss": "2"}).json()["id"]
    r = rafa.get(f"/contador/clientes/{cid}/servicos/sugeridos").json()
    assert [c["codigo"] for c in r["cnaes"]] == ["6201501", "9602502"]
    assert "010101" in r["cnaes"][0]["servicos"] and "060201" in r["cnaes"][1]["servicos"]


def test_resumo_do_ano_e_limite_do_mei(app, auth):  # noqa: F811
    from .test_api import entrar_como_empresa as entrar
    rafa = contador_aprovado(app, auth, "Rafa", "rafa@escritorio.com")
    r = rafa.post("/contador/clientes", json={"cnpj": "11.222.333/0001-81", "razao_social": "Bia MEI",
                                              "municipio_ibge": "3550308", "municipio_nome": "São Paulo",
                                              "aliquota_iss": "2", "opcao_simples": "2", "abertura": "2019-03-10"})
    cid = r.json()["id"]
    rafa.put(f"/contador/clientes/{cid}/servicos", json={"servicos": [{"codigo": "060201", "apelido": "Limpeza"}]})
    empresa = entrar(app, rafa, cid)
    for valor in ("40.000,00", "25.000,00"):
        assert empresa.post(f"/app/{cid}/notas", json={"codigo_servico": "060201", "tomador_documento": "52998224725",
                                                      "tomador_nome": "Ana", "valor": valor}).status_code == 201
    r = empresa.get(f"/app/{cid}/resumo-ano").json()
    assert r["total_centavos"] == 6_500_000 and r["notas"] == 2
    assert r["mei"]["usado_pct"] == 80 and r["mei"]["nivel"] == "atencao" and r["mei"]["proporcional"] is False
    assert sum(m["valor_centavos"] for m in r["meses"]) == 6_500_000 and len(r["meses"]) == 12
    lista = rafa.get("/contador/clientes").json()[0]
    assert lista["faturamento_ano_centavos"] == 6_500_000 and lista["limite_mei"]["nivel"] == "atencao"
    assert rafa.get("/contador/resumo").json()["meis"] == {"total": 1, "atencao": 1, "passaram": 0}
    csv = rafa.get(f"/contador/clientes/{cid}/resumo-ano.csv").content.decode("utf-8-sig")
    assert "Total;2;65000,00" in csv and "Limite do MEI no ano;;81000,00" in csv


def test_regras_do_limite_do_mei_e_certificado():
    from datetime import date
    from app import regras
    assert regras.limite_mei(2026, "2026-09-15") == (675_000 * 4, True)  # set a dez: 4 meses
    assert regras.limite_mei(2026, "2025-01-01") == (8_100_000, False)
    assert regras.situacao_limite(9_000_000, 8_100_000)["nivel"] == "passou"
    assert regras.situacao_limite(9_800_000, 8_100_000)["nivel"] == "grave"   # mais de 20% acima
    assert regras.dias_para_vencer("2026-12-01T12:00:00+00:00", date(2026, 11, 19)) == 12
    assert regras.dias_para_vencer(None, date(2026, 11, 19)) is None


def test_notas_recebidas_do_adn(app, auth):  # noqa: F811
    rafa = contador_aprovado(app, auth, "Rafa", "rafa@escritorio.com")
    cid = criar_empresa(rafa, "27.384.956/0001-90")
    r = rafa.post(f"/contador/clientes/{cid}/recebidas/buscar")
    assert r.status_code == 200, r.text
    assert r.json()["novas"] == 3 and r.json()["canceladas"] == 1
    assert rafa.post(f"/contador/clientes/{cid}/recebidas/buscar").json()["novas"] == 0  # continua do último NSU
    lista = rafa.get(f"/contador/clientes/{cid}/recebidas").json()
    assert [n["emitente_nome"] for n in lista["notas"]][0] == "LIMPA BEM SERVICOS LTDA"
    assert lista["notas"][0]["situacao"] == "cancelada" and lista["total_centavos"] == 18_990 + 120_000
    x = rafa.get(lista["notas"][1]["xml"])
    assert x.status_code == 200 and b"<nNFSe>102</nNFSe>" in x.content
    z = rafa.get(f"/contador/clientes/{cid}/recebidas/arquivos.zip?mes=2026-11")
    assert z.status_code == 200 and len(zipfile.ZipFile(io.BytesIO(z.content)).namelist()) == 3
    outro = contador_aprovado(app, auth, "Outro", "outro@escritorio.com")
    assert outro.get(f"/contador/clientes/{cid}/recebidas").status_code in (403, 404)
