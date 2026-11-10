"""Testes da API HTTP. Precisam de fastapi e httpx (requirements.txt)."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.api import criar_app  # noqa: E402
from app.autenticacao import ServicoAutenticacao  # noqa: E402

from .conftest import CNPJ_PRESTADOR, CNPJ_TOMADOR  # noqa: E402

SENHA = "Cafe-com-Pao-2026"
CODIGO = "codigo-de-instalacao-teste"
CSRF = {"X-Emitta": "1"}


@pytest.fixture
def auth(servico):
    return ServicoAutenticacao(servico.repo, codigo_instalacao=CODIGO)


@pytest.fixture
def app(servico, auth):
    return criar_app(servico, auth=auth, cookie_seguro=False)


def novo_cliente(app):
    return TestClient(app, headers=CSRF)


@pytest.fixture
def anonimo(app):
    return novo_cliente(app)


@pytest.fixture
def contador(app):
    c = novo_cliente(app)
    resp = c.post("/auth/instalacao", json={"codigo": CODIGO, "nome": "Ana", "email": "ana@escritorio.com", "senha": SENHA})
    assert resp.status_code == 200, resp.text
    return c


def criar_empresa(c, cnpj="11.222.333/0001-81"):
    resp = c.post("/contador/clientes", json={
        "cnpj": cnpj, "razao_social": "Minha Empresa ME",
        "municipio_ibge": "3550308", "municipio_nome": "São Paulo",
        "aliquota_iss": "3", "prazo_cancelamento_dias": 30,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def entrar_como_empresa(app, contador, cid, email="bia@empresa.com"):
    provisoria = contador.post(f"/contador/clientes/{cid}/acessos", json={"nome": "Bia", "email": email}).json()["senha_provisoria"]
    c = novo_cliente(app)
    assert c.post("/auth/entrar", json={"email": email, "senha": provisoria}).status_code == 200
    # primeiro acesso: só pode trocar a senha
    resp = c.get(f"/app/{cid}/servicos")
    assert resp.status_code == 403 and resp.json()["detail"]["codigo"] == "trocar_senha"
    assert c.post("/auth/senha", json={"atual": provisoria, "nova": "Nova-Senha-Da-Bia-9"}).status_code == 200
    return c


# ---------------------------------------------------------------- público

def test_status_e_paginas_publicas(anonimo):
    assert anonimo.get("/status").json()["ambiente"] == "simulacao"
    for caminho, trecho in [("/", "Sou contador"), ("/entrar", "entrar.js"), ("/escritorio", "painel.js"),
                            ("/empresa", "app.js"), ("/static/estilo.css", "--verde")]:
        resp = anonimo.get(caminho)
        assert resp.status_code == 200 and trecho in resp.text, caminho
        if not caminho.startswith("/static"):
            assert resp.headers["cache-control"] == "no-store", caminho
    assert anonimo.get("/painel", follow_redirects=False).headers["location"] == "/escritorio"
    assert anonimo.get("/app?empresa=2", follow_redirects=False).headers["location"] == "/empresa?empresa=2"


def test_cabecalhos_de_seguranca(anonimo):
    resp = anonimo.get("/")
    assert "frame-ancestors 'none'" in resp.headers["content-security-policy"]
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["x-content-type-options"] == "nosniff"


# ---------------------------------------------------------------- bloqueios

@pytest.mark.parametrize("metodo, caminho", [
    ("get", "/contador/clientes"), ("get", "/catalogo/servicos"), ("get", "/app/1/servicos"), ("get", "/auth/eu"),
])
def test_sem_login_nao_entra(anonimo, metodo, caminho):
    assert getattr(anonimo, metodo)(caminho).status_code == 401


def test_csrf_sem_cabecalho_bloqueia(app, contador):
    sem_cabecalho = TestClient(app)
    sem_cabecalho.cookies = contador.cookies
    resp = sem_cabecalho.post("/contador/clientes", json={})
    assert resp.status_code == 403
    assert "X-Emitta" in resp.json()["detail"]


def test_instalacao_exige_codigo_e_so_uma_vez(anonimo, contador):
    resp = anonimo.post("/auth/instalacao", json={"codigo": CODIGO, "nome": "X", "email": "x@x.com", "senha": SENHA})
    assert resp.status_code == 403
    assert anonimo.get("/auth/situacao").json()["precisa_instalar"] is False


def test_cookie_de_sessao_httponly(app):
    c = novo_cliente(app)
    resp = c.post("/auth/instalacao", json={"codigo": CODIGO, "nome": "Ana", "email": "ana@x.com", "senha": SENHA})
    cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_login_errado_e_limite_por_ip(app, contador):
    c = novo_cliente(app)
    respostas = [c.post("/auth/entrar", json={"email": "ana@escritorio.com", "senha": "errada-123456"}).status_code
                 for _ in range(11)]
    assert respostas[0] == 401
    assert 429 in respostas  # limite por IP


def test_sair_encerra_a_sessao(contador):
    assert contador.get("/auth/eu").status_code == 200
    contador.post("/auth/sair")
    assert contador.get("/auth/eu").status_code == 401


# ---------------------------------------------------------------- permissões

def test_empresa_nao_ve_outra_empresa_nem_o_painel(app, contador):
    cid1 = criar_empresa(contador)
    cid2 = criar_empresa(contador, CNPJ_TOMADOR)
    empresa = entrar_como_empresa(app, contador, cid1)
    assert empresa.get(f"/app/{cid1}").status_code == 200
    assert empresa.get(f"/app/{cid2}").status_code == 404
    assert empresa.get(f"/app/{cid2}/notas").status_code == 404
    assert empresa.get("/contador/clientes").status_code == 403
    assert empresa.put(f"/contador/clientes/{cid1}/servicos", json={"servicos": []}).status_code == 403


# ---------------------------------------------------------------- fluxo completo

def test_fluxo_completo(app, contador):
    cid = criar_empresa(contador)
    resp = contador.put(f"/contador/clientes/{cid}/servicos", json={
        "servicos": [{"codigo": "010101", "apelido": "Desenvolvimento de sistemas"}]
    })
    assert resp.status_code == 200

    empresa = entrar_como_empresa(app, contador, cid)
    eu = empresa.get("/auth/eu").json()
    assert eu["papel"] == "empresa" and eu["cliente_id"] == cid and not eu["trocar_senha"]
    assert empresa.get(f"/app/{cid}/servicos").json() == [{"codigo": "010101", "apelido": "Desenvolvimento de sistemas"}]

    bloqueado = empresa.post(f"/app/{cid}/notas", json={
        "codigo_servico": "170101", "tomador_documento": CNPJ_TOMADOR, "tomador_nome": "X", "valor": "100",
    })
    assert bloqueado.status_code == 403

    resp = empresa.post(f"/app/{cid}/notas", json={
        "codigo_servico": "010101", "tomador_documento": CNPJ_TOMADOR,
        "tomador_nome": "Cliente Exemplo Ltda", "valor": "1.500,00",
    })
    assert resp.status_code == 201, resp.text
    nota = resp.json()
    assert nota["situacao"] == "autorizada" and nota["iss"] == "45.00"

    resp = empresa.post(f"/app/{cid}/notas/{nota['id']}/cancelar", json={"motivo": "erro"})
    assert resp.status_code == 200 and resp.json()["situacao"] == "cancelada"

    acessos = contador.get(f"/contador/clientes/{cid}/acessos").json()
    assert acessos[0]["email"] == "bia@empresa.com" and not acessos[0]["aguardando_primeiro_acesso"]


def test_contador_nao_libera_codigo_inexistente(contador):
    cid = criar_empresa(contador)
    resp = contador.put(f"/contador/clientes/{cid}/servicos", json={"servicos": [{"codigo": "999999"}]})
    assert resp.status_code == 422


def test_empresa_duplicada(contador):
    criar_empresa(contador)
    resp = contador.post("/contador/clientes", json={
        "cnpj": CNPJ_PRESTADOR, "razao_social": "Repetida", "municipio_ibge": "3550308",
        "municipio_nome": "São Paulo", "aliquota_iss": "3",
    })
    assert resp.status_code == 409
