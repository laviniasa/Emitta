"""MEI/autônomo sem contador: cria a conta, cadastra a própria empresa e emite sozinho."""

import pytest

pytest.importorskip("fastapi")

from .test_api import SENHA, contador_aprovado, criar_empresa, novo_cliente  # noqa: E402
from .test_api import app, auth  # noqa: E402,F401  (fixtures)

CPF = "52998224725"


def autonomo_aprovado(app, auth, email="joana@mei.com"):
    c = novo_cliente(app)
    r = c.post("/auth/cadastro", json={"nome": "Joana MEI", "email": email, "senha": SENHA, "tipo": "autonomo"})
    assert r.status_code == 200 and r.json()["pendente"] is True
    assert c.post("/auth/entrar", json={"email": email, "senha": SENHA}).status_code != 200  # antes da aprovação
    auth.aprovar(auth.repo.buscar_usuario_por_email(email).id)
    r = c.post("/auth/entrar", json={"email": email, "senha": SENHA})
    assert r.status_code == 200 and r.json()["usuario"]["papel"] == "autonomo"
    return c


def test_autonomo_configura_e_emite_sozinho(app, auth):
    joana = autonomo_aprovado(app, auth)
    assert joana.get("/auth/eu").json()["cliente_id"] is None
    cid = criar_empresa(joana)
    assert joana.get("/auth/eu").json()["cliente_id"] == cid
    # só uma empresa por conta
    r = joana.post("/contador/clientes", json={"cnpj": "11.444.777/0001-61", "razao_social": "Outra", "municipio_ibge": "3550308",
                                                "municipio_nome": "São Paulo", "aliquota_iss": "2"})
    assert r.status_code == 409
    # libera o próprio serviço e emite pelo app
    assert joana.put(f"/contador/clientes/{cid}/servicos", json={"servicos": [{"codigo": "060101", "apelido": "Corte"}]}).status_code == 200
    assert [s["codigo"] for s in joana.get(f"/app/{cid}/servicos").json()] == ["060101"]
    r = joana.post(f"/app/{cid}/notas", json={"codigo_servico": "060101", "tomador_documento": CPF, "tomador_nome": "Carla",
                                              "valor": "80,00", "descricao": "Corte"})
    assert r.status_code == 201, r.text
    # não cria logins de empresa (ele mesmo é a empresa)
    r = joana.post(f"/contador/clientes/{cid}/acessos", json={"nome": "X", "email": "x@x.com"})
    assert r.status_code == 403


def test_autonomo_nao_ve_empresas_de_outros(app, auth):
    rafa = contador_aprovado(app, auth, "Rafa", "rafa@escritorio.com")
    cid_rafa = criar_empresa(rafa)
    joana = autonomo_aprovado(app, auth)
    assert joana.get("/contador/clientes").json() == []
    assert joana.get(f"/app/{cid_rafa}/notas").status_code == 404
    assert joana.get(f"/contador/clientes/{cid_rafa}/servicos").status_code == 404


def test_tipo_de_conta_invalido(app):
    c = novo_cliente(app)
    r = c.post("/auth/cadastro", json={"nome": "X", "email": "x@x.com", "senha": SENHA, "tipo": "admin"})
    assert r.status_code == 422
