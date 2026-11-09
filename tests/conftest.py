import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# Garante que importar app.api não cria arquivo de banco.
os.environ.setdefault("NFSE_BANCO", ":memory:")
os.environ.setdefault("NFSE_AMBIENTE", "simulacao")

from app.certificados import ProvedorCertificados  # noqa: E402
from app.config import Config  # noqa: E402
from app.emissao import ServicoEmissao  # noqa: E402
from app.repositorio import Repositorio  # noqa: E402
from app.sefin import SefinSimulada  # noqa: E402

FUSO = timezone(timedelta(hours=-3))
CNPJ_PRESTADOR = "11222333000181"  # CNPJ de exemplo com dígitos válidos
CNPJ_TOMADOR = "11444777000161"


class Relogio:
    def __init__(self):
        self.agora = datetime(2026, 11, 9, 13, 40, tzinfo=FUSO)

    def __call__(self):
        return self.agora

    def avancar(self, **kw):
        self.agora += timedelta(**kw)


@pytest.fixture
def relogio():
    return Relogio()


@pytest.fixture
def sefin():
    return SefinSimulada()


@pytest.fixture
def servico(sefin, relogio, tmp_path):
    config = Config(ambiente="simulacao", banco=Path(":memory:"), pasta_certificados=tmp_path, pasta_xsd=None)
    return ServicoEmissao(
        repo=Repositorio(":memory:"),
        sefin=sefin,
        config=config,
        certificados=ProvedorCertificados(tmp_path, permitir_teste=True),
        relogio=relogio,
    )


@pytest.fixture
def cliente(servico):
    c = servico.repo.criar_cliente(
        cnpj=CNPJ_PRESTADOR,
        razao_social="Minha Empresa ME",
        municipio_ibge="3550308",
        municipio_nome="São Paulo",
        aliquota_iss="3",
        prazo_cancelamento_dias=30,
    )
    servico.repo.definir_servicos_liberados(
        c.id, [("010101", "Desenvolvimento de sistemas"), ("010701", "Suporte técnico")]
    )
    return c
