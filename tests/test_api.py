"""Testes da API HTTP. Precisam de fastapi e httpx (requirements.txt)."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.api import criar_app  # noqa: E402

from .conftest import CNPJ_PRESTADOR, CNPJ_TOMADOR  # noqa: E402


@pytest.fixture
def api(servico):
    return TestClient(criar_app(servico))


def criar_empresa(api):
    resp = api.post("/contador/clientes", json={
        "cnpj": "11.222.333/0001-81", "razao_social": "Minha Empresa ME",
        "municipio_ibge": "3550308", "municipio_nome": "São Paulo",
        "aliquota_iss": "3", "prazo_cancelamento_dias": 30,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_fluxo_completo(api):
    cid = criar_empresa(api)

    # contador libera só um serviço
    resp = api.put(f"/contador/clientes/{cid}/servicos", json={
        "servicos": [{"codigo": "010101", "apelido": "Desenvolvimento de sistemas"}]
    })
    assert resp.status_code == 200
    assert api.get(f"/app/{cid}/servicos").json() == [
        {"codigo": "010101", "apelido": "Desenvolvimento de sistemas"}
    ]

    # cliente emite
    resp = api.post(f"/app/{cid}/notas", json={
        "codigo_servico": "010101", "tomador_documento": CNPJ_TOMADOR,
        "tomador_nome": "Cliente Exemplo Ltda", "valor": "1.500,00",
    })
    assert resp.status_code == 201, resp.text
    nota = resp.json()
    assert nota["situacao"] == "autorizada"
    assert nota["iss"] == "45.00"

    # e cancela
    resp = api.post(f"/app/{cid}/notas/{nota['id']}/cancelar", json={"motivo": "erro"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["situacao"] == "cancelada"


def test_servico_bloqueado_retorna_403(api):
    cid = criar_empresa(api)
    api.put(f"/contador/clientes/{cid}/servicos", json={"servicos": [{"codigo": "010101"}]})
    resp = api.post(f"/app/{cid}/notas", json={
        "codigo_servico": "170101", "tomador_documento": CNPJ_TOMADOR,
        "tomador_nome": "X", "valor": "100",
    })
    assert resp.status_code == 403
    assert "contador" in resp.json()["detail"]


def test_contador_nao_libera_codigo_inexistente(api):
    cid = criar_empresa(api)
    resp = api.put(f"/contador/clientes/{cid}/servicos", json={"servicos": [{"codigo": "999999"}]})
    assert resp.status_code == 422


def test_empresa_duplicada(api):
    criar_empresa(api)
    resp = api.post("/contador/clientes", json={
        "cnpj": CNPJ_PRESTADOR, "razao_social": "Repetida", "municipio_ibge": "3550308",
        "municipio_nome": "São Paulo", "aliquota_iss": "3",
    })
    assert resp.status_code == 409
