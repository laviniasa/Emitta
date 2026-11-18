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


def test_banco_aguenta_requisicoes_simultaneas(servico, cliente):
    """Várias threads lendo e gravando ao mesmo tempo não podem misturar resultados."""
    from concurrent.futures import ThreadPoolExecutor

    repo = servico.repo
    for i in range(5):
        emitir(servico, cliente)

    def trabalho(i):
        if i % 3 == 0:
            return repo.buscar_cliente(cliente.id).razao_social == "Minha Empresa ME"
        if i % 3 == 1:
            return len(repo.servicos_liberados(cliente.id)) == 2
        return len(repo.listar_notas(cliente.id)) >= 5

    with ThreadPoolExecutor(max_workers=16) as pool:
        assert all(pool.map(trabalho, range(600)))


def test_pula_numero_ja_usado_no_governo(servico, cliente, sefin):
    """Banco zerado (ou outro sistema já emitiu): o governo recusa o número com E0014
    e o Emitta passa sozinho para o próximo, sem deixar lixo na lista de notas."""
    from app.emissao import id_dps
    for n in (1, 2, 3):
        sefin.autorizadas[id_dps(cliente.municipio_ibge, cliente.cnpj, cliente.serie_dps, n)] = "x" * 50
    nota = emitir(servico, cliente, chave_envio="abc-123")
    assert nota.situacao == "autorizada" and nota.numero_dps == 4
    assert [n.numero_dps for n in servico.repo.listar_notas(cliente.id)] == [4]
    assert emitir(servico, cliente, chave_envio="abc-123").id == nota.id  # repetir o envio não duplica
    assert emitir(servico, cliente).numero_dps == 5


def test_confere_na_prefeitura_antes_de_enviar(servico, cliente, sefin):
    """Fora da simulação: sem complemento guardado, o Emitta pergunta à prefeitura antes de enviar."""
    import dataclasses
    from lxml import etree
    from app.sefin import ServicoNaPrefeitura
    servico.config = dataclasses.replace(servico.config, ambiente="homologacao", pasta_xsd=None)
    respostas = {"010101": ServicoNaPrefeitura(administrado=True, codigos_municipais=["001", "002"]),
                 "170101": ServicoNaPrefeitura(administrado=False)}
    sefin.consultar_servico_municipio = lambda mun, cod, cert: respostas[cod]
    with servico.repo.con:
        servico.repo.con.execute("UPDATE clientes SET p_tot_trib_sn = '6.00' WHERE id = ?", (cliente.id,))
    nota = emitir(servico, cliente)
    assert nota.situacao == "autorizada"
    assert b"cTribMun>001</" in sefin.enviados[-1]
    assert {s["codigo"]: s["codigo_municipal"] for s in servico.repo.servicos_liberados(cliente.id)}["010101"] == "001"
    # serviço que a prefeitura não aceita: avisa sem enviar
    liberados = [(s["codigo"], s["apelido"], s["codigo_municipal"]) for s in servico.repo.servicos_liberados(cliente.id)]
    servico.repo.definir_servicos_liberados(cliente.id, liberados + [("170101", "Contabilidade")])
    antes = len(sefin.enviados)
    with pytest.raises(regras.ErroDeNegocio, match="não aceita este serviço"):
        emitir(servico, cliente, codigo_servico="170101")
    assert len(sefin.enviados) == antes


def test_soma_dos_tributos_lei_12741():
    from app import regras
    assert regras.tributos_aproximados(52400, "1", "0", 0) == (0, 0, 0)
    f, e, m = regras.tributos_aproximados(100000, "3", "6.00", 2000)
    assert (f, e, m) == (4000, 0, 2000)
    t = regras.texto_tributos(f, e, m)
    assert t == ("Totais aproximados dos Tributos cfe. Lei n° 12.741/2012: Federais: R$ 40,00; "
                 "Estaduais: R$ 0,00; Municipais: R$ 20,00;")
    assert regras.info_complementar_com_tributos(t, None) == t
    junto = regras.info_complementar_com_tributos(t, "Pagamento via Pix")
    assert junto == t + " / Pagamento via Pix"
    # nota corrigida: não repete a soma antiga
    assert regras.info_complementar_com_tributos(t, junto) == junto


def test_nota_leva_soma_dos_tributos_nas_informacoes(servico, cliente, sefin):
    from app.dps import texto_leiaute
    nota = emitir(servico, cliente, info_compl="Pagamento via Pix")
    assert nota.info_compl.startswith("Totais aproximados dos Tributos cfe. Lei n° 12.741/2012: Federais: R$")
    assert nota.info_compl.endswith(" / Pagamento via Pix")
    assert "<xInfComp>" + nota.info_compl.replace("&", "&amp;") in nota.xml_dps
    sem = emitir(servico, cliente)
    assert sem.info_compl.endswith("Municipais: R$ 0,00;") or "Municipais: R$" in sem.info_compl
