"""Peças de segurança, só com a biblioteca padrão do Python.

- Senhas: scrypt com sal aleatório (resistente a força bruta com GPU).
- Tokens de sessão: 256 bits aleatórios; no banco fica só o hash SHA-256,
  então um vazamento do banco não entrega sessões válidas.
- 2FA: códigos de 6 dígitos (TOTP, RFC 6238), compatível com Google
  Authenticator, Microsoft Authenticator, Authy etc.
- Limitador de tentativas por IP, em memória.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import threading
import time
from collections import defaultdict, deque
from urllib.parse import quote

# ---------------------------------------------------------------- senhas

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 64}
TAMANHO_MINIMO_SENHA = 10

_SENHAS_COMUNS = {
    "1234567890", "12345678910", "0123456789", "senha12345", "senha123456",
    "password123", "qwertyuiop", "abcdefghij", "1q2w3e4r5t", "1111111111",
    "emitta1234", "minhasenha", "trocar1234", "admin12345",
}


def hash_senha(senha: str) -> str:
    sal = secrets.token_bytes(16)
    chave = hashlib.scrypt(senha.encode(), salt=sal, maxmem=64 * 1024 * 1024, **_SCRYPT)
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT["n"], _SCRYPT["r"], _SCRYPT["p"],
        base64.b64encode(sal).decode(), base64.b64encode(chave).decode(),
    )


def verificar_senha(senha: str, guardado: str) -> bool:
    try:
        _, n, r, p, sal, chave = guardado.split("$")
        calculada = hashlib.scrypt(
            senha.encode(), salt=base64.b64decode(sal), n=int(n), r=int(r), p=int(p),
            dklen=len(base64.b64decode(chave)), maxmem=64 * 1024 * 1024,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calculada, base64.b64decode(chave))


# Usado quando o e-mail não existe, para o tempo de resposta ser o mesmo
# (assim ninguém descobre quais e-mails têm conta medindo o tempo).
HASH_FALSO = hash_senha(secrets.token_urlsafe(16))


def problema_na_senha(senha: str, email: str = "") -> str | None:
    """Devolve o motivo de a senha ser fraca, ou None se estiver boa."""
    if len(senha) < TAMANHO_MINIMO_SENHA:
        return f"A senha precisa ter pelo menos {TAMANHO_MINIMO_SENHA} caracteres."
    if len(senha) > 200:
        return "A senha é longa demais."
    if senha.lower() in _SENHAS_COMUNS or len(set(senha)) < 4:
        return "Essa senha é fácil de adivinhar. Escolha outra."
    usuario = email.split("@")[0].lower()
    if usuario and len(usuario) >= 4 and usuario in senha.lower():
        return "A senha não pode conter o seu e-mail."
    return None


def senha_temporaria() -> str:
    """Senha provisória legível (sem 0/O, 1/l), para o primeiro acesso da empresa."""
    alfabeto = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"
    partes = ["".join(secrets.choice(alfabeto) for _ in range(4)) for _ in range(3)]
    return "-".join(partes)


# ---------------------------------------------------------------- tokens

def gerar_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------- 2FA (TOTP)

PASSO_TOTP = 30


def gerar_segredo_totp() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _codigo_totp(segredo: str, passo: int) -> str:
    chave = base64.b32decode(segredo + "=" * (-len(segredo) % 8))
    mac = hmac.new(chave, struct.pack(">Q", passo), hashlib.sha1).digest()
    deslocamento = mac[-1] & 0x0F
    numero = struct.unpack(">I", mac[deslocamento:deslocamento + 4])[0] & 0x7FFFFFFF
    return f"{numero % 1_000_000:06d}"


def passo_atual(agora: float | None = None) -> int:
    return int((agora if agora is not None else time.time()) // PASSO_TOTP)


def conferir_totp(segredo: str, codigo: str, ultimo_passo_usado: int | None, agora: float | None = None) -> int | None:
    """Confere o código aceitando 30 s de diferença de relógio. Devolve o passo
    usado (para impedir reaproveitar o mesmo código) ou None se inválido."""
    codigo = "".join(ch for ch in (codigo or "") if ch.isdigit())
    if len(codigo) != 6:
        return None
    atual = passo_atual(agora)
    for passo in (atual - 1, atual, atual + 1):
        if ultimo_passo_usado is not None and passo <= ultimo_passo_usado:
            continue
        if hmac.compare_digest(_codigo_totp(segredo, passo), codigo):
            return passo
    return None


def uri_totp(segredo: str, email: str, emissor: str = "Emitta") -> str:
    rotulo = quote(f"{emissor}:{email}")
    return f"otpauth://totp/{rotulo}?secret={segredo}&issuer={quote(emissor)}&digits=6&period={PASSO_TOTP}"


# ---------------------------------------------------------------- limitador

class LimitadorTentativas:
    """No máximo `limite` tentativas por chave (ex.: IP) a cada `janela` segundos."""

    def __init__(self, limite: int = 10, janela: int = 15 * 60):
        self.limite = limite
        self.janela = janela
        self._registros: dict[str, deque] = defaultdict(deque)
        self._trava = threading.Lock()

    def permitir(self, chave: str, agora: float | None = None) -> bool:
        agora = agora if agora is not None else time.monotonic()
        with self._trava:
            fila = self._registros[chave]
            while fila and agora - fila[0] > self.janela:
                fila.popleft()
            if len(fila) >= self.limite:
                return False
            fila.append(agora)
            return True

    def limpar(self, chave: str) -> None:
        with self._trava:
            self._registros.pop(chave, None)
