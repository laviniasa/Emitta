"""Consulta de dados públicos de CNPJ (Receita Federal, via BrasilAPI).

Usada para preencher automaticamente o nome do cliente na nota e o cadastro
da empresa no painel. Sem custo e sem certificado. Os resultados ficam em
memória por algumas horas para não repetir consultas.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

import requests

URL = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
VALIDADE_CACHE = 6 * 3600


class CnpjNaoEncontrado(Exception):
    pass


class ConsultaIndisponivel(Exception):
    pass


def _buscar_brasilapi(cnpj: str) -> dict:
    try:
        resp = requests.get(URL.format(cnpj=cnpj), timeout=8, headers={"User-Agent": "Emitta"})
    except requests.RequestException as erro:
        raise ConsultaIndisponivel("A consulta à Receita não respondeu.") from erro
    if resp.status_code == 404:
        raise CnpjNaoEncontrado("CNPJ não encontrado na Receita.")
    if not resp.ok:
        raise ConsultaIndisponivel("A consulta à Receita está indisponível agora.")
    return resp.json()


def _resumo(d: dict) -> dict:
    """Só os campos que o Emitta usa."""
    simples = d.get("opcao_pelo_simples")
    mei = d.get("opcao_pelo_mei")
    return {
        "razao_social": (d.get("razao_social") or "").strip(),
        "nome_fantasia": (d.get("nome_fantasia") or "").strip(),
        "municipio": (d.get("municipio") or "").strip().title(),
        "uf": d.get("uf") or "",
        "codigo_municipio_ibge": str(d.get("codigo_municipio_ibge") or ""),
        "situacao": d.get("descricao_situacao_cadastral") or "",
        "cnae_principal": {"codigo": str(d.get("cnae_fiscal") or ""), "descricao": d.get("cnae_fiscal_descricao") or ""},
        "regime": "2" if mei else ("3" if simples else ("1" if simples is False else "")),
    }


class ConsultaCnpj:
    def __init__(self, buscar: Callable[[str], dict] = _buscar_brasilapi):
        self.buscar = buscar
        self._cache: dict[str, tuple[float, dict]] = {}
        self._trava = threading.Lock()

    def consultar(self, cnpj: str) -> dict:
        agora = time.monotonic()
        with self._trava:
            guardado = self._cache.get(cnpj)
            if guardado and agora - guardado[0] < VALIDADE_CACHE:
                return guardado[1]
        resultado = _resumo(self.buscar(cnpj))
        with self._trava:
            self._cache[cnpj] = (agora, resultado)
        return resultado
