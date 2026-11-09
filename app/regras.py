"""Regras de negócio puras (sem banco, sem rede).

Tudo aqui é fácil de testar e é onde ficam as decisões que protegem o cliente:
- só emitir serviço que o contador liberou;
- recusar CNPJ/CPF inválido antes de mandar para a prefeitura;
- calcular o ISS;
- saber se ainda dá para cancelar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


class ErroDeNegocio(Exception):
    """Erro com mensagem pronta para mostrar ao usuário."""


class ServicoNaoLiberado(ErroDeNegocio):
    pass


class DocumentoInvalido(ErroDeNegocio):
    pass


class ValorInvalido(ErroDeNegocio):
    pass


class ForaDoPrazo(ErroDeNegocio):
    pass


class NotaNaoCancelavel(ErroDeNegocio):
    pass


# ---------------------------------------------------------------- serviços

def verificar_servico_liberado(codigos_liberados: set[str], codigo: str) -> None:
    """A trava: o servidor confere, não só a tela do app."""
    if codigo not in codigos_liberados:
        raise ServicoNaoLiberado(
            "Este serviço não está liberado para a sua empresa. "
            "Peça ao seu contador para liberar."
        )


# ---------------------------------------------------------------- valores

def valor_em_centavos(valor: str | int | float | Decimal) -> int:
    """Aceita '1500', '1500.00', '1.500,00' ou Decimal e devolve centavos."""
    if isinstance(valor, str):
        texto = valor.strip().replace("R$", "").strip()
        if "," in texto:  # formato brasileiro: 1.500,00
            texto = texto.replace(".", "").replace(",", ".")
        valor = texto
    try:
        decimal = Decimal(str(valor))
    except InvalidOperation:
        raise ValorInvalido("Valor inválido. Use, por exemplo, 1500,00.") from None
    if decimal <= 0:
        raise ValorInvalido("O valor do serviço precisa ser maior que zero.")
    centavos = (decimal * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(centavos)


def calcular_iss(valor_centavos: int, aliquota_percentual: Decimal | float | str) -> int:
    aliquota = Decimal(str(aliquota_percentual))
    iss = Decimal(valor_centavos) * aliquota / Decimal(100)
    return int(iss.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def centavos_para_texto(centavos: int) -> str:
    """1500,00 -> '1500.00' (formato do XML)."""
    return f"{centavos // 100}.{centavos % 100:02d}"


# ---------------------------------------------------------------- CNPJ / CPF

def somente_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")


def _cpf_valido(cpf: str) -> bool:
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for tamanho in (9, 10):
        soma = sum(int(cpf[i]) * (tamanho + 1 - i) for i in range(tamanho))
        digito = (soma * 10) % 11 % 10
        if digito != int(cpf[tamanho]):
            return False
    return True


def _cnpj_valido(cnpj: str) -> bool:
    if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
        return False
    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6] + pesos1
    for pesos, posicao in ((pesos1, 12), (pesos2, 13)):
        soma = sum(int(cnpj[i]) * pesos[i] for i in range(posicao))
        resto = soma % 11
        digito = 0 if resto < 2 else 11 - resto
        if digito != int(cnpj[posicao]):
            return False
    return True


@dataclass(frozen=True)
class Documento:
    tipo: str  # "CPF" ou "CNPJ"
    numero: str  # só dígitos


def validar_documento(texto: str) -> Documento:
    """Confere os dígitos verificadores antes de enviar.

    Evita a rejeição mais comum ("CNPJ do tomador inválido").
    """
    numero = somente_digitos(texto)
    if len(numero) == 11 and _cpf_valido(numero):
        return Documento("CPF", numero)
    if len(numero) == 14 and _cnpj_valido(numero):
        return Documento("CNPJ", numero)
    raise DocumentoInvalido(
        "CNPJ ou CPF do cliente inválido. Confira os números digitados."
    )


# ---------------------------------------------------------------- cancelamento

# Códigos de motivo do evento de cancelamento (e101101).
# Conferir com o leiaute oficial antes de ir para homologação.
MOTIVOS_CANCELAMENTO = {
    "erro": ("1", "Erro na emissão"),
    "nao_prestado": ("2", "Serviço não prestado"),
    "outro": ("9", "Outros"),
}


def motivo_cancelamento(motivo: str, texto: str | None) -> tuple[str, str]:
    """Devolve (código, descrição) do motivo, conferindo o texto quando é 'outro'."""
    if motivo not in MOTIVOS_CANCELAMENTO:
        raise ErroDeNegocio("Escolha um motivo de cancelamento da lista.")
    codigo, descricao = MOTIVOS_CANCELAMENTO[motivo]
    if motivo == "outro":
        texto = (texto or "").strip()
        if len(texto) < 15:
            raise ErroDeNegocio(
                "Explique o motivo em uma frase (pelo menos 15 letras)."
            )
        descricao = texto
    return codigo, descricao


def verificar_prazo_cancelamento(
    emitida_em: datetime, prazo_dias: int | None, agora: datetime
) -> None:
    """Cada município define seu prazo. Sem prazo cadastrado, deixamos tentar
    e a própria API do governo decide."""
    if prazo_dias is None:
        return
    if agora - emitida_em > timedelta(days=prazo_dias):
        raise ForaDoPrazo(
            f"Passou o prazo de {prazo_dias} dias que a sua prefeitura dá para "
            "cancelar direto. É preciso pedir análise fiscal ao município; "
            "fale com o seu contador."
        )


def verificar_situacao_cancelavel(situacao: str) -> None:
    if situacao == "cancelada":
        raise NotaNaoCancelavel("Esta nota já está cancelada.")
    if situacao != "autorizada":
        raise NotaNaoCancelavel("Só é possível cancelar notas autorizadas.")
