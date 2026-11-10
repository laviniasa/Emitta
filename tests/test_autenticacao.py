from datetime import datetime, timedelta, timezone

import pytest

from app import seguranca as seg
from app.autenticacao import (
    MSG_BLOQUEADO,
    MSG_LOGIN_INVALIDO,
    AcessoNegado,
    ErroAutenticacao,
    ServicoAutenticacao,
)
from app.repositorio import Repositorio

SENHA = "Cafe-com-Pao-2026"


class Relogio:
    def __init__(self):
        self.agora = datetime(2026, 11, 10, 13, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.agora

    def avancar(self, **kw):
        self.agora += timedelta(**kw)


@pytest.fixture
def relogio():
    return Relogio()


@pytest.fixture
def auth(relogio):
    return ServicoAutenticacao(Repositorio(":memory:"), relogio=relogio, codigo_instalacao="codigo-secreto-123")


@pytest.fixture
def contador(auth):
    return auth.instalar("codigo-secreto-123", "Ana Contadora", "Ana@Escritorio.com.br", SENHA)


# ---------------------------------------------------------------- senhas

def test_hash_de_senha_nao_guarda_a_senha():
    h = seg.hash_senha(SENHA)
    assert SENHA not in h
    assert h != seg.hash_senha(SENHA)  # sal diferente a cada vez
    assert seg.verificar_senha(SENHA, h)
    assert not seg.verificar_senha(SENHA + "x", h)
    assert not seg.verificar_senha(SENHA, "lixo")


@pytest.mark.parametrize("senha", ["curta", "1234567890", "aaaaaaaaaaaa", "ana.silva-123456"])
def test_senhas_fracas(senha):
    assert seg.problema_na_senha(senha, "ana.silva@x.com")


def test_totp_aceita_codigo_certo_e_recusa_reuso():
    segredo = seg.gerar_segredo_totp()
    agora = 1_800_000_000
    passo = seg.passo_atual(agora)
    codigo = seg._codigo_totp(segredo, passo)
    assert seg.conferir_totp(segredo, codigo, None, agora) == passo
    assert seg.conferir_totp(segredo, codigo, passo, agora) is None  # já usado
    assert seg.conferir_totp(segredo, "000000" if codigo != "000000" else "111111", None, agora) is None
    # 30 s de diferença de relógio é tolerado
    assert seg.conferir_totp(segredo, codigo, None, agora + 30) == passo


def test_totp_compativel_com_rfc6238():
    # Vetor de teste oficial (RFC 6238, SHA-1, T=59): 94287082 -> 6 dígitos 287082
    segredo = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # "12345678901234567890"
    assert seg._codigo_totp(segredo, 59 // 30) == "287082"


def test_limitador():
    lim = seg.LimitadorTentativas(limite=3, janela=60)
    assert all(lim.permitir("ip", agora=t) for t in (0, 1, 2))
    assert not lim.permitir("ip", agora=3)
    assert lim.permitir("ip", agora=70)
    assert lim.permitir("outro-ip", agora=3)


# ---------------------------------------------------------------- instalação

def test_instalacao_exige_codigo(auth):
    with pytest.raises(AcessoNegado):
        auth.instalar("errado", "Ana", "ana@x.com", SENHA)
    assert auth.precisa_instalar()


def test_instalacao_so_uma_vez(auth, contador):
    assert not auth.precisa_instalar()
    with pytest.raises(AcessoNegado):
        auth.instalar("codigo-secreto-123", "Intrusa", "intrusa@x.com", SENHA)


def test_instalacao_desativada_sem_codigo_no_servidor(relogio):
    auth = ServicoAutenticacao(Repositorio(":memory:"), relogio=relogio, codigo_instalacao="")
    with pytest.raises(AcessoNegado):
        auth.instalar("", "Ana", "ana@x.com", SENHA)


# ---------------------------------------------------------------- login

def test_login_e_sessao(auth, contador):
    r = auth.entrar("ana@escritorio.com.br", SENHA)  # e-mail sem diferenciar maiúsculas
    assert r.token_sessao and not r.desafio_2fa
    assert auth.usuario_da_sessao(r.token_sessao).id == contador.id
    # o token não fica salvo em texto puro
    assert auth.repo.buscar_sessao(r.token_sessao) is None
    auth.sair(r.token_sessao)
    assert auth.usuario_da_sessao(r.token_sessao) is None


def test_mensagem_igual_para_email_inexistente(auth, contador):
    for email, senha in [("naoexiste@x.com", SENHA), ("ana@escritorio.com.br", "senha-errada-123")]:
        with pytest.raises(ErroAutenticacao) as e:
            auth.entrar(email, senha)
        assert str(e.value) == MSG_LOGIN_INVALIDO


def test_bloqueio_apos_5_erros(auth, contador, relogio):
    for _ in range(4):
        with pytest.raises(ErroAutenticacao, match="incorretos"):
            auth.entrar("ana@escritorio.com.br", "errada-errada")
    with pytest.raises(ErroAutenticacao) as e:
        auth.entrar("ana@escritorio.com.br", "errada-errada")
    assert str(e.value) == MSG_BLOQUEADO
    # nem a senha certa entra durante o bloqueio
    with pytest.raises(ErroAutenticacao, match="aguarde"):
        auth.entrar("ana@escritorio.com.br", SENHA)
    relogio.avancar(minutes=16)
    assert auth.entrar("ana@escritorio.com.br", SENHA).token_sessao


def test_sessao_expira_por_inatividade_e_por_tempo(auth, contador, relogio):
    token = auth.entrar("ana@escritorio.com.br", SENHA).token_sessao
    relogio.avancar(hours=1, minutes=59)
    assert auth.usuario_da_sessao(token)
    relogio.avancar(hours=2, minutes=1)
    assert auth.usuario_da_sessao(token) is None

    token = auth.entrar("ana@escritorio.com.br", SENHA).token_sessao
    for _ in range(7):  # usando sempre, mas passa de 12 h
        relogio.avancar(hours=1, minutes=50)
        auth.usuario_da_sessao(token)
    assert auth.usuario_da_sessao(token) is None


def test_trocar_senha_encerra_outras_sessoes(auth, contador):
    t1 = auth.entrar("ana@escritorio.com.br", SENHA).token_sessao
    t2 = auth.entrar("ana@escritorio.com.br", SENHA).token_sessao
    usuario = auth.usuario_da_sessao(t1)
    with pytest.raises(ErroAutenticacao, match="atual"):
        auth.trocar_senha(usuario, "errada", "Outra-Senha-Forte-9", t1)
    auth.trocar_senha(usuario, SENHA, "Outra-Senha-Forte-9", t1)
    assert auth.usuario_da_sessao(t1)
    assert auth.usuario_da_sessao(t2) is None
    assert auth.entrar("ana@escritorio.com.br", "Outra-Senha-Forte-9").token_sessao


# ---------------------------------------------------------------- 2FA

def test_fluxo_2fa(auth, contador, relogio):
    segredo, uri = auth.iniciar_2fa(contador)
    assert uri.startswith("otpauth://totp/Emitta")
    passo = seg.passo_atual(relogio().timestamp())
    with pytest.raises(ErroAutenticacao):
        auth.ativar_2fa(auth.repo.buscar_usuario(contador.id), "123456" if seg._codigo_totp(segredo, passo) != "123456" else "654321")
    auth.ativar_2fa(auth.repo.buscar_usuario(contador.id), seg._codigo_totp(segredo, passo))

    relogio.avancar(seconds=60)
    r = auth.entrar("ana@escritorio.com.br", SENHA)
    assert r.token_sessao is None and r.desafio_2fa  # senha sozinha não basta
    with pytest.raises(ErroAutenticacao, match="incorreto"):
        auth.confirmar_2fa(r.desafio_2fa, "000000" if seg._codigo_totp(segredo, passo + 2) != "000000" else "111111")
    codigo = seg._codigo_totp(segredo, seg.passo_atual(relogio().timestamp()))
    ok = auth.confirmar_2fa(r.desafio_2fa, codigo)
    assert auth.usuario_da_sessao(ok.token_sessao).id == contador.id
    # o mesmo desafio não serve duas vezes
    with pytest.raises(ErroAutenticacao):
        auth.confirmar_2fa(r.desafio_2fa, codigo)


def test_desafio_2fa_expira_e_limita_tentativas(auth, contador, relogio):
    segredo, _ = auth.iniciar_2fa(contador)
    auth.ativar_2fa(auth.repo.buscar_usuario(contador.id), seg._codigo_totp(segredo, seg.passo_atual(relogio().timestamp())))
    relogio.avancar(seconds=60)
    desafio = auth.entrar("ana@escritorio.com.br", SENHA).desafio_2fa
    for _ in range(5):
        with pytest.raises(ErroAutenticacao):
            auth.confirmar_2fa(desafio, "000000")
    with pytest.raises(ErroAutenticacao):
        auth.confirmar_2fa(desafio, seg._codigo_totp(segredo, seg.passo_atual(relogio().timestamp())))

    desafio = auth.entrar("ana@escritorio.com.br", SENHA).desafio_2fa
    relogio.avancar(minutes=6)
    with pytest.raises(ErroAutenticacao, match="tempo"):
        auth.confirmar_2fa(desafio, seg._codigo_totp(segredo, seg.passo_atual(relogio().timestamp())))


# ---------------------------------------------------------------- acesso da empresa

def test_acesso_da_empresa_com_senha_provisoria(auth, contador):
    cliente = auth.repo.criar_cliente(cnpj="11222333000181", razao_social="Salão ME", municipio_ibge="3550308",
                                      municipio_nome="SP", aliquota_iss="2")
    usuario, provisoria = auth.criar_acesso_empresa(cliente.id, "Bia", "bia@salao.com")
    assert usuario.papel == "empresa" and usuario.trocar_senha
    r = auth.entrar("bia@salao.com", provisoria)
    assert auth.usuario_da_sessao(r.token_sessao).cliente_id == cliente.id

    # redefinir gera senha nova e derruba as sessões antigas
    _, nova = auth.criar_acesso_empresa(cliente.id, "Bia", "bia@salao.com")
    assert nova != provisoria
    assert auth.usuario_da_sessao(r.token_sessao) is None

    # não dá para "sequestrar" o e-mail do contador
    with pytest.raises(ErroAutenticacao):
        auth.criar_acesso_empresa(cliente.id, "X", "ana@escritorio.com.br")


@pytest.mark.parametrize("entrada, esperado", [
    ("mailto:Contato@MarvixBrasil.com.br", "contato@marvixbrasil.com.br"),
    ("  ana@escritorio.com ", "ana@escritorio.com"),
])
def test_email_colado_como_link(entrada, esperado):
    from app.autenticacao import normalizar_email
    assert normalizar_email(entrada) == esperado


@pytest.mark.parametrize("ruim", ["ana", "ana@", "ana@x", "a b@x.com", "ana@x.c", "mailto:"])
def test_email_invalido(ruim):
    from app.autenticacao import normalizar_email
    with pytest.raises(ErroAutenticacao):
        normalizar_email(ruim)
