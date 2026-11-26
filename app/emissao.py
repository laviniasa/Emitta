"""Fluxos principais: emitir e cancelar uma nota.

Proteção contra nota duplicada:
1. Cada tela de "Nova nota" manda uma chave de envio única. Se o mesmo envio
   chegar duas vezes (toque duplo, internet instável), devolvemos a nota que
   já existe em vez de emitir outra.
2. A nota é gravada como "processando" ANTES de ir ao governo. Se a resposta
   se perder, ela continua "processando" e o EmitHub pergunta ao governo
   (GET /dps/{id}) se a nota foi gerada, antes de qualquer reenvio.
"""

from __future__ import annotations

from decimal import Decimal

import json
from datetime import datetime, timedelta, timezone

from . import regras
from .assinatura import assinar
from .catalogo import descricao_oficial
from .certificados import ProvedorCertificados
from .config import Config
from .dps import (
    endereco_valido,
    texto_leiaute,
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


MAX_PULOS_NUMERO = 50  # números já usados no governo que o EmitHub pula sozinho (E0014)


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

    def _xsd(self, nome: str) -> str:
        """XSD do leiaute em uso: app/xsd (NT 009) ou app/xsd/nt004 (produção até 30/11/2026)."""
        return f"nt004/{nome}" if self.config.leiaute == "nt004" else nome

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
        info_compl: str | None = None,
        tomador_endereco: dict | None = None,
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
        rtc = servicos.get(codigo_servico) or {}
        info_compl = texto_leiaute(info_compl, " / ")[:2000] or None
        print(f"[emissao] cliente {cliente_id} servico {codigo_servico} codigo_municipal {codigo_municipal or '-'}", flush=True)
        tomador = regras.validar_documento(tomador_documento)
        tomador_nome = (tomador_nome or "").strip()
        if len(tomador_nome) < 2:
            raise regras.ErroDeNegocio("Informe o nome do cliente.")
        valor_centavos = regras.valor_em_centavos(valor)
        iss = regras.calcular_iss(valor_centavos, cliente.aliquota_iss)
        descricao = (descricao or "").strip() or descricao_oficial(codigo_servico) or "Prestação de serviço"
        descricao = texto_leiaute(descricao)[:2000] or "Prestação de serviço"
        tomador_nome = texto_leiaute(tomador_nome)[:300]
        agora = self.agora()
        data_servico = regras.validar_competencia(competencia, agora.date())
        regras.verificar_retencao(bool(iss_retido), tomador, cliente.opcao_simples)
        percentual_sn = self._percentual_simples(cliente)
        federais, estaduais, municipais = regras.tributos_aproximados(
            valor_centavos, cliente.opcao_simples, percentual_sn, iss)
        texto_trib = (regras.texto_tributos_simples(valor_centavos, percentual_sn) if cliente.opcao_simples == "3"
                      else regras.texto_tributos(federais, estaduais, municipais))
        info_compl = regras.info_complementar_com_tributos(texto_trib, info_compl)
        cert = self.certificados.para(cliente)
        codigo_municipal = self._conferir_na_prefeitura(cliente, codigo_servico, codigo_municipal, cert)

        for tentativa in range(MAX_PULOS_NUMERO + 1):
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
                nbs=rtc.get("nbs"), cind_op=rtc.get("cind_op"), cclass_trib=rtc.get("cclass_trib"),
                info_compl=info_compl,
                tomador_end=tomador_endereco,
                leiaute=self.config.leiaute,
            ))
            assinar(xml, "infDPS", cert)
            self._validar_xsd(xml, self._xsd("DPS_v1.01.xsd"))
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
                info_compl=info_compl,
                ibscbs=json.dumps({"nbs": rtc.get("nbs"), "cind_op": rtc.get("cind_op"), "cclass_trib": rtc.get("cclass_trib")})
                if self.config.leiaute == "nt009" and rtc.get("nbs") and rtc.get("cind_op") and rtc.get("cclass_trib")
                and endereco_valido(tomador_endereco) else None,  # na NT 004 o grupo IBS/CBS não vai no XML
            )

            # 4. Envia
            try:
                resposta = self.sefin.enviar_dps(xml_bytes, cert)
            except SemResposta:
                raise NotaEmProcessamento(nota) from None
            # E0014 = o governo já tem uma nota com este número para este CNPJ (por exemplo,
            # emitida antes de o banco do EmitHub ser zerado). Pula para o próximo número.
            if not resposta.sucesso and tentativa < MAX_PULOS_NUMERO and any("E0014" in m for m in resposta.mensagens):
                print(f"[emissao] cliente {cliente_id}: número {numero} já usado no governo (E0014), tentando o próximo", flush=True)
                self.repo.descartar_nota(nota.id)
                continue
            return self._registrar_resposta(nota, resposta)

    def _conferir_na_prefeitura(self, cliente, codigo_servico: str, codigo_municipal: str | None, cert) -> str | None:
        """Antes de enviar: se o serviço ainda não foi conferido na prefeitura (sem complemento
        municipal guardado), pergunta ao governo. Guarda o complemento que a prefeitura pede
        (evita a recusa E0312) e, se a prefeitura não aceita o serviço, avisa sem enviar nada."""
        if codigo_municipal or self.config.ambiente == "simulacao" or not hasattr(self.sefin, "consultar_servico_municipio"):
            return codigo_municipal
        try:
            r = self.sefin.consultar_servico_municipio(cliente.municipio_ibge, codigo_servico, cert)
        except Exception as erro:  # a conferência é uma ajuda: se falhar, segue como antes
            print(f"[emissao] conferência na prefeitura falhou: {erro}", flush=True)
            return codigo_municipal
        print(f"[emissao] prefeitura {cliente.municipio_ibge} servico {codigo_servico}: administrado={r.administrado} "
              f"codigos={r.codigos_municipais}", flush=True)
        if r.codigos_municipais:
            self.repo.definir_codigo_municipal(cliente.id, codigo_servico, r.codigos_municipais[0])
            return r.codigos_municipais[0]
        if r.administrado is False:
            raise regras.ErroDeNegocio(
                f"A prefeitura de {cliente.municipio_nome} não aceita este serviço (código "
                f"{codigo_servico[:2]}.{codigo_servico[2:4]}.{codigo_servico[4:]}) pela nota nacional. Nada foi enviado. "
                "Peça ao contador para liberar um serviço parecido que a prefeitura aceite.")
        return codigo_municipal

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

    def trazer_nota_externa(self, cliente_id: int, chave: str | None = None, xml: str | None = None) -> Nota:
        """Traz para o EmitHub uma NFS-e emitida em outro sistema (Emissor Nacional, app do
        governo...), pela chave de acesso ou pelo XML, para poder ver, baixar o PDF e cancelar."""
        cliente = self._cliente(cliente_id)
        chave = "".join(ch for ch in (chave or "") if ch.isdigit())
        dados = ler_nfse_externa(xml) if xml else None
        if dados:
            chave = dados["chave"] or chave
        if not chave_valida(chave):
            raise regras.ErroDeNegocio("A chave de acesso tem 50 números. Confira e cole de novo.")
        cnpj_da_chave = chave[9:23] if chave[8] == "2" else None
        prestador = (dados or {}).get("prestador") or cnpj_da_chave
        if prestador != cliente.cnpj:
            raise regras.ErroDeNegocio("Esta nota foi emitida por outro CNPJ. Só dá para trazer notas emitidas por esta empresa.")
        ja = self.repo.buscar_nota_por_chave_acesso(cliente_id, chave)
        if ja:
            return ja
        if not dados:  # só a chave: pede o XML ao sistema nacional, com o certificado da empresa
            cert = self.certificados.para(cliente)
            try:
                xml = self.sefin.consultar_nfse(chave, cert)
            except SemResposta as erro:
                raise regras.ErroDeNegocio(str(erro)) from None
            dados = ler_nfse_externa(xml) if xml else None
        agora = self.agora().isoformat()
        d = dados or {}
        return self.repo.salvar_nota(
            cliente_id=cliente_id, numero_dps=self.repo.numero_para_nota_externa(cliente_id),
            codigo_servico=d.get("codigo_servico") or "", tomador_tipo=d.get("tomador_tipo") or "",
            tomador_documento=d.get("tomador_documento") or "",
            tomador_nome=d.get("tomador_nome") or "Nota trazida pela chave de acesso",
            descricao=d.get("descricao") or "", valor_centavos=d.get("valor_centavos") or 0,
            iss_centavos=d.get("iss_centavos") or 0, situacao="autorizada", chave_acesso=chave,
            xml_nfse=xml, mensagem=None, emitida_em=d.get("emitida_em") or agora, cancelada_em=None,
            motivo_cancelamento=None, competencia=d.get("competencia"), iss_retido=d.get("iss_retido") or 0,
            info_compl=d.get("info_compl"), origem="externa",
        )

    def cancelar(self, cliente_id: int, nota_id: int, motivo: str, texto: str | None = None) -> Nota:
        cliente = self._cliente(cliente_id)
        nota = self.repo.buscar_nota(nota_id)
        if not nota or nota.cliente_id != cliente_id:
            raise NotaNaoEncontrada("Nota não encontrada.")

        regras.verificar_situacao_cancelavel(nota.situacao)
        agora = self.agora()
        if nota.origem != "externa":  # nota de fora: quem confere o prazo é o governo
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
        self._validar_xsd(xml, self._xsd("pedRegEvento_v1.01.xsd"))

        try:
            resposta = self.sefin.enviar_evento(nota.chave_acesso, para_bytes(xml), cert)
        except SemResposta as erro:
            raise regras.ErroDeNegocio(str(erro)) from None
        if not resposta.sucesso:
            raise RejeitadaPelaPrefeitura(resposta.mensagens)
        return self.repo.marcar_cancelada(nota_id, descricao_motivo, agora.isoformat())


def _txt(raiz, *caminhos: str) -> str | None:
    """Primeiro texto encontrado (por nome local) em qualquer profundidade."""
    for caminho in caminhos:
        xp = ".//" + "/".join(f"*[local-name()='{p}']" for p in caminho.split("/"))
        for n in raiz.xpath(xp):
            if n.text and n.text.strip():
                return n.text.strip()
    return None


def ler_nfse_externa(xml: str) -> dict:
    """Dados de uma NFS-e nacional autorizada (XML do Emissor Nacional, do app do governo ou de
    outro sistema). Levanta ErroDeNegocio se não for uma NFS-e nacional."""
    from lxml import etree
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    try:
        raiz = etree.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml, parser)
    except etree.XMLSyntaxError:
        raise regras.ErroDeNegocio("Este arquivo não é um XML válido.") from None
    inf = raiz.xpath(".//*[local-name()='infNFSe']") or ([raiz] if etree.QName(raiz).localname == "infNFSe" else [])
    if not inf:
        raise regras.ErroDeNegocio("Este XML não é de uma NFS-e nacional autorizada (falta o bloco infNFSe).")
    inf = inf[0]
    digitos = "".join(ch for ch in (inf.get("Id") or "") if ch.isdigit())
    chave = digitos[-50:] if len(digitos) >= 50 else (_txt(raiz, "chNFSe") or "")
    valor = _txt(inf, "vServPrest/vServ") or "0"
    try:
        centavos = int((Decimal(valor) * 100).quantize(Decimal("1")))
    except Exception:
        centavos = 0
    iss = _txt(inf, "valores/vISSQN")
    tipo = "CNPJ" if _txt(inf, "toma/CNPJ") else "CPF" if _txt(inf, "toma/CPF") else "NIF" if _txt(inf, "toma/NIF") else ""
    return {
        "chave": chave,
        "prestador": _txt(inf, "emit/CNPJ", "prest/CNPJ", "emit/CPF", "prest/CPF") or chave[9:23],
        "tomador_tipo": tipo,
        "tomador_documento": _txt(inf, "toma/CNPJ", "toma/CPF", "toma/NIF") or "",
        "tomador_nome": _txt(inf, "toma/xNome") or "Tomador não identificado",
        "codigo_servico": _txt(inf, "cServ/cTribNac") or "",
        "descricao": _txt(inf, "cServ/xDescServ") or "",
        "valor_centavos": centavos,
        "iss_centavos": int((Decimal(iss) * 100).quantize(Decimal("1"))) if iss else 0,
        "emitida_em": _txt(inf, "dhProc", "dhEmi"),
        "competencia": _txt(inf, "dCompet"),
        "iss_retido": 1 if _txt(inf, "tribMun/tpRetISSQN") in ("2", "3") else 0,
        "info_compl": _txt(inf, "infoCompl/xInfComp"),
    }


def chave_valida(chave: str) -> bool:
    return len(chave) == 50 and chave.isdigit()


def xml_para_download(nota: Nota, ambiente: str) -> tuple[str, str]:
    """(nome do arquivo, conteúdo). NFS-e oficial quando houver; senão a DPS assinada."""
    if nota.xml_nfse and ambiente != "simulacao":
        return f"nfse-{nota.chave_acesso}.xml", nota.xml_nfse
    if nota.xml_dps:
        return f"dps-{nota.numero_dps:06d}.xml", nota.xml_dps
    raise NotaNaoEncontrada("Esta nota não tem XML disponível.")

