"""Assistente: só monta rascunhos, respeita o acesso de cada um e funciona sem chave."""

import json
from datetime import date

import pytest

from app import assistente
from app.assistente import ConfigIA, Contexto, responder

CPF = "52998224725"


def ctx_empresa(**kw):
    base = dict(
        papel="empresa", nome="Bia", ambiente="simulacao", hoje=date(2026, 11, 17),
        empresa={"razao_social": "Studio Aurora", "municipio": "São Paulo", "aliquota_iss": "2", "regime": "Simples Nacional"},
        servicos=[{"codigo": "060201", "apelido": "Limpeza de pele", "descricao": "Esteticistas"},
                  {"codigo": "060101", "apelido": "Corte e escova", "descricao": "Barbearia, cabeleireiros"}],
        notas=[{"id": 7, "numero": "000003", "cliente": "Carla", "valor": "180,00", "situacao": "autorizada", "data": "2026-11-16"},
               {"id": 8, "numero": "000004", "cliente": "Ana", "valor": "90,00", "situacao": "cancelada", "data": "2026-11-16"}],
        catalogo={"060201": {"codigo": "060201", "descricao": "Esteticistas, tratamento de pele", "palavras": ["estética"]},
                  "171901": {"codigo": "171901", "descricao": "Contabilidade", "palavras": ["contador"]}},
    )
    base.update(kw)
    return Contexto(**base)


def ia_falsa(*rodadas):
    """Devolve as respostas na ordem; cada rodada é texto ou (ferramenta, argumentos)."""
    fila = list(rodadas)
    vistos = []

    def chamar(corpo):
        vistos.append(corpo)
        item = fila.pop(0)
        if isinstance(item, tuple):
            nome, args = item
            return {"choices": [{"message": {"content": "", "tool_calls": [
                {"id": f"c{len(vistos)}", "type": "function", "function": {"name": nome, "arguments": json.dumps(args)}}]}}]}
        return {"choices": [{"message": {"content": item}}]}

    chamar.vistos = vistos
    return chamar


def falar(texto):
    return [{"de": "pessoa", "texto": texto}]


def test_sem_chave_usa_ajuda_basica():
    r = responder(ctx_empresa(), falar("como eu cancelo uma nota?"), ConfigIA(chave=None))
    assert r["modo"] == "basico" and "Cancelar esta nota" in r["resposta"]
    r = responder(ctx_empresa(), falar("quero emitir uma nota"), ConfigIA(chave=None))
    assert r["acoes"] == [{"tipo": "abrir", "dados": {"tela": "nova", "rotulo": "Abrir nova nota"}}]


def test_prepara_nota_mas_nao_emite():
    ia = ia_falsa(("preparar_nota", {"servico": "limpeza de pele", "cliente_documento": "529.982.247-25",
                                     "cliente_nome": "Carla Mendes", "valor": "R$ 180"}),
                  "Pronto! Confira a nota abaixo e toque em Emitir.")
    r = responder(ctx_empresa(), falar("faz uma nota de limpeza de pele pra Carla"), ConfigIA(chave="x"), chamar=ia)
    assert r["modo"] == "ia"
    assert r["acoes"] == [{"tipo": "nota", "dados": {
        "codigo": "060201", "servico": "Limpeza de pele", "documento": CPF, "tipo_documento": "CPF",
        "nome": "Carla Mendes", "valor": "180,00", "descricao": "Limpeza de pele"}}]
    # as instruções proíbem dizer que emitiu e as ferramentas não emitem nada
    sistema = ia.vistos[0]["messages"][0]["content"]
    assert "NUNCA emite nem cancela" in sistema
    nomes = {t["function"]["name"] for t in ia.vistos[0]["tools"]}
    assert nomes == {"buscar_servico_lista_nacional", "preparar_nota", "preparar_cancelamento"}


def test_nota_com_dados_errados_volta_erro_para_a_ia():
    ia = ia_falsa(("preparar_nota", {"servico": "pintura", "cliente_documento": CPF, "cliente_nome": "X", "valor": "10"}),
                  ("preparar_nota", {"servico": "060201", "cliente_documento": "123", "cliente_nome": "X", "valor": "10"}),
                  "Qual o CPF certo?")
    r = responder(ctx_empresa(), falar("nota"), ConfigIA(chave="x"), chamar=ia)
    assert r["acoes"] == []
    respostas = [m for m in ia.vistos[-1]["messages"] if m["role"] == "tool"]
    assert "não está liberado" in respostas[0]["content"]
    assert "inválido" in respostas[1]["content"]


def test_prepara_cancelamento_so_de_nota_autorizada():
    ia = ia_falsa(("preparar_cancelamento", {"numero_nota": "4", "motivo": "erro"}),
                  ("preparar_cancelamento", {"numero_nota": "3", "motivo": "nao_prestado"}),
                  "Confira e confirme o cancelamento.")
    r = responder(ctx_empresa(), falar("cancelar"), ConfigIA(chave="x"), chamar=ia)
    assert r["acoes"] == [{"tipo": "cancelamento", "dados": {
        "nota_id": 7, "numero": "000003", "cliente": "Carla", "valor": "180,00", "motivo": "nao_prestado", "texto_motivo": ""}}]
    primeira = [m for m in ia.vistos[-1]["messages"] if m["role"] == "tool"][0]["content"]
    assert "cancelada" in primeira


def test_contador_sem_empresa_nao_tem_ferramentas_de_nota():
    ia = ia_falsa("Use a aba Serviços.")
    responder(ctx_empresa(papel="contador", empresa=None, servicos=[], notas=[]), falar("oi"), ConfigIA(chave="x"), chamar=ia)
    assert {t["function"]["name"] for t in ia.vistos[0]["tools"]} == {"buscar_servico_lista_nacional"}


def test_busca_no_catalogo():
    c = ctx_empresa().catalogo
    assert [s["codigo"] for s in assistente.buscar_no_catalogo(c, "contador")] == ["171901"]
    assert [s["codigo"] for s in assistente.buscar_no_catalogo(c, "06.02")] == ["060201"]


def test_falha_da_ia_cai_na_ajuda_basica():
    def quebrada(corpo):
        raise RuntimeError("fora do ar")
    r = responder(ctx_empresa(), falar("como baixar o pdf"), ConfigIA(chave="x"), chamar=quebrada)
    assert r["modo"] == "basico" and "Baixar PDF" in r["resposta"]


def test_historico_e_cortado():
    longas = [{"de": "pessoa", "texto": "a" * 5000}] * 30
    h = assistente._limpar_historico(longas)
    assert len(h) == assistente.MAX_MENSAGENS and all(len(m["content"]) <= assistente.MAX_CARACTERES for m in h)


# ---------------------------------------------------------------- pela API

pytest.importorskip("fastapi")


@pytest.fixture
def ambiente_api(servico):
    from app.autenticacao import ServicoAutenticacao
    from .test_api import CODIGO, ConsultaFalsa
    from app.api import criar_app
    auth = ServicoAutenticacao(servico.repo, codigo_instalacao=CODIGO)
    return criar_app(servico, auth=auth, cookie_seguro=False, consulta_cnpj=ConsultaFalsa()), auth


def test_rota_assistente_api(ambiente_api, monkeypatch):
    from .test_api import contador_aprovado, criar_empresa, entrar_como_empresa
    monkeypatch.delenv("EMITTA_IA_CHAVE", raising=False)
    app, auth = ambiente_api
    rafa = contador_aprovado(app, auth, "Rafa", "rafa@escritorio.com")
    outro = contador_aprovado(app, auth, "Outro", "outro@escritorio.com")
    cid = criar_empresa(rafa)
    empresa = entrar_como_empresa(app, rafa, cid)

    r = empresa.post("/assistente", json={"mensagens": falar("como emitir nota?"), "cliente_id": 999})
    assert r.status_code == 200 and r.json()["modo"] == "basico"
    assert r.json()["acoes"][0]["tipo"] == "abrir"  # usou a empresa dela, não a 999

    assert rafa.post("/assistente", json={"mensagens": falar("oi"), "cliente_id": cid}).status_code == 200
    assert outro.post("/assistente", json={"mensagens": falar("oi"), "cliente_id": cid}).status_code == 404
    assert outro.post("/assistente", json={"mensagens": falar("oi")}).status_code == 200
