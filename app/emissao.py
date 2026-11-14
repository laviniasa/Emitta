"""Fluxos principais: emitir e cancelar uma nota.

Proteção contra nota duplicada:
1. Cada tela de "Nova nota" manda uma chave de envio única. Se o mesmo envio
   chegar duas vezes (toque duplo, internet instável), devolvemos a nota que
   já existe em vez de emitir outra.
2. A nota é gravada como "processando" ANTES de ir ao governo. Se a resposta
   se perder, ela continua "processando" e o Emitta pergunta ao governo
   (GET /dps/{id}) se a nota foi gerada, antes de qualquer reenvio.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import regras
from .assinatura import assinar
from .catalogo import descricao_oficial
from .certificados import ProvedorCertificados
from .config import Config
from .dps import (
    DadosCancelamento,
    DadosDPS,
    id_dps,
    montar_dps,
    montar_pedido_cancelamento,
    para_bytes,
    validar_xsd,
)
from .repositorio import Nota, Repositorio
from .sefin import ClienteSefin, SemResposta


class ClienteNaoEncontrado(regras.ErroDeNegocio):
    pass


class NotaNaoEncontrada(regras.ErroDeNegocio):
    pass


class RejeitadaPelaPrefeitura(regras.ErroDeNegocio):
    def __init__(self, mensagens: list[str], nota: Nota | None = None):
        self.mensagens = mensagens
        self.nota = nota
        super().__init__("A prefeitura recusou: " + "; ".join(mensagens))


class NotaEmProcessamento(regras.ErroDeNegocio):
    def __init__(self, nota: Nota):
        self.nota = nota
        super().__init__(
            "A prefeitura ainda não confirmou esta nota. Não emita de novo: "
            "toque em \"Verificar agora\" daqui a pouco."
        )


FUSO_BRASILIA = timezone(timedelta(hours=-3))  # o Brasil não tem horário de verão desde 2019


def agora_brasilia() -> datetime:
    """Hora de Brasília, 1 minuto para trás.

    O Emissor Nacional recusa (E0008) DPS com data de emissão posterior ao
    relógio dele; um pequeno atraso evita a recusa quando os relógios
    diferem por alguns segundos. O fuso -03:00 também garante que a
    competência (data) seja a do Brasil, e não a do servidor em UTC.
    """
    return (datetime.now(FUSO_BRASILIA) - timedelta(minutes=1)).replace(microsecond=0)


class ServicoEmissao:
    def __init__(
        self,
        repo: Repositorio,
        sefin: ClienteSefin,
        config: Config,
        certificados: ProvedorCertificados,
        relogio=None,
    ):
        self.repo = repo
        self.sefin = sefin
        self.config = config
        self.certificados = certificados
        self.agora = relogio or agora_brasilia

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

    def _percentual_simples(self, cliente) -> str:
        if cliente.opcao_simples != "3":
            return "0.00"
        if cliente.p_tot_trib_sn:
            return cliente.p_tot_trib_sn
        if self.config.ambiente == "simulacao":
            return "0.00"
        raise regras.ErroDeNegocio(
            "Falta o percentual aproximado de tributos do Simples no cadastro da empresa. "
            "Peça ao seu contador para completar."
        )

    # ---------------------------------------------------------------- emitir

    def emitir(
        self,
        cliente_id: int,
        codigo_servico: str,
        tomador_documento: str,
        tomador_nome: str,
        valor,
        descricao: str | None = None,
        competencia=None,
        iss_retido: bool = False,
        chave_envio: str | None = None,
    ) -> Nota:
        cliente = self._cliente(cliente_id)

        # 0. Mesmo envio repetido? Devolve o que já existe.
        if chave_envio:
            existente = self.repo.buscar_nota_por_chave_envio(cliente_id, chave_envio)
            if existente:
                return self._resolver_existente(cliente, existente)

        # 1. Regras antes de qualquer coisa sair do servidor
        servicos = {s["codigo"]: s for s in self.repo.servicos_liberados(cliente_id)}
        regras.verificar_servico_liberado(set(servicos), codigo_servico)
        codigo_municipal = (servicos.get(codigo_servico) or {}).get("codigo_municipal")
        tomador = regras.validar_documento(tomador_documento)
        tomador_nome = (tomador_nome or "").strip()
        if len(tomador_nome) < 2:
            raise regras.ErroDeNegocio("Informe o nome do cliente.")
        valor_centavos = regras.valor_em_centavos(valor)
        iss = regras.calcular_iss(valor_centavos, cliente.aliquota_iss)
        descricao = (descricao or "").strip() or descricao_oficial(codigo_servico) or "Prestação de serviço"
        agora = self.agora()
        data_servico = regras.validar_competencia(competencia, agora.date())
        regras.verificar_retencao(bool(iss_retido), tomador, cliente.opcao_simples)
        percentual_sn = self._percentual_simples(cliente)
        cert = self.certificados.para(cliente)

        # 2. Monta e assina o XML
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
            competencia=data_servico,
            iss_retido=bool(iss_retido),
            aliquota_iss=cliente.aliquota_iss,
            reg_ap_trib_sn=cliente.reg_ap_trib_sn or "1",
            p_tot_trib_sn=percentual_sn,
            codigo_municipal=codigo_municipal,
        ))
        assinar(xml, "infDPS", cert)
        self._validar_xsd(xml, "DPS_v1.01.xsd")
        xml_bytes = para_bytes(xml)

        # 3. Grava ANTES de enviar (se a resposta se perder, sabemos o que conferir)
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
            situacao="processando",
            emitida_em=agora.isoformat(),
            competencia=data_servico.isoformat(),
            iss_retido=int(bool(iss_retido)),
            id_dps=id_dps(cliente.municipio_ibge, cliente.cnpj, cliente.serie_dps, numero),
            xml_dps=xml_bytes.decode("utf-8"),
            chave_envio=chave_envio,
        )

        # 4. Envia
        try:
            resposta = self.sefin.enviar_dps(xml_bytes, cert)
        except SemResposta:
            raise NotaEmProcessamento(nota) from None
        return self._registrar_resposta(nota, resposta)

    def _registrar_resposta(self, nota: Nota, resposta) -> Nota:
        if resposta.sucesso:
            return self.repo.atualizar_nota(
                nota.id, situacao="autorizada", chave_acesso=resposta.chave_acesso,
                xml_nfse=resposta.xml, mensagem=None,
            )
        atualizada = self.repo.atualizar_nota(
            nota.id, situacao="rejeitada", mensagem="; ".join(resposta.mensagens) or None,
        )
        raise RejeitadaPelaPrefeitura(resposta.mensagens, atualizada)

    def _resolver_existente(self, cliente, nota: Nota) -> Nota:
        if nota.situacao == "processando":
            return self.verificar(cliente.id, nota.id)
        if nota.situacao == "rejeitada":
            raise RejeitadaPelaPrefeitura([nota.mensagem or "Recusada"], nota)
        return nota

    def verificar(self, cliente_id: int, nota_id: int) -> Nota:
        """Para nota "processando": pergunta ao governo se ela foi gerada.
        Se foi, registra. Se não foi, reenvia o MESMO XML (mesmo número), o que
        nunca gera nota duplicada: o governo recusa DPS repetida."""
        cliente = self._cliente(cliente_id)
        nota = self.repo.buscar_nota(nota_id)
        if not nota or nota.cliente_id != cliente_id:
            raise NotaNaoEncontrada("Nota não encontrada.")
        if nota.situacao != "processando":
            return nota
        cert = self.certificados.para(cliente)
        try:
            consulta = self.sefin.consultar_dps(nota.id_dps, cert)
            if consulta is not None:
                return self._registrar_resposta(nota, consulta)
            resposta = self.sefin.enviar_dps(nota.xml_dps.encode("utf-8"), cert)
        except SemResposta:
            raise NotaEmProcessamento(nota) from None
        return self._registrar_resposta(nota, resposta)

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
        cert = self.certificados.para(cliente)
        assinar(xml, "infPedReg", cert)
        self._validar_xsd(xml, "pedRegEvento_v1.01.xsd")

        try:
            resposta = self.sefin.enviar_evento(nota.chave_acesso, para_bytes(xml), cert)
        except SemResposta as erro:
            raise regras.ErroDeNegocio(str(erro)) from None
        if not resposta.sucesso:
            raise RejeitadaPelaPrefeitura(resposta.mensagens)
        return self.repo.marcar_cancelada(nota_id, descricao_motivo, agora.isoformat())


def xml_para_download(nota: Nota, ambiente: str) -> tuple[str, str]:
    """(nome do arquivo, conteúdo). NFS-e oficial quando houver; senão a DPS assinada."""
    if nota.xml_nfse and ambiente != "simulacao":
        return f"nfse-{nota.chave_acesso}.xml", nota.xml_nfse
    if nota.xml_dps:
        return f"dps-{nota.numero_dps:06d}.xml", nota.xml_dps
    raise NotaNaoEncontrada("Esta nota não tem XML disponível.")

