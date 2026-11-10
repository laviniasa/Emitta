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


class ConsultaFalsa:
    def consultar(self, cnpj):
        from app.consulta_cnpj import CnpjNaoEncontrado
        if cnpj != "11444777000161":
            raise CnpjNaoEncontrado("CNPJ não encontrado na Receita.")
        return {"razao_social": "EMPRESA CONSULTADA LTDA", "nome_fantasia": "", "municipio": "São Paulo",
                "uf": "SP", "codigo_municipio_ibge": "3550308", "situacao": "ATIVA",
                "cnae_principal": {"codigo": "6201501", "descricao": "Desenvolvimento"}, "regime": "3"}


@pytest.fixture
def app(servico, auth):
    return criar_app(servico, auth=auth, cookie_seguro=False, consulta_cnpj=ConsultaFalsa())


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
    assert anonimo.get("/entrar").headers["clear-site-data"] == '"cache"'
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
    assert resp.json()["detail"]["codigo"] == "pagina_desatualizada"


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


# ---------------------------------------------------------------- parte real

def emitir_via_api(c, cid, **mudar):
    corpo = {"codigo_servico": "010101", "tomador_documento": CNPJ_TOMADOR,
             "tomador_nome": "Cliente Ltda", "valor": "100,00", "chave_envio": "abc-1"}
    corpo.update(mudar)
    return c.post(f"/app/{cid}/notas", json=corpo)


def test_baixar_pdf_e_xml(app, contador):
    cid = criar_empresa(contador)
    contador.put(f"/contador/clientes/{cid}/servicos", json={"servicos": [{"codigo": "010101"}]})
    nota = emitir_via_api(contador, cid, competencia="2026-10-01").json()
    pdf = contador.get(nota["pdf"])
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert "attachment" in pdf.headers["content-disposition"]
    xml = contador.get(nota["xml"])
    assert xml.status_code == 200 and b"<dCompet>2026-10-01</dCompet>" in xml.content

    # outra empresa não baixa
    cid2 = criar_empresa(contador, "12.345.678/0001-95")
    empresa2 = entrar_como_empresa(app, contador, cid2, "outra@empresa.com")
    assert empresa2.get(nota["pdf"]).status_code == 404
    assert empresa2.get(f"/app/{cid2}/notas/{nota['id']}/pdf").status_code == 404


def test_envio_repetido_devolve_a_mesma_nota(contador):
    cid = criar_empresa(contador)
    contador.put(f"/contador/clientes/{cid}/servicos", json={"servicos": [{"codigo": "010101"}]})
    a = emitir_via_api(contador, cid).json()
    b = emitir_via_api(contador, cid).json()
    assert a["id"] == b["id"]
    assert len(contador.get(f"/app/{cid}/notas").json()) == 1


def test_resposta_perdida_e_verificar(servico, contador):
    cid = criar_empresa(contador)
    contador.put(f"/contador/clientes/{cid}/servicos", json={"servicos": [{"codigo": "010101"}]})
    servico.sefin.cair_depois_de_autorizar = True
    r = emitir_via_api(contador, cid)
    assert r.status_code == 202 and r.json()["processando"]
    nid = r.json()["nota"]["id"]
    assert contador.get(f"/app/{cid}/notas/{nid}/pdf").status_code == 409
    v = contador.post(f"/app/{cid}/notas/{nid}/verificar")
    assert v.status_code == 200 and v.json()["situacao"] == "autorizada"


def test_enviar_certificado(contador, monkeypatch):
    import base64
    from cryptography.fernet import Fernet
    from .test_parte_real import gerar_pfx
    monkeypatch.setenv("EMITTA_CHAVE_CERTIFICADOS", Fernet.generate_key().decode())
    cid = criar_empresa(contador)
    pfx = base64.b64encode(gerar_pfx(CNPJ_PRESTADOR, "senha-a1-ok")).decode()
    errado = contador.post(f"/contador/clientes/{cid}/certificado", json={"arquivo_base64": pfx, "senha": "nao"})
    assert errado.status_code == 422
    ok = contador.post(f"/contador/clientes/{cid}/certificado", json={"arquivo_base64": pfx, "senha": "senha-a1-ok"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["certificado"]["titular"].startswith("EMPRESA TESTE")
    lista = contador.get("/contador/clientes").json()
    assert "cert_pfx_cifrado" not in lista[0] and lista[0]["certificado"]  # nunca expõe o arquivo
    assert contador.delete(f"/contador/clientes/{cid}/certificado").json()["certificado"] is None


def test_consulta_cnpj(contador):
    r = contador.get("/consulta/cnpj/11.444.777/0001-61")
    assert r.status_code == 404  # barras na URL não são aceitas
    r = contador.get("/consulta/cnpj/11444777000161")
    assert r.status_code == 200, r.text
    assert r.json()["razao_social"] == "EMPRESA CONSULTADA LTDA"
    assert r.json()["codigo_municipio_ibge"] == "3550308"
    assert contador.get("/consulta/cnpj/52998224725").status_code == 422  # CPF não
