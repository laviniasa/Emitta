from app.catalogo import carregar_catalogo, descricao_oficial


def test_lista_nacional_completa():
    cat = carregar_catalogo()
    assert len(cat) > 300
    assert all(len(c) == 6 and c.isdigit() for c in cat)
    assert descricao_oficial("171901").startswith("Contabilidade")
    assert cat["060101"]["item_descricao"].startswith("Serviços de cuidados pessoais")
    assert cat["010302"]["subitem"] == "01.03"


def test_palavras_do_dia_a_dia():
    cat = carregar_catalogo()
    assert "contador" in cat["171901"]["palavras"]
    assert "cabelo" in cat["060101"]["palavras"]


def test_servicos_sugeridos_pelo_cnae():
    from app.catalogo import servicos_por_cnae
    r = servicos_por_cnae([{"codigo": "9602502", "descricao": "Estética"}, {"codigo": "96.02-5-01"},
                           {"codigo": "6920601"}, {"codigo": "4711302"}, {"codigo": "9602502"}])
    por = {c["codigo"]: c for c in r}
    assert [c["codigo"] for c in r] == ["9602502", "9602501", "6920601", "4711302"]  # sem repetir, principal primeiro
    assert por["9602502"]["servicos"] == ["060101", "060201"]
    assert "060101" in por["9602501"]["servicos"]
    assert por["6920601"]["servicos"] == ["171901"]  # contabilidade (tabela corrigida: 17.19)
    assert por["4711302"]["servicos"] == []  # comércio: sem serviço


def test_consulta_cnpj_traz_cnaes_secundarios():
    from app.consulta_cnpj import ConsultaCnpj
    c = ConsultaCnpj(buscar=lambda cnpj: {"razao_social": "X", "cnae_fiscal": 9602502, "cnae_fiscal_descricao": "Estética",
                                          "cnaes_secundarios": [{"codigo": 9602501, "descricao": "Cabeleireiros"}, {"codigo": 0, "descricao": ""}],
                                          "codigo_municipio_ibge": 3550308, "cep": "01310-100", "descricao_tipo_de_logradouro": "AVENIDA",
                                          "logradouro": "PAULISTA", "numero": "1000", "complemento": "", "bairro": "BELA VISTA"})
    r = c.consultar("27384956000190")
    assert r["cnae_principal"]["codigo"] == "9602502"
    assert r["cnaes_secundarios"] == [{"codigo": "9602501", "descricao": "Cabeleireiros"}]
    assert r["endereco"] == {"cmun": "3550308", "cep": "01310100", "logradouro": "AVENIDA PAULISTA", "numero": "1000",
                             "complemento": "", "bairro": "BELA VISTA"}
