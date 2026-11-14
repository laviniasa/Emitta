"""Consulta dos parâmetros municipais (se a prefeitura aceita o código de serviço)."""

from app.sefin import SefinNacional, SefinSimulada, codigo_servico_api


class Resp:
    def __init__(self, status, dados=None):
        self.status_code, self._dados = status, dados or {}
        self.ok = status < 400
        self.text = ""

    def json(self):
        return self._dados


def sefin_com(respostas):
    s = SefinNacional("https://sefin.exemplo/SefinNacional")
    chamadas = []

    def chamar(metodo, caminho, cert, corpo=None, base=None):
        chamadas.append(caminho)
        for trecho, resp in respostas.items():
            if trecho in caminho:
                return resp
        return Resp(404, {"erros": [{"codigo": "X", "descricao": "não achado"}]})

    s._chamar = chamar
    return s, chamadas


def test_formato_do_codigo():
    assert codigo_servico_api("60201") == "06.02.01.000"
    assert codigo_servico_api("010401", "003") == "01.04.01.003"


def test_url_do_adn():
    assert SefinNacional("https://sefin.producaorestrita.nfse.gov.br/SefinNacional").url_adn == \
        "https://adn.producaorestrita.nfse.gov.br"


def test_servico_aceito_sem_complemento():
    s, chamadas = sefin_com({"/convenio": Resp(200, {}), "06.02.01.000/historicoaliquotas": Resp(200, {"aliquotas": {"x": []}})})
    r = s.consultar_servico_municipio("3550308", "060201", None)
    assert r.administrado is True and r.conveniado is True and r.codigos_municipais == []
    assert "/parametrizacao/3550308/06.02.01.000/historicoaliquotas" in chamadas


def test_prefeitura_exige_codigo_municipal():
    s, _ = sefin_com({"/convenio": Resp(200, {}), "01.04.01.003/historicoaliquotas": Resp(200, {"aliquotas": {"x": []}})})
    r = s.consultar_servico_municipio("3304557", "010401", None)
    assert r.administrado is True and r.codigos_municipais == ["003"]


def test_servico_nao_aceito_e_municipio_sem_convenio():
    s, _ = sefin_com({})
    r = s.consultar_servico_municipio("3550308", "060201", None)
    assert r.administrado is False and r.conveniado is False


def test_simulacao_sempre_aceita():
    assert SefinSimulada().consultar_servico_municipio("3550308", "060201", None).administrado is True


def test_dica_no_erro_e0312():
    msgs = SefinNacional._mensagens(Resp(400, {"erros": [{"codigo": "E0312", "descricao": "não administrado"}]}))
    assert any("Conferir na prefeitura" in m for m in msgs)
