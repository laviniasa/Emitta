"""Comunicação com a API do Emissor Nacional (Sefin Nacional).

Dois clientes com a mesma interface:
- `SefinSimulada`: não acessa a internet, para desenvolver e testar telas.
- `SefinNacional`: chama a API de verdade, autenticando com o certificado A1
  (TLS mútuo: o governo identifica a empresa pelo certificado da conexão).

Rotas conferidas no manual oficial "Guia para utilização das APIs" (v1.2,
out/2025): POST /nfse, GET /nfse/{chave}, GET /dps/{id},
POST /nfse/{chave}/eventos.
"""

from __future__ import annotations

import base64
import gzip
import random
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import requests

from .assinatura import Certificado
from .regras import ErroDeNegocio


class SemResposta(ErroDeNegocio):
    """A prefeitura não respondeu (rede caiu, tempo esgotado). A nota pode ter
    sido autorizada mesmo assim: NÃO reenviar sem consultar antes."""


@dataclass
class RespostaSefin:
    sucesso: bool
    chave_acesso: str | None = None
    xml: str | None = None
    mensagens: list[str] = field(default_factory=list)


@dataclass
class ServicoNaPrefeitura:
    """O que o governo diz sobre um serviço num município (parâmetros municipais)."""
    administrado: bool | None  # None = não deu para saber
    conveniado: bool | None = None
    aliquotas: dict = field(default_factory=dict)
    mensagens: list[str] = field(default_factory=list)
    codigos_municipais: list[str] = field(default_factory=list)  # cTribMun aceitos (ex.: "001")


def codigo_servico_api(codigo: str, municipal: str = "000") -> str:
    """060201 (+ 003) -> 06.02.01.003: formato da API de parâmetros municipais
    (código nacional + complemento municipal cTribMun; 000 = sem complemento)."""
    c = codigo.zfill(6)
    return f"{c[:2]}.{c[2:4]}.{c[4:6]}.{municipal}"


class ClienteSefin(Protocol):
    def enviar_dps(self, xml_assinado: bytes, cert: Certificado | None) -> RespostaSefin: ...

    def consultar_dps(self, id_dps: str, cert: Certificado | None) -> RespostaSefin | None: ...

    def enviar_evento(
        self, chave_acesso: str, xml_assinado: bytes, cert: Certificado | None
    ) -> RespostaSefin: ...


def compactar(xml: bytes) -> str:
    return base64.b64encode(gzip.compress(xml)).decode()


def descompactar(texto: str) -> str:
    return gzip.decompress(base64.b64decode(texto)).decode("utf-8")


class SefinSimulada:
    """Imita a API. Controles para testes:
    - `rejeitar_com`: recusa com essa mensagem;
    - `cair_depois_de_autorizar`: autoriza, mas "perde" a resposta (como uma
      queda de internet), para testar a proteção contra nota duplicada.
    """

    def __init__(self, rejeitar_com: str | None = None):
        self.rejeitar_com = rejeitar_com
        self.cair_depois_de_autorizar = False
        self.enviados: list[bytes] = []
        self.autorizadas: dict[str, str] = {}  # id da DPS -> chave

    @staticmethod
    def _id_dps(xml_assinado: bytes) -> str:
        from lxml import etree
        raiz = etree.fromstring(xml_assinado)
        return next(el for el in raiz if etree.QName(el).localname == "infDPS").get("Id")

    def enviar_dps(self, xml_assinado, cert):
        self.enviados.append(xml_assinado)
        if self.rejeitar_com:
            return RespostaSefin(sucesso=False, mensagens=[self.rejeitar_com])
        id_dps = self._id_dps(xml_assinado)
        if id_dps in self.autorizadas:  # o governo recusa DPS repetida
            return RespostaSefin(sucesso=False, mensagens=["E0014 DPS já convertida em NFS-e"])
        chave = "".join(random.choice("0123456789") for _ in range(50))
        self.autorizadas[id_dps] = chave
        if self.cair_depois_de_autorizar:
            self.cair_depois_de_autorizar = False
            raise SemResposta("Simulação: a resposta da prefeitura se perdeu.")
        xml = f"<NFSe simulada='true'><chNFSe>{chave}</chNFSe></NFSe>"
        return RespostaSefin(sucesso=True, chave_acesso=chave, xml=xml)

    def consultar_dps(self, id_dps, cert):
        chave = self.autorizadas.get(id_dps)
        if not chave:
            return None
        return RespostaSefin(sucesso=True, chave_acesso=chave,
                             xml=f"<NFSe simulada='true'><chNFSe>{chave}</chNFSe></NFSe>")

    def enviar_evento(self, chave_acesso, xml_assinado, cert):
        self.enviados.append(xml_assinado)
        if self.rejeitar_com:
            return RespostaSefin(sucesso=False, mensagens=[self.rejeitar_com])
        return RespostaSefin(sucesso=True, chave_acesso=chave_acesso)


    def consultar_servico_municipio(self, municipio_ibge, codigo, cert):
        return ServicoNaPrefeitura(administrado=True, conveniado=True,
                                   mensagens=["Modo simulação: a prefeitura não foi consultada."])


class SefinNacional:
    def __init__(self, url_base: str, url_adn: str | None = None, timeout: int = 40):
        self.url_base = url_base.rstrip("/")
        self.url_adn = (url_adn or url_base.replace("://sefin.", "://adn.").split("/Sefin")[0]).rstrip("/")
        self.timeout = timeout

    def _chamar(self, metodo: str, caminho: str, cert: Certificado, corpo: dict | None = None,
                base: str | None = None) -> requests.Response:
        # requests precisa do certificado em arquivos PEM: criamos temporários
        # só durante a chamada, com permissão restrita, e apagamos em seguida.
        with tempfile.TemporaryDirectory() as pasta:
            crt, key = Path(pasta, "c.pem"), Path(pasta, "k.pem")
            crt.write_bytes(cert.pem_certificado())
            key.touch(mode=0o600)
            key.write_bytes(cert.pem_chave())
            try:
                return requests.request(
                    metodo, f"{base or self.url_base}{caminho}", json=corpo, cert=(str(crt), str(key)),
                    timeout=self.timeout, headers={"Accept": "application/json"},
                )
            except (requests.Timeout, requests.ConnectionError) as erro:
                raise SemResposta(
                    "A prefeitura não respondeu a tempo. Não emita de novo: "
                    "o Emitta vai conferir se a nota foi gerada."
                ) from erro

    @staticmethod
    def _mensagens(resp: requests.Response) -> list[str]:
        try:
            dados = resp.json()
        except ValueError:
            return [f"HTTP {resp.status_code}: {resp.text[:300]}"]
        erros = dados.get("erros") or dados.get("erro") or []
        if isinstance(erros, dict):
            erros = [erros]
        mensagens = []
        for e in erros:
            codigo = e.get("codigo") or e.get("Codigo") or ""
            descricao = e.get("descricao") or e.get("Descricao") or ""
            complemento = e.get("complemento") or e.get("Complemento") or ""
            mensagens.append(" ".join(x for x in (codigo, descricao, complemento) if x).strip())
            if codigo == "E0312":
                mensagens.append("Dica: a prefeitura da empresa não aceita este código de serviço. "
                                 "No painel do contador, use \"Conferir na prefeitura\" para testar outro código.")
        return mensagens or [f"HTTP {resp.status_code}"]

    def enviar_dps(self, xml_assinado, cert):
        resp = self._chamar("POST", "/nfse", cert, {"dpsXmlGZipB64": compactar(xml_assinado)})
        if resp.status_code >= 500:
            raise SemResposta("O sistema da prefeitura está instável. O Emitta vai conferir a nota.")
        if not resp.ok:
            return RespostaSefin(sucesso=False, mensagens=self._mensagens(resp))
        dados = resp.json()
        xml = dados.get("nfseXmlGZipB64")
        return RespostaSefin(sucesso=True, chave_acesso=dados.get("chaveAcesso"),
                             xml=descompactar(xml) if xml else None)

    def consultar_dps(self, id_dps, cert):
        """Pergunta ao governo se esta DPS já virou NFS-e (devolve None se não)."""
        resp = self._chamar("GET", f"/dps/{id_dps}", cert)
        if resp.status_code == 404:
            return None
        if not resp.ok:
            raise SemResposta("Não foi possível confirmar a nota com a prefeitura agora.")
        chave = resp.json().get("chaveAcesso")
        if not chave:
            return None
        xml = None
        nota = self._chamar("GET", f"/nfse/{chave}", cert)
        if nota.ok and nota.json().get("nfseXmlGZipB64"):
            xml = descompactar(nota.json()["nfseXmlGZipB64"])
        return RespostaSefin(sucesso=True, chave_acesso=chave, xml=xml)

    def enviar_evento(self, chave_acesso, xml_assinado, cert):
        resp = self._chamar("POST", f"/nfse/{chave_acesso}/eventos", cert,
                            {"pedidoRegistroEventoXmlGZipB64": compactar(xml_assinado)})
        if not resp.ok:
            return RespostaSefin(sucesso=False, mensagens=self._mensagens(resp))
        dados = resp.json()
        xml = dados.get("eventoXmlGZipB64")
        return RespostaSefin(sucesso=True, chave_acesso=chave_acesso,
                             xml=descompactar(xml) if xml else None)

    def consultar_servico_municipio(self, municipio_ibge: str, codigo: str, cert) -> ServicoNaPrefeitura:
        """Pergunta ao governo (ADN, /parametrizacao) se o município aceita este
        serviço e com quais complementos municipais (cTribMun). Evita a recusa
        E0312, que acontece quando a prefeitura exige o complemento."""
        from concurrent.futures import ThreadPoolExecutor
        from datetime import date

        def get(caminho):
            try:
                r = self._chamar("GET", f"/parametrizacao/{caminho}", cert, base=self.url_adn)
            except SemResposta:
                return None
            print(f"[parametrizacao] {caminho} -> HTTP {r.status_code}", flush=True)
            return r

        conv = get(f"{municipio_ibge}/convenio")
        conveniado = None if conv is None else (True if conv.ok else False if conv.status_code == 404 else None)

        candidatos = ["000"] + [f"{n:03d}" for n in range(1, 31)]
        hoje = date.today().isoformat()

        def consulta(municipal, modo):
            cod = codigo_servico_api(codigo, municipal)
            caminho = (f"{municipio_ibge}/{cod}/historicoaliquotas" if modo == "historico"
                       else f"{municipio_ibge}/{cod}/{hoje}/aliquota")
            return municipal, get(caminho)

        aceitos, aliquotas, mensagens, algum_erro = [], {}, [], False
        for modo in ("historico", "aliquota"):
            with ThreadPoolExecutor(max_workers=8) as pool:
                resultados = list(pool.map(lambda m: consulta(m, modo), candidatos))
            for municipal, r in resultados:
                if r is None or r.status_code >= 500:
                    algum_erro = True
                    continue
                if r.ok:
                    try:
                        dados = r.json()
                    except ValueError:
                        dados = {}
                    if dados.get("aliquotas") or dados.get("aliquota") is not None or not dados.get("mensagem"):
                        aceitos.append(municipal)
                        aliquotas[municipal] = dados.get("aliquotas") or dados.get("aliquota")
                    elif dados.get("mensagem"):
                        mensagens.append(dados["mensagem"])
            if aceitos:
                break
        if aceitos:
            return ServicoNaPrefeitura(administrado=True, conveniado=conveniado if conveniado is not None else True,
                                       aliquotas=aliquotas, mensagens=mensagens[:2],
                                       codigos_municipais=[m for m in aceitos if m != "000"])
        if algum_erro:
            return ServicoNaPrefeitura(administrado=None, conveniado=conveniado,
                                       mensagens=["O governo não respondeu a todas as consultas. Tente de novo em instantes."])
        return ServicoNaPrefeitura(administrado=False, conveniado=conveniado, mensagens=mensagens[:2])
