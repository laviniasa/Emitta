"""Comunicação com a API do Emissor Nacional (Sefin Nacional).

Dois clientes com a mesma interface:
- `SefinSimulada`: não acessa a internet, para desenvolver e testar telas.
- `SefinNacional`: chama a API de verdade, autenticando com o certificado A1.

Rotas e nomes de campos JSON: conferir no Swagger oficial do ambiente de
produção restrita antes do primeiro teste real.
"""

from __future__ import annotations

import base64
import gzip
import os
import random
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import requests

from .assinatura import Certificado


@dataclass
class RespostaSefin:
    sucesso: bool
    chave_acesso: str | None = None
    xml: str | None = None
    mensagens: list[str] = field(default_factory=list)


class ClienteSefin(Protocol):
    def enviar_dps(self, xml_assinado: bytes, cert: Certificado | None) -> RespostaSefin: ...

    def enviar_evento(
        self, chave_acesso: str, xml_assinado: bytes, cert: Certificado | None
    ) -> RespostaSefin: ...


def compactar(xml: bytes) -> str:
    return base64.b64encode(gzip.compress(xml)).decode()


def descompactar(texto: str) -> str:
    return gzip.decompress(base64.b64decode(texto)).decode("utf-8")


class SefinSimulada:
    """Imita a API: autoriza tudo, a menos que `rejeitar_com` esteja definido."""

    def __init__(self, rejeitar_com: str | None = None):
        self.rejeitar_com = rejeitar_com
        self.enviados: list[bytes] = []

    def enviar_dps(self, xml_assinado, cert):
        self.enviados.append(xml_assinado)
        if self.rejeitar_com:
            return RespostaSefin(sucesso=False, mensagens=[self.rejeitar_com])
        chave = "".join(random.choice("0123456789") for _ in range(50))
        xml = f"<NFSe simulada='true'><chNFSe>{chave}</chNFSe></NFSe>"
        return RespostaSefin(sucesso=True, chave_acesso=chave, xml=xml)

    def enviar_evento(self, chave_acesso, xml_assinado, cert):
        self.enviados.append(xml_assinado)
        if self.rejeitar_com:
            return RespostaSefin(sucesso=False, mensagens=[self.rejeitar_com])
        return RespostaSefin(sucesso=True, chave_acesso=chave_acesso)


class SefinNacional:
    def __init__(self, url_base: str, timeout: int = 30):
        self.url_base = url_base.rstrip("/")
        self.timeout = timeout

    def _post(self, caminho: str, corpo: dict, cert: Certificado) -> requests.Response:
        # requests precisa do certificado em arquivos PEM: criamos temporários
        # só durante a chamada e apagamos em seguida.
        with tempfile.TemporaryDirectory() as pasta:
            crt, key = Path(pasta, "c.pem"), Path(pasta, "k.pem")
            crt.write_bytes(cert.pem_certificado())
            key.write_bytes(cert.pem_chave())
            os.chmod(key, 0o600)
            return requests.post(
                f"{self.url_base}{caminho}", json=corpo, cert=(str(crt), str(key)),
                timeout=self.timeout,
            )

    @staticmethod
    def _ler(resp: requests.Response) -> RespostaSefin:
        try:
            dados = resp.json()
        except ValueError:
            return RespostaSefin(sucesso=False, mensagens=[f"HTTP {resp.status_code}: {resp.text[:300]}"])
        if resp.ok:
            xml = dados.get("nfseXmlGZipB64") or dados.get("eventoXmlGZipB64")
            return RespostaSefin(
                sucesso=True,
                chave_acesso=dados.get("chaveAcesso"),
                xml=descompactar(xml) if xml else None,
            )
        erros = dados.get("erros") or dados.get("erro") or []
        if isinstance(erros, dict):
            erros = [erros]
        mensagens = [
            f"{e.get('codigo') or e.get('Codigo', '')} {e.get('descricao') or e.get('Descricao', '')}".strip()
            for e in erros
        ] or [f"HTTP {resp.status_code}"]
        return RespostaSefin(sucesso=False, mensagens=mensagens)

    def enviar_dps(self, xml_assinado, cert):
        resp = self._post("/nfse", {"dpsXmlGZipB64": compactar(xml_assinado)}, cert)
        return self._ler(resp)

    def enviar_evento(self, chave_acesso, xml_assinado, cert):
        resp = self._post(
            f"/nfse/{chave_acesso}/eventos",
            {"pedidoRegistroEventoXmlGZipB64": compactar(xml_assinado)},
            cert,
        )
        return self._ler(resp)
