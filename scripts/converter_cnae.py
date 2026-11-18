"""Converte a "Tabela CNAE x Atividade x Item da Lista de Serviços" (PDF) em app/dados/cnae_servicos.json.

Uso: python -I scripts/converter_cnae.py "Tabela_CNAE_x_Atividade_x_Item_da_Lista_de_Servicos.pdf"
Cada CNAE (7 dígitos) aponta para os itens da LC 116 (ex.: "01.01") que ele costuma prestar.
"""
import json, re, sys
from pathlib import Path

import pdfplumber

SAIDA = Path(__file__).resolve().parent.parent / "app" / "dados" / "cnae_servicos.json"
CNAE = re.compile(r"^\d{2}\.\d{2}-\d-\d{2}$")
ITEM = re.compile(r"^\d{2}\.\d{2}$")

# Na tabela publicada, as linhas do bloco 17.17 a 17.20 estão deslocadas uma posição
# (ex.: "Atividades de contabilidade" aparece ao lado de 17.20, mas contabilidade é 17.19).
CORRECOES = {
    "6920601": ["17.19"],
    "6920602": ["17.01", "17.09", "17.16", "17.19"],
    "6621502": ["17.16", "17.18"],
    "7020400": ["17.01", "17.03", "17.17", "17.20", "35.01"],
}


def _faixas(pagina, x_a: float, x_b: float, bordas: bool = False) -> list[tuple[float, float]]:
    """Intervalos verticais das células de uma coluna (entre as linhas horizontais que a cruzam).
    Com bordas=True, inclui o pedaço antes da primeira e depois da última linha (célula que
    continua da página anterior ou na próxima)."""
    ys = {round(e["top"], 1) for e in pagina.edges
          if e["orientation"] == "h" and e["x0"] <= x_a + 2 and e["x1"] >= x_b - 2}
    if bordas:
        ys |= {0.0, round(float(pagina.height), 1)}
    ys = sorted(ys)
    return list(zip(ys, ys[1:]))


def _textos(pagina, faixa, x_a, x_b, padrao):
    return [w["text"] for w in pagina.extract_words()
            if x_a - 2 <= w["x0"] and w["x1"] <= x_b + 2 and faixa[0] - 1 <= (w["top"] + w["bottom"]) / 2 <= faixa[1] + 1
            and padrao.match(w["text"])]


def main(caminho: str) -> None:
    mapa: dict[str, dict] = {}
    ultimo_item = None
    for pagina in pdfplumber.open(caminho).pages:
        palavras = pagina.extract_words(keep_blank_chars=False)
        # colunas pela posição do cabeçalho / códigos (CNAE à esquerda, código do item no meio)
        xs_cnae = [w for w in palavras if CNAE.match(w["text"])]
        xs_item = [w for w in palavras if ITEM.match(w["text"]) and w["x0"] > 300]
        if not xs_cnae:
            continue
        ca, cb = min(w["x0"] for w in xs_cnae), max(w["x1"] for w in xs_cnae)
        ia, ib = (min(w["x0"] for w in xs_item), max(w["x1"] for w in xs_item)) if xs_item else (400, 430)
        celulas_item = []
        faixas_item = _faixas(pagina, ia, ib, bordas=True)
        for n, f in enumerate(faixas_item):
            cods = _textos(pagina, f if n < len(faixas_item) - 1 else (f[0], 10_000), ia, ib, ITEM)
            item = cods[0] if cods else (ultimo_item if not celulas_item else None)
            celulas_item.append((f, item))
        if celulas_item and celulas_item[-1][1]:
            ultimo_item = celulas_item[-1][1]
        celulas = []
        for f in _faixas(pagina, ca, cb):
            desc = " ".join(w["text"] for w in palavras if cb + 2 < w["x0"] < 262 and f[0] - 1 <= (w["top"] + w["bottom"]) / 2 <= f[1] + 1)
            celulas.append((f, _textos(pagina, f, ca, cb, CNAE), desc))
        # célula sem código (mesclado com outra linha): acha o código pela mesma descrição
        por_desc = {d.upper(): c[0] for _, c, d in celulas if len(c) == 1 and d}
        for f, cods, desc in celulas:
            if not cods and desc.upper() in por_desc:
                cods = [por_desc[desc.upper()]]
            if not cods:
                continue
            for (a, b), item in celulas_item:
                if item and item != "00.00" and min(b, f[1]) - max(a, f[0]) > 1:
                    e = mapa.setdefault(re.sub(r"\D", "", cods[0]), {"descricao": desc.capitalize(), "itens": []})
                    if item not in e["itens"]:
                        e["itens"].append(item)
    for cnae, itens in CORRECOES.items():
        if cnae in mapa:
            mapa[cnae]["itens"] = itens
    SAIDA.write_text(json.dumps({"fonte": Path(caminho).name, "cnaes": mapa}, ensure_ascii=False, indent=0))
    print(len(mapa), "CNAEs,", sum(len(v["itens"]) for v in mapa.values()), "ligações")

if __name__ == "__main__":
    main(sys.argv[1])
