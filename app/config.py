"""Configurações lidas de variáveis de ambiente (veja .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

URLS_SEFIN = {
    # Conferir na documentação oficial (gov.br/nfse) antes de usar.
    "homologacao": "https://sefin.producaorestrita.nfse.gov.br/SefinNacional",
    "producao": "https://sefin.nfse.gov.br/SefinNacional",
}

AMBIENTES = ("simulacao", "homologacao", "producao")


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
