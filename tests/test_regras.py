from datetime import datetime, timedelta

import pytest

from app import regras


def test_trava_bloqueia_servico_nao_liberado():
    with pytest.raises(regras.ServicoNaoLiberado):
        regras.verificar_servico_liberado({"010101"}, "170101")


def test_trava_permite_servico_liberado():
    regras.verificar_servico_liberado({"010101"}, "010101")


@pytest.mark.parametrize("entrada, centavos", [
    ("1500", 150000),
    ("1500.00", 150000),
    ("1.500,00", 150000),
    ("R$ 99,90", 9990),
    ("0,01", 1),
])
def test_valor_em_centavos(entrada, centavos):
    assert regras.valor_em_centavos(entrada) == centavos


@pytest.mark.parametrize("entrada", ["0", "-10", "abc", ""])
def test_valor_invalido(entrada):
    with pytest.raises(regras.ValorInvalido):
        regras.valor_em_centavos(entrada)


def test_iss_arredonda_para_o_centavo():
    assert regras.calcular_iss(150000, "3") == 4500
    assert regras.calcular_iss(3333, "2.5") == 83  # 83,325 -> 83


def test_documentos():
    assert regras.validar_documento("11.222.333/0001-81") == regras.Documento("CNPJ", "11222333000181")
    assert regras.validar_documento("529.982.247-25").tipo == "CPF"
    for ruim in ["11.222.333/0001-80", "111.111.111-11", "123", ""]:
        with pytest.raises(regras.DocumentoInvalido):
            regras.validar_documento(ruim)


def test_prazo_de_cancelamento():
    emitida = datetime(2026, 11, 1)
    regras.verificar_prazo_cancelamento(emitida, 30, emitida + timedelta(days=29))
    regras.verificar_prazo_cancelamento(emitida, None, emitida + timedelta(days=999))
    with pytest.raises(regras.ForaDoPrazo):
        regras.verificar_prazo_cancelamento(emitida, 30, emitida + timedelta(days=31))


def test_motivo_outro_exige_texto():
    assert regras.motivo_cancelamento("erro", None) == ("1", "Erro na emissão")
    with pytest.raises(regras.ErroDeNegocio):
        regras.motivo_cancelamento("outro", "curto")
    with pytest.raises(regras.ErroDeNegocio):
        regras.motivo_cancelamento("inventado", None)
