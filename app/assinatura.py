"""Assinatura digital XML (XMLDSig enveloped) com o certificado A1 (.pfx).

Feita com lxml + cryptography, sem dependências extras. O padrão do
ecossistema NFS-e é RSA-SHA1 (C14N inclusivo, transforms enveloped + C14N);
SHA-256 fica disponível em `ALGORITMO` se o governo passar a exigir.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from lxml import etree

from .regras import ErroDeNegocio

NS_DS = "http://www.w3.org/2000/09/xmldsig#"
C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
ENVELOPED = "http://www.w3.org/2000/09/xmldsig#enveloped-signature"

ALGORITMOS = {
    "sha256": (
        "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
        "http://www.w3.org/2001/04/xmlenc#sha256",
        hashes.SHA256,
    ),
    "sha1": (
        "http://www.w3.org/2000/09/xmldsig#rsa-sha1",
        "http://www.w3.org/2000/09/xmldsig#sha1",
        hashes.SHA1,
    ),
}
ALGORITMO = "sha1"


class ErroCertificado(ErroDeNegocio):
    pass


@dataclass
class Certificado:
    chave: rsa.RSAPrivateKey
    certificado: x509.Certificate

    @property
    def vence_em(self):
        return self.certificado.not_valid_after_utc

    def pem_certificado(self) -> bytes:
        return self.certificado.public_bytes(serialization.Encoding.PEM)

    def pem_chave(self) -> bytes:
        return self.chave.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )


def carregar_pfx(arquivo: Path, senha: str) -> Certificado:
    try:
        chave, cert, _ = pkcs12.load_key_and_certificates(
            Path(arquivo).read_bytes(), senha.encode()
        )
    except FileNotFoundError:
        raise ErroCertificado(f"Certificado não encontrado: {arquivo}") from None
    except ValueError:
        raise ErroCertificado("Senha do certificado incorreta ou arquivo inválido.") from None
    if chave is None or cert is None:
        raise ErroCertificado("O arquivo .pfx não contém chave e certificado.")
    return Certificado(chave=chave, certificado=cert)


def _c14n(el: etree._Element) -> bytes:
    """Canonicalização do elemento como se fosse um documento próprio.

    Canonicalizar o subelemento direto dentro da árvore pode gerar declarações
    xmlns="" a mais nos netos (namespace padrão redeclarado em <Signature>),
    e aí o hash calculado pelo governo não bate com o nosso. Reserializar o
    elemento antes leva junto só os namespaces em escopo.
    """
    isolado = etree.fromstring(etree.tostring(el))
    return etree.tostring(isolado, method="c14n", exclusive=False, with_comments=False)


def _ds(pai, tag, **attrs):
    return etree.SubElement(pai, f"{{{NS_DS}}}{tag}", **attrs)


def assinar(raiz: etree._Element, elemento_assinado: str, cert: Certificado) -> etree._Element:
    """Assina o elemento filho `elemento_assinado` (ex.: 'infDPS') pelo seu Id e
    insere <Signature> como último filho da raiz."""
    alvo = next(el for el in raiz if etree.QName(el).localname == elemento_assinado)
    ref_id = alvo.get("Id")
    alg_assinatura, alg_digest, hash_cls = ALGORITMOS[ALGORITMO]

    digest = hashes.Hash(hash_cls())
    digest.update(_c14n(alvo))
    valor_digest = base64.b64encode(digest.finalize()).decode()

    assinatura = etree.SubElement(raiz, f"{{{NS_DS}}}Signature", nsmap={None: NS_DS})
    info = _ds(assinatura, "SignedInfo")
    _ds(info, "CanonicalizationMethod", Algorithm=C14N)
    _ds(info, "SignatureMethod", Algorithm=alg_assinatura)
    ref = _ds(info, "Reference", URI=f"#{ref_id}")
    transforms = _ds(ref, "Transforms")
    _ds(transforms, "Transform", Algorithm=ENVELOPED)
    _ds(transforms, "Transform", Algorithm=C14N)
    _ds(ref, "DigestMethod", Algorithm=alg_digest)
    _ds(ref, "DigestValue").text = valor_digest

    valor = cert.chave.sign(_c14n(info), padding.PKCS1v15(), hash_cls())
    _ds(assinatura, "SignatureValue").text = base64.b64encode(valor).decode()
    key_info = _ds(assinatura, "KeyInfo")
    x509_data = _ds(key_info, "X509Data")
    der = cert.certificado.public_bytes(serialization.Encoding.DER)
    _ds(x509_data, "X509Certificate").text = base64.b64encode(der).decode()
    return raiz


def verificar(raiz: etree._Element) -> bool:
    """Confere digest e assinatura (útil em testes e para checar o que foi enviado)."""
    ns = {"ds": NS_DS}
    assinatura = raiz.find("ds:Signature", ns)
    info = assinatura.find("ds:SignedInfo", ns)
    ref_id = info.find("ds:Reference", ns).get("URI").lstrip("#")
    alvo = next(el for el in raiz if el.get("Id") == ref_id)
    alg = info.find("ds:SignatureMethod", ns).get("Algorithm")
    hash_cls = next(h for a, _, h in ALGORITMOS.values() if a == alg)

    digest = hashes.Hash(hash_cls())
    digest.update(_c14n(alvo))
    if base64.b64encode(digest.finalize()).decode() != info.find("ds:Reference/ds:DigestValue", ns).text:
        return False
    der = base64.b64decode(assinatura.find("ds:KeyInfo/ds:X509Data/ds:X509Certificate", ns).text)
    publica = x509.load_der_x509_certificate(der).public_key()
    try:
        publica.verify(
            base64.b64decode(assinatura.find("ds:SignatureValue", ns).text),
            _c14n(info),
            padding.PKCS1v15(),
            hash_cls(),
        )
    except Exception:
        return False
    return True
