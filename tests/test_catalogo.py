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
