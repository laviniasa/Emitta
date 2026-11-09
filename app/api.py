"""API web (FastAPI).

Rode com:  uvicorn app.api:app --reload
Documentação interativa:  http://localhost:8000/docs

Rotas:
  /catalogo/servicos             lista nacional (para o contador escolher)
  /contador/...                  painel do contador
  /app/{cliente_id}/...          app do cliente (só vê o que foi liberado)

ATENÇÃO: ainda não há login. Antes de colocar no ar, adicione autenticação
(contador e cliente) — está nos próximos passos do README.
"""

from decimal import Decimal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import regras
from .catalogo import carregar_catalogo
from .certificados import ProvedorCertificados
from .config import carregar_config
from .emissao import (
    ClienteNaoEncontrado,
    NotaNaoEncontrada,
    RejeitadaPelaPrefeitura,
    ServicoEmissao,
)
from .repositorio import Nota, Repositorio
from .sefin import SefinNacional, SefinSimulada


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


def criar_app(servico: ServicoEmissao | None = None) -> FastAPI:
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
    app = FastAPI(title="Emitta", version="0.1.0")

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
    def listar_catalogo():
        return list(carregar_catalogo().values())

    # ------------------------------------------------------------ contador

    @app.post("/contador/clientes", status_code=201, tags=["contador"])
    def criar_cliente(dados: NovoCliente):
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
    def listar_clientes():
        return [
            {**c.__dict__, "servicos_liberados": len(repo.servicos_liberados(c.id))}
            for c in repo.listar_clientes()
        ]

    @app.get("/contador/clientes/{cliente_id}/servicos", tags=["contador"])
    def ver_servicos_do_cliente(cliente_id: int):
        cliente_ou_404(cliente_id)
        liberados = {s["codigo"]: s["apelido"] for s in repo.servicos_liberados(cliente_id)}
        return [
            {**s, "liberado": s["codigo"] in liberados, "apelido": liberados.get(s["codigo"])}
            for s in carregar_catalogo().values()
        ]

    @app.put("/contador/clientes/{cliente_id}/servicos", tags=["contador"])
    def liberar_servicos(cliente_id: int, dados: ListaServicos):
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
    def notas_do_cliente(cliente_id: int):
        cliente_ou_404(cliente_id)
        return [nota_json(n) for n in repo.listar_notas(cliente_id)]

    # ------------------------------------------------------------ app do cliente

    @app.get("/app/{cliente_id}/servicos", tags=["app do cliente"])
    def servicos_para_emitir(cliente_id: int):
        """Só os serviços liberados pelo contador."""
        cliente_ou_404(cliente_id)
        return repo.servicos_liberados(cliente_id)

    @app.post("/app/{cliente_id}/notas", status_code=201, tags=["app do cliente"])
    def emitir_nota(cliente_id: int, dados: NovaNota):
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

    @app.get("/app/{cliente_id}/notas", tags=["app do cliente"])
    def minhas_notas(cliente_id: int):
        cliente_ou_404(cliente_id)
        return [nota_json(n) for n in repo.listar_notas(cliente_id)]

    @app.post("/app/{cliente_id}/notas/{nota_id}/cancelar", tags=["app do cliente"])
    def cancelar_nota(cliente_id: int, nota_id: int, dados: PedidoCancelamento):
        try:
            nota = servico.cancelar(cliente_id, nota_id, dados.motivo, dados.texto)
        except regras.ErroDeNegocio as erro:
            raise traduzir_erro(erro)
        return nota_json(nota)

    return app


app = criar_app()
