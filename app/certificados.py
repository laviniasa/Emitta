"""Certificados digitais A1 das empresas.

O contador envia o arquivo .pfx e a senha pelo painel. Os dois são guardados
CRIPTOGRAFADOS no banco (Fernet: AES-128 + HMAC), com a chave na variável de
ambiente EMITTA_CHAVE_CERTIFICADOS, que fica só no servidor. Quem tiver acesso
ao banco sem essa chave não consegue usar os certificados.

No modo simulação, se a empresa não tiver certificado, é gerado um certificado
de teste para que a assinatura seja exercitada mesmo assim.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from cryptography import x509
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from .assinatura import Certificado, ErroCertificado

# OID ICP-Brasil onde fica o CNPJ da empresa titular do e-CNPJ.
OID_CNPJ_ICP = "2.16.76.1.3.3"
TAMANHO_MAXIMO_PFX = 50 * 1024


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


def _cofre(chave: str | None = None) -> Fernet:
    chave = chave if chave is not None else os.getenv("EMITTA_CHAVE_CERTIFICADOS")
    if not chave:
        raise ErroCertificado(
            "O servidor ainda não está preparado para guardar certificados "
            "(falta a chave EMITTA_CHAVE_CERTIFICADOS)."
        )
    try:
        return Fernet(chave.encode())
    except ValueError:
        raise ErroCertificado("Chave EMITTA_CHAVE_CERTIFICADOS inválida.") from None


def cnpjs_do_certificado(cert: x509.Certificate) -> set[str]:
    """CNPJs que aparecem no certificado (no nome e no campo ICP-Brasil)."""
    encontrados: set[str] = set()
    for atributo in cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME):
        encontrados.update(re.findall(r"(?<![0-9A-Z])[0-9A-Z]{12}[0-9]{2}(?![0-9A-Z])", atributo.value.upper()))
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        for outro in san.get_values_for_type(x509.OtherName):
            if outro.type_id.dotted_string == OID_CNPJ_ICP:
                encontrados.update(re.findall(r"[0-9A-Z]{12}[0-9]{2}", outro.value.decode("latin-1", "ignore").upper()))
    except x509.ExtensionNotFound:
        pass
    return encontrados


def preparar_certificado(pfx: bytes, senha: str, cnpj_empresa: str, agora: datetime | None = None,
                         chave: str | None = None) -> dict:
    """Confere o .pfx (senha, validade, CNPJ) e devolve os dados cifrados para guardar."""
    if not pfx or len(pfx) > TAMANHO_MAXIMO_PFX:
        raise ErroCertificado("Envie o arquivo .pfx do certificado A1 (até 50 KB).")
    try:
        chave_privada, cert, _ = pkcs12.load_key_and_certificates(pfx, (senha or "").encode())
    except ValueError:
        raise ErroCertificado("Senha incorreta ou arquivo não é um certificado .pfx válido.") from None
    if chave_privada is None or cert is None:
        raise ErroCertificado("O arquivo não contém a chave do certificado. Exporte o A1 completo (.pfx).")
    agora = agora or datetime.now(timezone.utc)
    if cert.not_valid_after_utc < agora:
        raise ErroCertificado(f"Este certificado venceu em {cert.not_valid_after_utc:%d/%m/%Y}.")
    cnpjs = cnpjs_do_certificado(cert)
    if cnpjs and cnpj_empresa not in cnpjs:
        raise ErroCertificado("Este certificado é de outra empresa (o CNPJ não confere).")
    titular = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    cofre = _cofre(chave)
    return {
        "pfx_cifrado": cofre.encrypt(pfx),
        "senha_cifrada": cofre.encrypt((senha or "").encode()),
        "validade": cert.not_valid_after_utc.isoformat(),
        "titular": titular[0].value if titular else "",
    }


def abrir_certificado(pfx_cifrado: bytes, senha_cifrada: bytes, chave: str | None = None) -> Certificado:
    cofre = _cofre(chave)
    try:
        pfx = cofre.decrypt(pfx_cifrado)
        senha = cofre.decrypt(senha_cifrada).decode()
    except InvalidToken:
        raise ErroCertificado("Não foi possível abrir o certificado guardado (chave do servidor mudou?).") from None
    chave_privada, cert, _ = pkcs12.load_key_and_certificates(pfx, senha.encode())
    return Certificado(chave=chave_privada, certificado=cert)


class ProvedorCertificados:
    def __init__(self, permitir_teste: bool, chave: str | None = None):
        self.permitir_teste = permitir_teste
        self.chave = chave

    def para(self, cliente) -> Certificado:
        if cliente.cert_pfx_cifrado:
            cert = abrir_certificado(cliente.cert_pfx_cifrado, cliente.cert_senha_cifrada, self.chave)
            if cert.vence_em < datetime.now(timezone.utc):
                raise ErroCertificado("O certificado digital da empresa venceu. Fale com o seu contador.")
            return cert
        if self.permitir_teste:
            return certificado_de_teste()
        raise ErroCertificado(
            "Certificado digital da empresa não cadastrado. Fale com o seu contador."
        )
