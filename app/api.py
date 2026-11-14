"""API web (FastAPI).

Rode com:  uvicorn app.api:app --reload
Documentação interativa:  http://localhost:8000/docs

Páginas:
  /                              apresentação
  /entrar                        login, primeiro acesso, troca de senha
  /escritorio                    painel do contador
  /empresa                       app da empresa

Rotas da API:
  /status                        situação do servidor (público)
  /auth/...                      login, sessão, senha, verificação em duas etapas
  /catalogo/servicos             lista nacional (contador)
  /contador/...                  painel do contador (só contador)
  /app/{cliente_id}/...          app da empresa (a empresa só acessa a própria)

Segurança:
  - sessão em cookie HttpOnly + Secure + SameSite=Strict (o JavaScript não lê);
  - toda requisição que altera dados exige o cabeçalho X-Emitta (proteção CSRF);
  - limite de tentativas de login por IP, além do bloqueio por conta;
  - cabeçalhos de segurança (CSP, HSTS, anti-iframe).
"""

import base64
import binascii
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response as RespostaBruta
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import regras
from .autenticacao import (
    AcessoNegado,
    ContaDesativada,
    ContaPendente,
    ErroAutenticacao,
    MSG_BLOQUEADO,
    DURACAO_SESSAO,
    ServicoAutenticacao,
)
from .assinatura import ErroCertificado
from .catalogo import carregar_catalogo
from .certificados import ProvedorCertificados, preparar_certificado
from .config import carregar_config
from .consulta_cnpj import CnpjNaoEncontrado, ConsultaCnpj, ConsultaIndisponivel
from .emissao import (
    ClienteNaoEncontrado,
    NotaEmProcessamento,
    NotaNaoEncontrada,
    RejeitadaPelaPrefeitura,
    ServicoEmissao,
    xml_para_download,
)
from .pdf_nota import gerar_pdf
from .repositorio import Nota, Repositorio, Usuario
from .seguranca import LimitadorTentativas
from .sefin import SefinNacional, SefinSimulada

PASTA_WEB = Path(__file__).parent / "web"
COOKIE = "emitta_sessao"
CABECALHO_CSRF = "x-emitta"
METODOS_QUE_ALTERAM = {"POST", "PUT", "PATCH", "DELETE"}
# Rotas liberadas mesmo quando a pessoa ainda precisa trocar a senha provisória.
LIBERADAS_SEM_TROCA = {"/auth/eu", "/auth/senha", "/auth/sair"}

CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src https://fonts.gstatic.com",
    "img-src 'self' data:",
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
])


# ---------------------------------------------------------------- modelos

class NovoCliente(BaseModel):
    cnpj: str
    razao_social: str
    municipio_ibge: str = Field(min_length=7, max_length=7, description="Código IBGE do município")
    municipio_nome: str
    aliquota_iss: Decimal = Field(ge=2, le=5, description="ISS: entre 2% e 5% (lei)")
    opcao_simples: Literal["1", "2", "3"] = Field("3", description="1 não optante, 2 MEI, 3 ME/EPP")
    prazo_cancelamento_dias: int | None = Field(None, ge=0, le=3650)
    p_tot_trib_sn: Decimal | None = Field(None, ge=0, le=100, description="% aproximado de tributos do Simples (ME/EPP)")
    reg_ap_trib_sn: Literal["1", "2", "3"] = "1"


class ServicoLiberado(BaseModel):
    codigo: str
    apelido: str | None = None


class ListaServicos(BaseModel):
    servicos: list[ServicoLiberado]


class NovaNota(BaseModel):
    codigo_servico: str
    tomador_documento: str
    tomador_nome: str
    valor: str = Field(examples=["1500,00"])
    descricao: str | None = Field(None, max_length=2000)
    competencia: str | None = Field(None, description="Data do serviço (AAAA-MM-DD). Padrão: hoje.")
    iss_retido: bool = False
    chave_envio: str | None = Field(None, max_length=64, description="Identificador único deste envio (evita nota duplicada)")


class PedidoCancelamento(BaseModel):
    motivo: str = Field(description="erro | nao_prestado | outro")
    texto: str | None = None


class Instalacao(BaseModel):
    codigo: str
    nome: str
    email: str
    senha: str


class Cadastro(BaseModel):
    nome: str = Field(max_length=120)
    email: str = Field(max_length=254)
    senha: str = Field(max_length=200)


class Login(BaseModel):
    email: str
    senha: str


class Codigo2FA(BaseModel):
    desafio: str
    codigo: str


class TrocaSenha(BaseModel):
    atual: str
    nova: str


class AtivarCodigo(BaseModel):
    codigo: str


class ConfirmarSenha(BaseModel):
    senha: str


class NovoAcesso(BaseModel):
    nome: str
    email: str


class EnvioCertificado(BaseModel):
    arquivo_base64: str = Field(max_length=100_000)
    senha: str = Field(max_length=200)


def usuario_json(u: Usuario) -> dict:
    return {
        "id": u.id, "nome": u.nome, "email": u.email, "papel": u.papel,
        "cliente_id": u.cliente_id, "trocar_senha": bool(u.trocar_senha), "dois_fatores": bool(u.totp_ativo),
    }


def ip_do_pedido(request: Request) -> str:
    # No Render, o proxy acrescenta o IP real no FIM do X-Forwarded-For.
    # Pegamos o último para que um valor forjado pelo navegador não conte.
    encaminhado = request.headers.get("x-forwarded-for")
    if encaminhado:
        return encaminhado.split(",")[-1].strip()
    return request.client.host if request.client else "desconhecido"


def criar_app(
    servico: ServicoEmissao | None = None,
    auth: ServicoAutenticacao | None = None,
    cookie_seguro: bool | None = None,
    consulta_cnpj: ConsultaCnpj | None = None,
) -> FastAPI:
    if servico is None:
        config = carregar_config()
        sefin = SefinSimulada() if config.ambiente == "simulacao" else SefinNacional(config.url_sefin)
        servico = ServicoEmissao(
            repo=Repositorio(config.banco),
            sefin=sefin,
            config=config,
            certificados=ProvedorCertificados(permitir_teste=config.ambiente == "simulacao"),
        )
    repo = servico.repo
    auth = auth or ServicoAutenticacao(repo)
    if cookie_seguro is None:
        cookie_seguro = os.getenv("EMITTA_COOKIE_SEGURO", "1") != "0"
    if not cookie_seguro and servico.config.ambiente != "simulacao":
        raise RuntimeError("EMITTA_COOKIE_SEGURO=0 só é permitido no modo simulação.")
    limitador = LimitadorTentativas(limite=10, janela=15 * 60)
    limitador_consultas = LimitadorTentativas(limite=30, janela=60)
    limitador_cadastros = LimitadorTentativas(limite=5, janela=60 * 60)
    consulta_cnpj = consulta_cnpj or ConsultaCnpj()

    app = FastAPI(title="Emitta", version="0.2.0")

    # ------------------------------------------------------------ proteções gerais

    @app.middleware("http")
    async def protecoes(request: Request, call_next):
        caminho = request.url.path
        if request.method in METODOS_QUE_ALTERAM and request.headers.get(CABECALHO_CSRF) != "1":
            # Sem o cabeçalho: ou é um envio forjado por outro site, ou uma aba
            # antiga do Emitta (de antes do login) ainda aberta no aparelho.
            return JSONResponse({"detail": {
                "codigo": "pagina_desatualizada",
                "mensagem": "Esta página do Emitta está desatualizada. Feche esta aba e abra "
                            "emitta.onrender.com/entrar numa aba nova.",
            }}, 403)
        resposta = await call_next(request)
        resposta.headers["X-Content-Type-Options"] = "nosniff"
        resposta.headers["Referrer-Policy"] = "same-origin"
        resposta.headers["X-Frame-Options"] = "DENY"
        resposta.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if not caminho.startswith(("/docs", "/redoc", "/openapi.json")):
            resposta.headers["Content-Security-Policy"] = CSP
        if cookie_seguro:
            resposta.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if caminho.startswith(("/auth", "/contador", "/app/", "/catalogo", "/admin", "/consulta")):
            resposta.headers["Cache-Control"] = "no-store"
        elif caminho.startswith("/static/"):
            # Sempre confere se há versão nova (evita o celular usar arquivo velho).
            resposta.headers["Cache-Control"] = "no-cache"
        return resposta

    def gravar_sessao(resposta: Response, token: str) -> None:
        resposta.set_cookie(
            COOKIE, token, max_age=int(DURACAO_SESSAO.total_seconds()), httponly=True,
            secure=cookie_seguro, samesite="strict", path="/",
        )

    def limitar(request: Request) -> None:
        if not limitador.permitir(ip_do_pedido(request)):
            raise HTTPException(429, MSG_BLOQUEADO)

    def evento(tipo: str, request: Request | None = None, usuario: Usuario | None = None,
               email: str | None = None, detalhe: str | None = None) -> None:
        """Registro de atividades (aparece na tela de administração)."""
        repo.registrar_evento(
            quando=datetime.now(timezone.utc).isoformat(timespec="seconds"), tipo=tipo,
            usuario_id=usuario.id if usuario else None,
            email=(usuario.email if usuario else email),
            papel=usuario.papel if usuario else None,
            detalhe=(detalhe or "")[:300] or None,
            ip=ip_do_pedido(request) if request else None,
        )

    def usuario_atual(request: Request) -> Usuario:
        usuario = auth.usuario_da_sessao(request.cookies.get(COOKIE))
        if usuario is None:
            raise HTTPException(401, "Sua sessão terminou. Entre de novo.")
        if usuario.trocar_senha and request.url.path not in LIBERADAS_SEM_TROCA:
            raise HTTPException(403, {"mensagem": "Troque a senha provisória para continuar.", "codigo": "trocar_senha"})
        return usuario

    def contador_atual(usuario: Usuario = Depends(usuario_atual)) -> Usuario:
        if usuario.papel != "contador":
            raise HTTPException(403, "Área exclusiva do contador.")
        return usuario

    def admin_atual(usuario: Usuario = Depends(usuario_atual)) -> Usuario:
        if usuario.papel != "admin":
            raise HTTPException(404, "Não encontrado.")
        if not usuario.totp_ativo:
            raise HTTPException(403, {"mensagem": "Ative a verificação em duas etapas para usar a administração.",
                                      "codigo": "admin_2fa"})
        return usuario

    def dono_do_cliente(cliente_id: int, usuario: Usuario = Depends(contador_atual)) -> Usuario:
        # Separação por login: o contador só acessa as empresas que ele cadastrou.
        # 404 (e não 403) para não confirmar que empresas de outros existem.
        cliente = repo.buscar_cliente(cliente_id)
        if not cliente or cliente.contador_id != usuario.id:
            raise HTTPException(404, "Empresa não encontrada.")
        return usuario

    def autorizar_empresa(cliente_id: int, usuario: Usuario = Depends(usuario_atual)) -> Usuario:
        # A empresa só enxerga a si mesma; o contador, só as empresas dele;
        # a administração não acessa dados fiscais.
        if usuario.papel == "empresa" and usuario.cliente_id == cliente_id:
            return usuario
        if usuario.papel == "contador":
            cliente = repo.buscar_cliente(cliente_id)
            if cliente and cliente.contador_id == usuario.id:
                return usuario
        raise HTTPException(404, "Empresa não encontrada.")

    def erro_auth(e: Exception) -> HTTPException:
        if isinstance(e, AcessoNegado):
            return HTTPException(403, str(e))
        return HTTPException(400, str(e))

    # ------------------------------------------------------------ páginas

    app.mount("/static", StaticFiles(directory=PASTA_WEB), name="static")

    def pagina(nome: str):
        # no-store: o navegador nunca guarda a página, então sempre pega a versão atual.
        return FileResponse(PASTA_WEB / nome, headers={"Cache-Control": "no-store"})

    @app.get("/", include_in_schema=False)
    def pagina_inicial():
        return pagina("index.html")

    @app.get("/entrar", include_in_schema=False)
    def pagina_entrar():
        resposta = pagina("entrar.html")
        # Manda o navegador apagar cópias antigas do site guardadas no aparelho
        # (versões de antes do login ficavam presas no cache de alguns celulares).
        resposta.headers["Clear-Site-Data"] = '"cache"'
        return resposta

    @app.get("/escritorio", include_in_schema=False)
    def pagina_painel():
        return pagina("painel.html")

    @app.get("/empresa", include_in_schema=False)
    def pagina_app():
        return pagina("app.html")

    # ---------------------------------------------------------- app instalável (PWA)
    @app.get("/abrir", include_in_schema=False)
    def pagina_abrir():
        # Abertura com a animação da nota; decide para onde levar cada pessoa.
        return FileResponse(PASTA_WEB / "abrir.html", headers={"Cache-Control": "no-cache"})

    @app.get("/offline", include_in_schema=False)
    def pagina_offline():
        return FileResponse(PASTA_WEB / "offline.html", headers={"Cache-Control": "no-cache"})

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifesto():
        return FileResponse(PASTA_WEB / "manifest.webmanifest", media_type="application/manifest+json",
                            headers={"Cache-Control": "no-cache"})

    @app.get("/sw.js", include_in_schema=False)
    def service_worker():
        # Servido na raiz para valer para o site todo; sempre conferido (no-cache).
        return FileResponse(PASTA_WEB / "sw.js", media_type="text/javascript",
                            headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})

    @app.get("/admin", include_in_schema=False)
    def pagina_admin():
        resposta = pagina("admin.html")
        resposta.headers["X-Robots-Tag"] = "noindex, nofollow"
        return resposta

    # Endereços antigos: redirecionam para os novos (celulares guardavam cópias velhas).
    @app.get("/painel", include_in_schema=False)
    def antigo_painel():
        return RedirectResponse("/escritorio", 307, headers={"Cache-Control": "no-store"})

    @app.get("/app", include_in_schema=False)
    def antigo_app(request: Request):
        destino = "/empresa" + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(destino, 307, headers={"Cache-Control": "no-store"})

    @app.get("/status", tags=["status"])
    def status():
        return {"app": "Emitta", "ambiente": servico.config.ambiente}

    # ------------------------------------------------------------ autenticação

    @app.get("/auth/situacao", tags=["autenticação"])
    def situacao():
        return {
            "precisa_instalar": auth.precisa_instalar(),
            "instalacao_disponivel": bool(auth.codigo_instalacao),
        }

    @app.post("/auth/instalacao", tags=["autenticação"])
    def instalar(dados: Instalacao, request: Request, response: Response):
        """Cria a conta de administração (uma vez só, com o código de instalação)."""
        limitar(request)
        try:
            usuario = auth.instalar(dados.codigo, dados.nome, dados.email, dados.senha)
            resultado = auth.entrar(usuario.email, dados.senha)
        except (ErroAutenticacao, AcessoNegado) as e:
            evento("instalacao_recusada", request, email=dados.email, detalhe=str(e))
            raise erro_auth(e)
        evento("administracao_criada", request, usuario)
        gravar_sessao(response, resultado.token_sessao)
        return {"usuario": usuario_json(usuario)}

    @app.post("/auth/cadastro", tags=["autenticação"])
    def cadastrar_contador(dados: Cadastro, request: Request, response: Response):
        """Contador cria a própria conta. Ele só enxerga as empresas que cadastrar."""
        limitar(request)
        if not limitador_cadastros.permitir(ip_do_pedido(request)):
            raise HTTPException(429, "Muitas contas criadas deste aparelho. Tente mais tarde.")
        try:
            usuario = auth.cadastrar_contador(dados.nome, dados.email, dados.senha)
        except ErroAutenticacao as e:
            raise erro_auth(e)
        # Não abre sessão: a conta só funciona depois da aprovação.
        evento("contador_pediu_acesso", request, usuario)
        return {"pendente": True, "email": usuario.email}

    @app.post("/auth/entrar", tags=["autenticação"])
    def entrar(dados: Login, request: Request, response: Response):
        limitar(request)
        try:
            resultado = auth.entrar(dados.email, dados.senha)
        except ErroAutenticacao as e:
            tipo = ("conta_desativada_tentou_entrar" if isinstance(e, ContaDesativada)
                    else "conta_pendente_tentou_entrar" if isinstance(e, ContaPendente)
                    else "bloqueio_por_tentativas" if str(e) == MSG_BLOQUEADO else "senha_errada")
            evento(tipo, request, email=(dados.email or "")[:254])
            raise HTTPException(401, str(e))
        if resultado.desafio_2fa:
            return {"precisa_2fa": True, "desafio": resultado.desafio_2fa}
        evento("entrou", request, resultado.usuario)
        gravar_sessao(response, resultado.token_sessao)
        return {"usuario": usuario_json(resultado.usuario)}

    @app.post("/auth/2fa", tags=["autenticação"])
    def confirmar_2fa(dados: Codigo2FA, request: Request, response: Response):
        limitar(request)
        try:
            resultado = auth.confirmar_2fa(dados.desafio, dados.codigo)
        except ErroAutenticacao as e:
            evento("codigo_2fa_errado", request, detalhe=str(e))
            raise HTTPException(401, str(e))
        evento("entrou", request, resultado.usuario, detalhe="com verificação em duas etapas")
        gravar_sessao(response, resultado.token_sessao)
        return {"usuario": usuario_json(resultado.usuario)}

    @app.post("/auth/sair", tags=["autenticação"])
    def sair(request: Request, response: Response):
        token = request.cookies.get(COOKIE)
        usuario = auth.usuario_da_sessao(token)
        auth.sair(token)
        if usuario:
            evento("saiu", request, usuario)
        response.delete_cookie(COOKIE, path="/", secure=cookie_seguro, httponly=True, samesite="strict")
        return {"ok": True}

    @app.get("/auth/eu", tags=["autenticação"])
    def eu(usuario: Usuario = Depends(usuario_atual)):
        return usuario_json(usuario)

    @app.post("/auth/senha", tags=["autenticação"])
    def trocar_senha(dados: TrocaSenha, request: Request, usuario: Usuario = Depends(usuario_atual)):
        limitar(request)
        try:
            atualizado = auth.trocar_senha(usuario, dados.atual, dados.nova, request.cookies.get(COOKIE))
        except ErroAutenticacao as e:
            raise erro_auth(e)
        evento("senha_trocada", request, usuario)
        return usuario_json(atualizado)

    @app.post("/auth/2fa/iniciar", tags=["autenticação"])
    def iniciar_2fa(usuario: Usuario = Depends(usuario_atual)):
        try:
            segredo, uri = auth.iniciar_2fa(usuario)
        except ErroAutenticacao as e:
            raise erro_auth(e)
        # Mostrado uma única vez, para a pessoa cadastrar no aplicativo autenticador.
        return {"segredo": segredo, "uri": uri}

    @app.post("/auth/2fa/ativar", tags=["autenticação"])
    def ativar_2fa(dados: AtivarCodigo, request: Request, usuario: Usuario = Depends(usuario_atual)):
        limitar(request)
        try:
            atualizado = auth.ativar_2fa(usuario, dados.codigo)
        except ErroAutenticacao as e:
            raise erro_auth(e)
        evento("duas_etapas_ativada", request, usuario)
        return usuario_json(atualizado)

    @app.post("/auth/2fa/desativar", tags=["autenticação"])
    def desativar_2fa(dados: ConfirmarSenha, request: Request, usuario: Usuario = Depends(usuario_atual)):
        limitar(request)
        if usuario.papel == "admin":
            raise HTTPException(403, "Na administração, a verificação em duas etapas é obrigatória.")
        try:
            atualizado = auth.desativar_2fa(usuario, dados.senha)
        except ErroAutenticacao as e:
            raise erro_auth(e)
        evento("duas_etapas_desativada", request, usuario)
        return usuario_json(atualizado)

    # ------------------------------------------------------------ administração

    PAPEIS = {"admin": "Administração", "contador": "Contador", "empresa": "Empresa"}

    @app.get("/admin/contas", tags=["administração"])
    def admin_contas(_: Usuario = Depends(admin_atual)):
        """Contas e situação de acesso. Não inclui notas nem certificados."""
        empresas = repo.contar_empresas_por_contador()
        agora = datetime.now(timezone.utc)
        contas = []
        for u in repo.listar_usuarios():
            bloqueada = bool(u["bloqueado_ate"] and datetime.fromisoformat(u["bloqueado_ate"]) > agora)
            contas.append({
                "id": u["id"], "nome": u["nome"], "email": u["email"], "papel": u["papel"],
                "papel_nome": PAPEIS.get(u["papel"], u["papel"]),
                "ativo": bool(u["ativo"]), "bloqueada": bloqueada, "dois_fatores": bool(u["totp_ativo"]),
                "aguardando_primeiro_acesso": bool(u["trocar_senha"]),
                "aguardando_aprovacao": not u["aprovado"],
                "ultimo_acesso": u["ultimo_acesso"], "criado_em": u["criado_em"],
                "empresa": u["empresa"], "contador": u["contador"],
                "empresas_cadastradas": empresas.get(u["id"], 0) if u["papel"] == "contador" else None,
            })
        return contas

    @app.get("/admin/atividades", tags=["administração"])
    def admin_atividades(usuario_id: int | None = None, limite: int = 200, _: Usuario = Depends(admin_atual)):
        return repo.listar_eventos(limite=max(1, min(limite, 1000)), usuario_id=usuario_id)

    def acao_admin(request: Request, quem: Usuario, alvo_id: int, tipo: str, fazer):
        alvo = repo.buscar_usuario(alvo_id)
        if not alvo:
            raise HTTPException(404, "Conta não encontrada.")
        try:
            resultado = fazer(alvo)
        except ErroAutenticacao as e:
            raise erro_auth(e)
        evento(tipo, request, quem, detalhe=f"conta: {alvo.email}")
        return resultado

    @app.post("/admin/contas/{usuario_id}/senha-provisoria", tags=["administração"])
    def admin_senha(usuario_id: int, request: Request, quem: Usuario = Depends(admin_atual)):
        """Gera uma senha provisória (mostrada uma vez). A pessoa troca no próximo acesso."""
        if usuario_id == quem.id:
            raise HTTPException(400, "Para a sua própria conta, use \"Trocar senha\".")
        def fazer(alvo):
            _, provisoria = auth.redefinir_senha(alvo.id)
            return {"email": alvo.email, "senha_provisoria": provisoria}
        return acao_admin(request, quem, usuario_id, "admin_gerou_senha_provisoria", fazer)

    @app.post("/admin/contas/{usuario_id}/aprovar", tags=["administração"])
    def admin_aprovar(usuario_id: int, request: Request, quem: Usuario = Depends(admin_atual)):
        return acao_admin(request, quem, usuario_id, "admin_aprovou_conta",
                          lambda alvo: {"ok": bool(auth.aprovar(alvo.id))})

    @app.post("/admin/contas/{usuario_id}/recusar", tags=["administração"])
    def admin_recusar(usuario_id: int, request: Request, quem: Usuario = Depends(admin_atual)):
        return acao_admin(request, quem, usuario_id, "admin_recusou_conta",
                          lambda alvo: {"ok": bool(auth.recusar(alvo.id))})

    @app.post("/admin/contas/{usuario_id}/desbloquear", tags=["administração"])
    def admin_desbloquear(usuario_id: int, request: Request, quem: Usuario = Depends(admin_atual)):
        return acao_admin(request, quem, usuario_id, "admin_desbloqueou",
                          lambda alvo: {"ok": bool(auth.desbloquear(alvo.id))})

    @app.post("/admin/contas/{usuario_id}/desativar", tags=["administração"])
    def admin_desativar(usuario_id: int, request: Request, quem: Usuario = Depends(admin_atual)):
        return acao_admin(request, quem, usuario_id, "admin_desativou_conta",
                          lambda alvo: {"ok": bool(auth.definir_ativo(alvo.id, False, quem))})

    @app.post("/admin/contas/{usuario_id}/reativar", tags=["administração"])
    def admin_reativar(usuario_id: int, request: Request, quem: Usuario = Depends(admin_atual)):
        return acao_admin(request, quem, usuario_id, "admin_reativou_conta",
                          lambda alvo: {"ok": bool(auth.definir_ativo(alvo.id, True, quem))})

    @app.post("/admin/contas/{usuario_id}/remover-2fa", tags=["administração"])
    def admin_remover_2fa(usuario_id: int, request: Request, quem: Usuario = Depends(admin_atual)):
        return acao_admin(request, quem, usuario_id, "admin_removeu_duas_etapas",
                          lambda alvo: {"ok": bool(auth.remover_2fa(alvo.id))})

    @app.post("/admin/contas/{usuario_id}/desconectar", tags=["administração"])
    def admin_desconectar(usuario_id: int, request: Request, quem: Usuario = Depends(admin_atual)):
        def fazer(alvo):
            auth.encerrar_sessoes(alvo.id)
            return {"ok": True}
        return acao_admin(request, quem, usuario_id, "admin_desconectou_conta", fazer)

    # ------------------------------------------------------------ utilidades

    def nota_json(n: Nota) -> dict:
        return {
            "id": n.id,
            "numero_dps": n.numero_dps,
            "situacao": n.situacao,
            "chave_acesso": n.chave_acesso,
            "servico": n.codigo_servico,
            "tomador": {"tipo": n.tomador_tipo, "documento": n.tomador_documento, "nome": n.tomador_nome},
            "descricao": n.descricao,
            "valor": regras.centavos_para_texto(n.valor_centavos),
            "iss": regras.centavos_para_texto(n.iss_centavos),
            "mensagem": n.mensagem,
            "emitida_em": n.emitida_em,
            "cancelada_em": n.cancelada_em,
            "motivo_cancelamento": n.motivo_cancelamento,
            "competencia": n.competencia,
            "iss_retido": bool(n.iss_retido),
            "pdf": f"/app/{n.cliente_id}/notas/{n.id}/pdf",
            "xml": f"/app/{n.cliente_id}/notas/{n.id}/xml",
        }

    def cliente_ou_404(cliente_id: int):
        cliente = repo.buscar_cliente(cliente_id)
        if not cliente:
            raise HTTPException(404, "Empresa não encontrada.")
        return cliente

    def traduzir_erro(erro: regras.ErroDeNegocio) -> HTTPException:
        if isinstance(erro, (ClienteNaoEncontrado, NotaNaoEncontrada)):
            return HTTPException(404, str(erro))
        if isinstance(erro, RejeitadaPelaPrefeitura):
            return HTTPException(502, {"mensagem": str(erro), "detalhes": erro.mensagens})
        if isinstance(erro, regras.ServicoNaoLiberado):
            return HTTPException(403, str(erro))
        return HTTPException(422, str(erro))

    # ------------------------------------------------------------ catálogo

    @app.get("/catalogo/servicos", tags=["catálogo"])
    def listar_catalogo(_: Usuario = Depends(contador_atual)):
        return list(carregar_catalogo().values())

    # ------------------------------------------------------------ contador

    @app.post("/contador/clientes", status_code=201, tags=["contador"])
    def criar_cliente(dados: NovoCliente, request: Request, usuario: Usuario = Depends(contador_atual)):
        cnpj = regras.limpar_documento(dados.cnpj)
        if dados.opcao_simples == "3" and dados.p_tot_trib_sn is None and servico.config.ambiente != "simulacao":
            raise HTTPException(422, "Informe o percentual aproximado de tributos do Simples Nacional.")
        try:
            doc = regras.validar_documento(cnpj)
        except regras.DocumentoInvalido:
            raise HTTPException(422, "CNPJ da empresa inválido.")
        if doc.tipo != "CNPJ":
            raise HTTPException(422, "Informe o CNPJ da empresa.")
        try:
            cliente = repo.criar_cliente(
                cnpj=cnpj,
                razao_social=dados.razao_social.strip(),
                municipio_ibge=dados.municipio_ibge,
                municipio_nome=dados.municipio_nome.strip(),
                aliquota_iss=str(dados.aliquota_iss),
                opcao_simples=dados.opcao_simples,
                prazo_cancelamento_dias=dados.prazo_cancelamento_dias,
                p_tot_trib_sn=str(dados.p_tot_trib_sn) if dados.p_tot_trib_sn is not None else None,
                reg_ap_trib_sn=dados.reg_ap_trib_sn,
                contador_id=usuario.id,
            )
        except Exception as erro:  # sqlite3.IntegrityError
            if "UNIQUE" in str(erro):
                raise HTTPException(409, "Você já cadastrou esta empresa.")
            raise
        evento("empresa_cadastrada", request, usuario, detalhe=f"{cliente.razao_social} ({cnpj})")
        return cliente.publico()

    @app.get("/contador/clientes", tags=["contador"])
    def listar_clientes(usuario: Usuario = Depends(contador_atual)):
        return [
            {**c.publico(), "servicos_liberados": len(repo.servicos_liberados(c.id))}
            for c in repo.listar_clientes(contador_id=usuario.id)
        ]

    @app.post("/contador/clientes/{cliente_id}/certificado", tags=["contador"])
    def enviar_certificado(cliente_id: int, dados: EnvioCertificado, request: Request,
                           usuario: Usuario = Depends(dono_do_cliente)):
        """Recebe o .pfx (em base64) e a senha; confere e guarda criptografado."""
        limitar(request)
        cliente = cliente_ou_404(cliente_id)
        try:
            pfx = base64.b64decode(dados.arquivo_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(422, "Arquivo inválido. Envie o .pfx do certificado A1.")
        try:
            cifrado = preparar_certificado(pfx, dados.senha, cliente.cnpj)
        except ErroCertificado as e:
            raise HTTPException(422, str(e))
        atualizado = repo.guardar_certificado(
            cliente_id, cifrado["pfx_cifrado"], cifrado["senha_cifrada"], cifrado["validade"], cifrado["titular"])
        evento("certificado_enviado", request, usuario, detalhe=cliente.razao_social)
        return atualizado.publico()

    @app.delete("/contador/clientes/{cliente_id}/certificado", tags=["contador"])
    def remover_certificado(cliente_id: int, request: Request, usuario: Usuario = Depends(dono_do_cliente)):
        cliente = cliente_ou_404(cliente_id)
        evento("certificado_removido", request, usuario, detalhe=cliente.razao_social)
        return repo.remover_certificado(cliente_id).publico()

    # ------------------------------------------------------------ consulta CNPJ

    @app.get("/consulta/cnpj/{cnpj}", tags=["consulta"])
    def consultar_cnpj(cnpj: str, request: Request, usuario: Usuario = Depends(usuario_atual)):
        """Dados públicos da Receita (nome, município, atividade, regime)."""
        if not limitador_consultas.permitir(f"cnpj:{usuario.id}"):
            raise HTTPException(429, "Muitas consultas seguidas. Aguarde um minuto.")
        try:
            doc = regras.validar_documento(cnpj)
        except regras.DocumentoInvalido:
            raise HTTPException(422, "CNPJ inválido.")
        if doc.tipo != "CNPJ":
            raise HTTPException(422, "Consulta disponível só para CNPJ.")
        try:
            return {"cnpj": doc.numero, **consulta_cnpj.consultar(doc.numero)}
        except CnpjNaoEncontrado as e:
            raise HTTPException(404, str(e))
        except ConsultaIndisponivel as e:
            raise HTTPException(503, str(e))

    @app.get("/contador/clientes/{cliente_id}/servicos", tags=["contador"])
    def ver_servicos_do_cliente(cliente_id: int, _: Usuario = Depends(dono_do_cliente)):
        cliente_ou_404(cliente_id)
        liberados = {s["codigo"]: s["apelido"] for s in repo.servicos_liberados(cliente_id)}
        return [
            {**s, "liberado": s["codigo"] in liberados, "apelido": liberados.get(s["codigo"])}
            for s in carregar_catalogo().values()
        ]

    @app.put("/contador/clientes/{cliente_id}/servicos", tags=["contador"])
    def liberar_servicos(cliente_id: int, dados: ListaServicos, _: Usuario = Depends(dono_do_cliente)):
        """Define a lista COMPLETA de serviços que o cliente pode emitir."""
        cliente_ou_404(cliente_id)
        catalogo = carregar_catalogo()
        desconhecidos = [s.codigo for s in dados.servicos if s.codigo not in catalogo]
        if desconhecidos:
            raise HTTPException(422, f"Códigos fora da lista nacional: {', '.join(desconhecidos)}")
        repo.definir_servicos_liberados(
            cliente_id,
            [(s.codigo, (s.apelido or catalogo[s.codigo]["descricao"]).strip()) for s in dados.servicos],
        )
        return repo.servicos_liberados(cliente_id)

    @app.get("/contador/clientes/{cliente_id}/notas", tags=["contador"])
    def notas_do_cliente(cliente_id: int, _: Usuario = Depends(dono_do_cliente)):
        cliente_ou_404(cliente_id)
        return [nota_json(n) for n in repo.listar_notas(cliente_id)]

    @app.get("/contador/clientes/{cliente_id}/acessos", tags=["contador"])
    def acessos_da_empresa(cliente_id: int, _: Usuario = Depends(dono_do_cliente)):
        cliente_ou_404(cliente_id)
        return [
            {"id": u.id, "nome": u.nome, "email": u.email, "aguardando_primeiro_acesso": bool(u.trocar_senha)}
            for u in repo.usuarios_da_empresa(cliente_id)
        ]

    @app.post("/contador/clientes/{cliente_id}/acessos", tags=["contador"])
    def criar_acesso(cliente_id: int, dados: NovoAcesso, request: Request,
                     quem: Usuario = Depends(dono_do_cliente)):
        """Cria ou redefine o acesso da empresa. A senha provisória aparece
        uma única vez e precisa ser trocada no primeiro acesso."""
        cliente_ou_404(cliente_id)
        try:
            usuario, provisoria = auth.criar_acesso_empresa(cliente_id, dados.nome, dados.email)
        except ErroAutenticacao as e:
            raise erro_auth(e)
        evento("acesso_empresa_criado", request, quem, detalhe=f"{usuario.email} → {cliente_ou_404(cliente_id).razao_social}")
        return {"email": usuario.email, "nome": usuario.nome, "senha_provisoria": provisoria}

    # ------------------------------------------------------------ app da empresa

    @app.get("/app/{cliente_id}", tags=["app da empresa"])
    def dados_da_empresa(cliente_id: int, _: Usuario = Depends(autorizar_empresa)):
        """Nome, alíquota e prazo de cancelamento (para as telas do app)."""
        c = cliente_ou_404(cliente_id)
        return {
            "id": c.id,
            "razao_social": c.razao_social,
            "municipio_nome": c.municipio_nome,
            "aliquota_iss": c.aliquota_iss,
            "prazo_cancelamento_dias": c.prazo_cancelamento_dias,
            "opcao_simples": c.opcao_simples,
        }

    @app.get("/contador/clientes/{cliente_id}/servicos/{codigo}/prefeitura", tags=["contador"])
    def conferir_servico_na_prefeitura(cliente_id: int, codigo: str, request: Request,
                                       usuario: Usuario = Depends(dono_do_cliente)):
        """Pergunta ao governo se o município da empresa aceita este código de serviço."""
        cliente = cliente_ou_404(cliente_id)
        if codigo not in carregar_catalogo():
            raise HTTPException(404, "Serviço fora da lista nacional.")
        if not limitador_consultas.permitir(f"prefeitura:{usuario.id}"):
            raise HTTPException(429, "Muitas consultas seguidas. Aguarde um minuto.")
        try:
            cert = servico.certificados.para(cliente)
        except ErroCertificado as e:
            raise HTTPException(422, str(e))
        r = servico.sefin.consultar_servico_municipio(cliente.municipio_ibge, codigo, cert)
        return {"codigo": codigo, "municipio_ibge": cliente.municipio_ibge, "administrado": r.administrado,
                "conveniado": r.conveniado, "aliquotas": r.aliquotas, "mensagens": r.mensagens}

    @app.get("/app/{cliente_id}/servicos", tags=["app da empresa"])
    def servicos_para_emitir(cliente_id: int, _: Usuario = Depends(autorizar_empresa)):
        """Só os serviços liberados pelo contador."""
        cliente_ou_404(cliente_id)
        return repo.servicos_liberados(cliente_id)

    @app.post("/app/{cliente_id}/notas", status_code=201, tags=["app da empresa"])
    def emitir_nota(cliente_id: int, dados: NovaNota, request: Request, usuario: Usuario = Depends(autorizar_empresa)):
        try:
            nota = servico.emitir(
                cliente_id,
                codigo_servico=dados.codigo_servico,
                tomador_documento=dados.tomador_documento,
                tomador_nome=dados.tomador_nome,
                valor=dados.valor,
                descricao=dados.descricao,
                competencia=dados.competencia,
                iss_retido=dados.iss_retido,
                chave_envio=dados.chave_envio,
            )
        except NotaEmProcessamento as erro:
            return JSONResponse({"processando": True, "mensagem": str(erro), "nota": nota_json(erro.nota)}, 202)
        except regras.ErroDeNegocio as erro:
            raise traduzir_erro(erro)
        evento("nota_emitida", request, usuario, detalhe=f"nº {nota.numero_dps}, R$ {regras.centavos_para_texto(nota.valor_centavos).replace('.', ',')}")
        return nota_json(nota)

    @app.post("/app/{cliente_id}/notas/{nota_id}/verificar", tags=["app da empresa"])
    def verificar_nota(cliente_id: int, nota_id: int, _: Usuario = Depends(autorizar_empresa)):
        """Para nota que ficou "processando": confere com a prefeitura."""
        try:
            nota = servico.verificar(cliente_id, nota_id)
        except NotaEmProcessamento as erro:
            return JSONResponse({"processando": True, "mensagem": str(erro), "nota": nota_json(erro.nota)}, 202)
        except regras.ErroDeNegocio as erro:
            raise traduzir_erro(erro)
        return nota_json(nota)

    def nota_da_empresa(cliente_id: int, nota_id: int):
        nota = repo.buscar_nota(nota_id)
        if not nota or nota.cliente_id != cliente_id:
            raise HTTPException(404, "Nota não encontrada.")
        return nota

    @app.get("/app/{cliente_id}/notas/{nota_id}/pdf", tags=["app da empresa"])
    def baixar_pdf(cliente_id: int, nota_id: int, _: Usuario = Depends(autorizar_empresa)):
        nota = nota_da_empresa(cliente_id, nota_id)
        if nota.situacao not in ("autorizada", "cancelada"):
            raise HTTPException(409, "Só há PDF de nota autorizada ou cancelada.")
        pdf = gerar_pdf(nota, cliente_ou_404(cliente_id), servico.config.ambiente)
        return RespostaBruta(pdf, media_type="application/pdf", headers={
            "Content-Disposition": f'attachment; filename="nota-{nota.numero_dps:06d}.pdf"',
            "Cache-Control": "no-store",
        })

    @app.get("/app/{cliente_id}/notas/{nota_id}/xml", tags=["app da empresa"])
    def baixar_xml(cliente_id: int, nota_id: int, _: Usuario = Depends(autorizar_empresa)):
        nota = nota_da_empresa(cliente_id, nota_id)
        try:
            nome, conteudo = xml_para_download(nota, servico.config.ambiente)
        except regras.ErroDeNegocio as erro:
            raise traduzir_erro(erro)
        return RespostaBruta(conteudo.encode("utf-8"), media_type="application/xml", headers={
            "Content-Disposition": f'attachment; filename="{nome}"',
            "Cache-Control": "no-store",
        })

    @app.get("/app/{cliente_id}/notas", tags=["app da empresa"])
    def minhas_notas(cliente_id: int, _: Usuario = Depends(autorizar_empresa)):
        cliente_ou_404(cliente_id)
        return [nota_json(n) for n in repo.listar_notas(cliente_id)]

    @app.post("/app/{cliente_id}/notas/{nota_id}/cancelar", tags=["app da empresa"])
    def cancelar_nota(cliente_id: int, nota_id: int, dados: PedidoCancelamento,
                      request: Request, usuario: Usuario = Depends(autorizar_empresa)):
        try:
            nota = servico.cancelar(cliente_id, nota_id, dados.motivo, dados.texto)
        except regras.ErroDeNegocio as erro:
            raise traduzir_erro(erro)
        evento("nota_cancelada", request, usuario, detalhe=f"nº {nota.numero_dps}")
        return nota_json(nota)

    return app


app = criar_app()
