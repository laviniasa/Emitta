import pytest
from lxml import etree

from app import regras
from app.assinatura import verificar
from app.emissao import NotaNaoEncontrada, RejeitadaPelaPrefeitura

from .conftest import CNPJ_TOMADOR


def emitir(servico, cliente, **mudar):
    dados = dict(
        codigo_servico="010101", tomador_documento=CNPJ_TOMADOR,
        tomador_nome="Cliente Exemplo Ltda", valor="1.500,00",
    )
    dados.update(mudar)
    return servico.emitir(cliente.id, **dados)


def test_emite_nota_com_servico_liberado(servico, cliente, sefin):
    nota = emitir(servico, cliente)
    assert nota.situacao == "autorizada"
    assert nota.valor_centavos == 150000
    assert nota.iss_centavos == 4500
    assert len(nota.chave_acesso) == 50
    assert nota.descricao == "Análise e desenvolvimento de sistemas"  # veio do catálogo

    enviado = etree.fromstring(sefin.enviados[-1])
    assert verificar(enviado), "o XML enviado precisa estar assinado corretamente"


def test_numeracao_sequencial(servico, cliente):
    assert emitir(servico, cliente).numero_dps == 1
    assert emitir(servico, cliente).numero_dps == 2


def test_servico_bloqueado_nao_chega_ao_governo(servico, cliente, sefin):
    with pytest.raises(regras.ServicoNaoLiberado):
        emitir(servico, cliente, codigo_servico="170101")
    assert sefin.enviados == []


def test_documento_invalido_nao_chega_ao_governo(servico, cliente, sefin):
    with pytest.raises(regras.DocumentoInvalido):
        emitir(servico, cliente, tomador_documento="11.222.333/0001-00")
    assert sefin.enviados == []


def test_rejeicao_fica_no_historico(servico, cliente, sefin):
    sefin.rejeitar_com = "E0001 Teste de rejeição"
    with pytest.raises(RejeitadaPelaPrefeitura) as erro:
        emitir(servico, cliente)
    assert erro.value.nota.situacao == "rejeitada"
    assert servico.repo.listar_notas(cliente.id)[0].mensagem == "E0001 Teste de rejeição"


def test_cancelamento_no_prazo(servico, cliente, relogio):
    nota = emitir(servico, cliente)
    relogio.avancar(days=2)
    cancelada = servico.cancelar(cliente.id, nota.id, "nao_prestado")
    assert cancelada.situacao == "cancelada"
    assert cancelada.motivo_cancelamento == "Serviço não prestado"


def test_nao_cancela_duas_vezes(servico, cliente):
    nota = emitir(servico, cliente)
    servico.cancelar(cliente.id, nota.id, "erro")
    with pytest.raises(regras.NotaNaoCancelavel):
        servico.cancelar(cliente.id, nota.id, "erro")


def test_cancelamento_fora_do_prazo(servico, cliente, relogio, sefin):
    nota = emitir(servico, cliente)
    enviados_antes = len(sefin.enviados)
    relogio.avancar(days=31)
    with pytest.raises(regras.ForaDoPrazo):
        servico.cancelar(cliente.id, nota.id, "erro")
    assert len(sefin.enviados) == enviados_antes


def test_nao_cancela_nota_de_outra_empresa(servico, cliente):
    nota = emitir(servico, cliente)
    outro = servico.repo.criar_cliente(
        cnpj="11444777000161", razao_social="Outra ME", municipio_ibge="3550308",
        municipio_nome="São Paulo", aliquota_iss="2",
    )
    with pytest.raises(NotaNaoEncontrada):
        servico.cancelar(outro.id, nota.id, "erro")
