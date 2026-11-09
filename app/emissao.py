"""Fluxos principais: emitir e cancelar uma nota.

Junta regras de negócio, banco, XML, assinatura e API num só lugar.
"""

from __future__ import annotations

from datetime import datetime

from . import regras
from .assinatura import assinar
from .catalogo import descricao_oficial
from .certificados import ProvedorCertificados
from .config import Config
from .dps import (
    DadosCancelamento,
    DadosDPS,
    montar_dps,
    montar_pedido_cancelamento,
    para_bytes,
    validar_xsd,
)
from .repositorio import Nota, Repositorio
from .sefin import ClienteSefin


class ClienteNaoEncontrado(regras.ErroDeNegocio):
    pass


class NotaNaoEncontrada(regras.ErroDeNegocio):
    pass


class RejeitadaPelaPrefeitura(regras.ErroDeNegocio):
    def __init__(self, mensagens: list[str], nota: Nota | None = None):
        self.mensagens = mensagens
        self.nota = nota
        super().__init__("A prefeitura recusou: " + "; ".join(mensagens))


class ServicoEmissao:
    def __init__(
        self,
        repo: Repositorio,
        sefin: ClienteSefin,
        config: Config,
        certificados: ProvedorCertificados,
        relogio=lambda: datetime.now().astimezone(),
    ):
        self.repo = repo
        self.sefin = sefin
        self.config = config
        self.certificados = certificados
        self.agora = relogio

    def _cliente(self, cliente_id: int):
        cliente = self.repo.buscar_cliente(cliente_id)
        if not cliente:
            raise ClienteNaoEncontrado("Empresa não encontrada.")
        return cliente

    def _validar_xsd(self, xml, nome_xsd: str) -> None:
        if not self.config.pasta_xsd:
            return
        arquivo = self.config.pasta_xsd / nome_xsd
        if arquivo.exists():
            erros = validar_xsd(xml, arquivo)
            if erros:
                raise regras.ErroDeNegocio("XML fora do leiaute oficial: " + "; ".join(erros[:3]))

    # ---------------------------------------------------------------- emitir

    def emitir(
        self,
        cliente_id: int,
        codigo_servico: str,
        tomador_documento: str,
        tomador_nome: str,
        valor,
        descricao: str | None = None,
    ) -> Nota:
        cliente = self._cliente(cliente_id)

        # 1. Regras antes de qualquer coisa sair do servidor
        liberados = {s["codigo"] for s in self.repo.servicos_liberados(cliente_id)}
        regras.verificar_servico_liberado(liberados, codigo_servico)
        tomador = regras.validar_documento(tomador_documento)
        tomador_nome = (tomador_nome or "").strip()
        if not tomador_nome:
            raise regras.ErroDeNegocio("Informe o nome do cliente.")
        valor_centavos = regras.valor_em_centavos(valor)
        iss = regras.calcular_iss(valor_centavos, cliente.aliquota_iss)
        descricao = (descricao or "").strip() or descricao_oficial(codigo_servico) or "Prestação de serviço"

        # 2. Monta e assina o XML
        agora = self.agora()
        numero = self.repo.proximo_numero_dps(cliente_id)
        xml = montar_dps(DadosDPS(
            tp_amb=self.config.tp_amb,
            versao_aplicativo=self.config.versao_aplicativo,
            emitida_em=agora,
            serie=cliente.serie_dps,
            numero=numero,
            municipio_ibge=cliente.municipio_ibge,
            prestador_cnpj=cliente.cnpj,
            opcao_simples=cliente.opcao_simples,
            tomador_tipo=tomador.tipo,
            tomador_documento=tomador.numero,
            tomador_nome=tomador_nome,
            codigo_servico=codigo_servico,
            descricao=descricao,
            valor=regras.centavos_para_texto(valor_centavos),
        ))
        cert = self.certificados.para(cliente.cnpj)
        assinar(xml, "infDPS", cert)
        self._validar_xsd(xml, "DPS_v1.00.xsd")

        # 3. Envia e guarda o resultado (inclusive rejeições, para histórico)
        resposta = self.sefin.enviar_dps(para_bytes(xml), cert)
        nota = self.repo.salvar_nota(
            cliente_id=cliente_id,
            numero_dps=numero,
            codigo_servico=codigo_servico,
            tomador_tipo=tomador.tipo,
            tomador_documento=tomador.numero,
            tomador_nome=tomador_nome,
            descricao=descricao,
            valor_centavos=valor_centavos,
            iss_centavos=iss,
            situacao="autorizada" if resposta.sucesso else "rejeitada",
            chave_acesso=resposta.chave_acesso,
            xml_nfse=resposta.xml,
            mensagem="; ".join(resposta.mensagens) or None,
            emitida_em=agora.isoformat(),
        )
        if not resposta.sucesso:
            raise RejeitadaPelaPrefeitura(resposta.mensagens, nota)
        return nota

    # ---------------------------------------------------------------- cancelar

    def cancelar(self, cliente_id: int, nota_id: int, motivo: str, texto: str | None = None) -> Nota:
        cliente = self._cliente(cliente_id)
        nota = self.repo.buscar_nota(nota_id)
        if not nota or nota.cliente_id != cliente_id:
            raise NotaNaoEncontrada("Nota não encontrada.")

        regras.verificar_situacao_cancelavel(nota.situacao)
        agora = self.agora()
        regras.verificar_prazo_cancelamento(
            datetime.fromisoformat(nota.emitida_em), cliente.prazo_cancelamento_dias, agora
        )
        codigo_motivo, descricao_motivo = regras.motivo_cancelamento(motivo, texto)

        xml = montar_pedido_cancelamento(DadosCancelamento(
            tp_amb=self.config.tp_amb,
            versao_aplicativo=self.config.versao_aplicativo,
            quando=agora,
            autor_cnpj=cliente.cnpj,
            chave_acesso=nota.chave_acesso,
            codigo_motivo=codigo_motivo,
            texto_motivo=descricao_motivo,
        ))
        cert = self.certificados.para(cliente.cnpj)
        assinar(xml, "infPedReg", cert)
        self._validar_xsd(xml, "pedRegEvento_v1.00.xsd")

        resposta = self.sefin.enviar_evento(nota.chave_acesso, para_bytes(xml), cert)
        if not resposta.sucesso:
            raise RejeitadaPelaPrefeitura(resposta.mensagens)
        return self.repo.marcar_cancelada(nota_id, descricao_motivo, agora.isoformat())
