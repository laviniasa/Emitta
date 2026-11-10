"""API web (FastAPI).

Rode com:  uvicorn app.api:app --reload
Documentação interativa:  http://localhost:8000/docs

Páginas:
  /                              apresentação
  /entrar                        login, primeiro acesso, troca de senha
  /painel                        painel do contador
  /app                           app da empresa

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

import os
from decimal import Decimal
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import regras
from .autenticacao import (
    AcessoNegado,
    ErroAutenticacao,
    MSG_BLOQUEADO,
    DURACAO_SESSAO,
    ServicoAutenticacao,
)
from .catalogo import carregar_catalogo
from .certificados import ProvedorCertificados
from .config import carregar_config
from .emissao import (
    ClienteNaoEncontrado,
    NotaNaoEncontrada,
    RejeitadaPelaPrefeitura,
    ServicoEmissao,
)
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
    aliquota_iss: Decimal = Field(gt=0, le=5)
    opcao_simples: str = Field("3", description="1 não optante, 2 MEI, 3 ME/EPP")
    prazo_cancelamento_dias: int | None = None


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
    descricao: str | None = None


class PedidoCancelamento(BaseModel):
    motivo: str = Field(description="erro | nao_prestado | outro")
    texto: str | None = None


class Instalacao(BaseModel):
    codigo: str
    nome: str
    email: str
    senha: str


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
) -> FastAPI:
    if servico is None:
        config = carregar_config()
        sefin = SefinSimulada() if config.ambiente == "simulacao" else SefinNacional(config.url_sefin)
        servico = ServicoEmissao(
            repo=Repositorio(config.banco),
            sefin=sefin,
            config=config,
            certificados=ProvedorCertificados(
                config.pasta_certificados, permitir_teste=config.ambiente == "simulacao"
            ),
        )
    repo = servico.repo
    auth = auth or ServicoAutenticacao(repo)
    if cookie_seguro is None:
        cookie_seguro = os.getenv("EMITTA_COOKIE_SEGURO", "1") != "0"
    if not cookie_seguro and servico.config.ambiente != "simulacao":
        raise RuntimeError("EMITTA_COOKIE_SEGURO=0 só é permitido no modo simulação.")
    limitador = LimitadorTentativas(limite=10, janela=15 * 60)

    app = FastAPI(title="Emitta", version="0.2.0")

    # ------------------------------------------------------------ proteções gerais

    @app.middleware("http")
    async def protecoes(request: Request, call_next):
        caminho = request.url.path
        if request.method in METODOS_QUE_ALTERAM and request.headers.get(CABECALHO_CSRF) != "1":
            return JSONResponse({"detail": "Requisição bloqueada por segurança (falta o cabeçalho X-Emitta)."}, 403)
        resposta = await call_next(request)
        resposta.headers["X-Content-Type-Options"] = "nosniff"
        resposta.headers["Referrer-Policy"] = "same-origin"
        resposta.headers["X-Frame-Options"] = "DENY"
        resposta.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if not caminho.startswith(("/docs", "/redoc", "/openapi.json")):
            resposta.headers["Content-Security-Policy"] = CSP
        if cookie_seguro:
            resposta.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if caminho.startswith(("/auth", "/contador", "/app/", "/catalogo")):
            resposta.headers["Cache-Control"] = "no-store"
        return resposta

    def gravar_sessao(resposta: Response, token: str) -> None:
        resposta.set_cookie(
            COOKIE, token, max_age=int(DURACAO_SESSAO.total_seconds()), httponly=True,
            secure=cookie_seguro, samesite="strict", path="/",
        )

    def limitar(request: Request) -> None:
        if not limitador.permitir(ip_do_pedido(request)):
            raise HTTPException(429, MSG_BLOQUEADO)

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

    def autorizar_empresa(cliente_id: int, usuario: Usuario = Depends(usuario_atual)) -> Usuario:
        # Uma empresa só enxerga a si mesma. Responde 404 (e não 403) para não
        # confirmar que outras empresas existem.
        if usuario.papel == "empresa" and usuario.cliente_id != cliente_id:
            raise HTTPException(404, "Empresa não encontrada.")
        return usuario

    def erro_auth(e: Exception) -> HTTPException:
        if isinstance(e, AcessoNegado):
            return HTTPException(403, str(e))
        return HTTPException(400, str(e))

    # ------------------------------------------------------------ páginas

    app.mount("/static", StaticFiles(directory=PASTA_WEB), name="static")

    def pagina(nome: str):
        return FileResponse(PASTA_WEB / nome, headers={"Cache-Control": "no-cache"})

    @app.get("/", include_in_schema=False)
    def pagina_inicial():
        return pagina("index.html")

    @app.get("/entrar", include_in_schema=False)
    def pagina_entrar():
        return pagina("entrar.html")

    @app.get("/painel", include_in_schema=False)
    def pagina_painel():
        return pagina("painel.html")

    @app.get("/app", include_in_schema=False)
    def pagina_app():
        return pagina("app.html")

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
        limitar(request)
        try:
            usuario = auth.instalar(dados.codigo, dados.nome, dados.email, dados.senha)
            resultado = auth.entrar(usuario.email, dados.senha)
        except (ErroAutenticacao, AcessoNegado) as e:
            raise erro_auth(e)
        gravar_sessao(response, resultado.token_sessao)
        return {"usuario": usuario_json(usuario)}

    @app.post("/auth/entrar", tags=["autenticação"])
    def entrar(dados: Login, request: Request, response: Response):
        limitar(request)
        try:
            resultado = auth.entrar(dados.email, dados.senha)
        except ErroAutenticacao as e:
            raise HTTPException(401, str(e))
        if resultado.desafio_2fa:
            return {"precisa_2fa": True, "desafio": resultado.desafio_2fa}
        gravar_sessao(response, resultado.token_sessao)
        return {"usuario": usuario_json(resultado.usuario)}

    @app.post("/auth/2fa", tags=["autenticação"])
    def confirmar_2fa(dados: Codigo2FA, request: Request, response: Response):
        limitar(request)
        try:
            resultado = auth.confirmar_2fa(dados.desafio, dados.codigo)
        except ErroAutenticacao as e:
            raise HTTPException(401, str(e))
        gravar_sessao(response, resultado.token_sessao)
        return {"usuario": usuario_json(resultado.usuario)}

    @app.post("/auth/sair", tags=["autenticação"])
    def sair(request: Request, response: Response):
        auth.sair(request.cookies.get(COOKIE))
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
            return usuario_json(auth.ativar_2fa(usuario, dados.codigo))
        except ErroAutenticacao as e:
            raise erro_auth(e)

    @app.post("/auth/2fa/desativar", tags=["autenticação"])
    def desativar_2fa(dados: ConfirmarSenha, request: Request, usuario: Usuario = Depends(usuario_atual)):
        limitar(request)
        try:
            return usuario_json(auth.desativar_2fa(usuario, dados.senha))
        except ErroAutenticacao as e:
            raise erro_auth(e)

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
    def criar_cliente(dados: NovoCliente, _: Usuario = Depends(contador_atual)):
        cnpj = regras.somente_digitos(dados.cnpj)
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
            )
        except Exception as erro:  # sqlite3.IntegrityError
            if "UNIQUE" in str(erro):
                raise HTTPException(409, "Esta empresa já está cadastrada.")
            raise
        return cliente.__dict__

    @app.get("/contador/clientes", tags=["contador"])
    def listar_clientes(_: Usuario = Depends(contador_atual)):
        return [
            {**c.__dict__, "servicos_liberados": len(repo.servicos_liberados(c.id))}
            for c in repo.listar_clientes()
        ]

    @app.get("/contador/clientes/{cliente_id}/servicos", tags=["contador"])
    def ver_servicos_do_cliente(cliente_id: int, _: Usuario = Depends(contador_atual)):
        cliente_ou_404(cliente_id)
        liberados = {s["codigo"]: s["apelido"] for s in repo.servicos_liberados(cliente_id)}
        return [
            {**s, "liberado": s["codigo"] in liberados, "apelido": liberados.get(s["codigo"])}
            for s in carregar_catalogo().values()
        ]

    @app.put("/contador/clientes/{cliente_id}/servicos", tags=["contador"])
    def liberar_servicos(cliente_id: int, dados: ListaServicos, _: Usuario = Depends(contador_atual)):
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
    def notas_do_cliente(cliente_id: int, _: Usuario = Depends(contador_atual)):
        cliente_ou_404(cliente_id)
        return [nota_json(n) for n in repo.listar_notas(cliente_id)]

    @app.get("/contador/clientes/{cliente_id}/acessos", tags=["contador"])
    def acessos_da_empresa(cliente_id: int, _: Usuario = Depends(contador_atual)):
        cliente_ou_404(cliente_id)
        return [
            {"id": u.id, "nome": u.nome, "email": u.email, "aguardando_primeiro_acesso": bool(u.trocar_senha)}
            for u in repo.usuarios_da_empresa(cliente_id)
        ]

    @app.post("/contador/clientes/{cliente_id}/acessos", tags=["contador"])
    def criar_acesso(cliente_id: int, dados: NovoAcesso, _: Usuario = Depends(contador_atual)):
        """Cria ou redefine o acesso da empresa. A senha provisória aparece
        uma única vez e precisa ser trocada no primeiro acesso."""
        cliente_ou_404(cliente_id)
        try:
            usuario, provisoria = auth.criar_acesso_empresa(cliente_id, dados.nome, dados.email)
        except ErroAutenticacao as e:
            raise erro_auth(e)
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
        }

    @app.get("/app/{cliente_id}/servicos", tags=["app da empresa"])
    def servicos_para_emitir(cliente_id: int, _: Usuario = Depends(autorizar_empresa)):
        """Só os serviços liberados pelo contador."""
        cliente_ou_404(cliente_id)
        return repo.servicos_liberados(cliente_id)

    @app.post("/app/{cliente_id}/notas", status_code=201, tags=["app da empresa"])
    def emitir_nota(cliente_id: int, dados: NovaNota, _: Usuario = Depends(autorizar_empresa)):
        try:
            nota = servico.emitir(
                cliente_id,
                codigo_servico=dados.codigo_servico,
                tomador_documento=dados.tomador_documento,
                tomador_nome=dados.tomador_nome,
                valor=dados.valor,
                descricao=dados.descricao,
            )
        except regras.ErroDeNegocio as erro:
            raise traduzir_erro(erro)
        return nota_json(nota)

    @app.get("/app/{cliente_id}/notas", tags=["app da empresa"])
    def minhas_notas(cliente_id: int, _: Usuario = Depends(autorizar_empresa)):
        cliente_ou_404(cliente_id)
        return [nota_json(n) for n in repo.listar_notas(cliente_id)]

    @app.post("/app/{cliente_id}/notas/{nota_id}/cancelar", tags=["app da empresa"])
    def cancelar_nota(cliente_id: int, nota_id: int, dados: PedidoCancelamento,
                      _: Usuario = Depends(autorizar_empresa)):
        try:
            nota = servico.cancelar(cliente_id, nota_id, dados.motivo, dados.texto)
        except regras.ErroDeNegocio as erro:
            raise traduzir_erro(erro)
        return nota_json(nota)

    return app


app = criar_app()
