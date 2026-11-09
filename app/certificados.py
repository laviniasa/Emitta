"""Onde o sistema encontra o certificado A1 de cada cliente.

Convenção: `certificados/<CNPJ>.pfx` e a senha na variável de ambiente
`CERT_SENHA_<CNPJ>`. Nunca suba .pfx ou senhas para o GitHub (.gitignore).

No modo simulação, se o cliente não tiver certificado, é gerado um
certificado de teste para que a assinatura seja exercitada mesmo assim.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from .assinatura import Certificado, ErroCertificado, carregar_pfx


@lru_cache
def certificado_de_teste() -> Certificado:
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CERTIFICADO DE TESTE - SEM VALOR")])
    agora = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=1))
        .not_valid_after(agora + timedelta(days=365))
        .sign(chave, hashes.SHA256())
    )
    return Certificado(chave=chave, certificado=cert)


class ProvedorCertificados:
    def __init__(self, pasta: Path, permitir_teste: bool):
        self.pasta = Path(pasta)
        self.permitir_teste = permitir_teste

    def para(self, cnpj: str) -> Certificado:
        arquivo = self.pasta / f"{cnpj}.pfx"
        if arquivo.exists():
            senha = os.getenv(f"CERT_SENHA_{cnpj}")
            if senha is None:
                raise ErroCertificado(f"Defina a variável CERT_SENHA_{cnpj} com a senha do certificado.")
            return carregar_pfx(arquivo, senha)
        if self.permitir_teste:
            return certificado_de_teste()
        raise ErroCertificado(
            "Certificado digital da empresa não cadastrado. Fale com o seu contador."
        )
