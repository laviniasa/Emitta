"""Configurações lidas de variáveis de ambiente (veja .env.example)."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path

URLS_SEFIN = {
    # Conferir na documentação oficial (gov.br/nfse) antes de usar.
    "homologacao": "https://sefin.producaorestrita.nfse.gov.br/SefinNacional",
    "producao": "https://sefin.nfse.gov.br/SefinNacional",
}

URLS_ADN = {
    # Ambiente de Dados Nacional: onde ficam os parâmetros municipais (parametrizacao).
    "homologacao": "https://adn.producaorestrita.nfse.gov.br",
    "producao": "https://adn.nfse.gov.br",
}

AMBIENTES = ("simulacao", "homologacao", "producao")
# NT 009 (leiaute com finNFSe) entra na produção do governo nesta data
INICIO_NT009_PRODUCAO = date(2026, 12, 1)


@dataclass(frozen=True)
class Config:
    ambiente: str
    banco: Path
    pasta_certificados: Path
    pasta_xsd: Path | None
    versao_aplicativo: str = "Emitta-0.1"

    @property
    def url_sefin(self) -> str | None:
        return URLS_SEFIN.get(self.ambiente)

    @property
    def url_adn(self) -> str | None:
        return URLS_ADN.get(self.ambiente)

    @property
    def leiaute(self) -> str:
        """Leiaute da DPS aceito pelo ambiente do governo hoje.

        "nt009": leiaute novo (NT 009, com finNFSe), na produção restrita (homologação) e,
        a partir de 01/12/2026, também na produção.
        "nt004": leiaute anterior, o único aceito na produção até 30/11/2026: sem finNFSe,
        sem o grupo IBS/CBS (opcional) e com nPedRegEvento no cancelamento.
        NFSE_LEIAUTE=nt004|nt009 força um dos dois (caso o governo mude o cronograma).
        """
        forcado = os.getenv("NFSE_LEIAUTE", "").lower()
        if forcado in ("nt004", "nt009"):
            return forcado
        if self.ambiente != "producao":
            return "nt009"
        hoje = datetime.now(timezone(timedelta(hours=-3))).date()
        return "nt009" if hoje >= INICIO_NT009_PRODUCAO else "nt004"

    @property
    def tp_amb(self) -> str:
        """1 = produção, 2 = homologação (produção restrita)."""
        return "1" if self.ambiente == "producao" else "2"


def carregar_config() -> Config:
    ambiente = os.getenv("NFSE_AMBIENTE", "simulacao").lower()
    if ambiente not in AMBIENTES:
        raise ValueError(f"NFSE_AMBIENTE deve ser um de {AMBIENTES}, não {ambiente!r}")
    xsd = os.getenv("NFSE_PASTA_XSD")
    return Config(
        ambiente=ambiente,
        banco=Path(os.getenv("NFSE_BANCO", "dados/emissor.db")),
        pasta_certificados=Path(os.getenv("NFSE_PASTA_CERTIFICADOS", "certificados")),
        pasta_xsd=Path(xsd) if xsd else Path(__file__).parent / "xsd",  # XSD oficial v1.01 junto do app
    )
