"""Converte a planilha oficial do Anexo VIII (NFS-e Nacional, Reforma Tributária) em app/dados/anexo8.json.

Uso: python -I scripts/converter_anexo8.py "Anexo VIII - v1.02.00.xlsx"
Fonte: https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/rtc
"""
import json
import sys
from pathlib import Path

import openpyxl


def main(caminho: str) -> None:
    ws = openpyxl.load_workbook(caminho, data_only=True)["tabela geral"]
    linhas = [[ws.cell(r, c).value for c in range(1, 11)] for r in range(1, ws.max_row + 1)]
    for faixa in ws.merged_cells.ranges:  # células mescladas valem para todas as linhas cobertas
        if faixa.min_col > 10:
            continue
        valor = linhas[faixa.min_row - 1][faixa.min_col - 1]
        for r in range(faixa.min_row, min(faixa.max_row, ws.max_row) + 1):
            for c in range(faixa.min_col, min(faixa.max_col, 10) + 1):
                linhas[r - 1][c - 1] = valor
    itens, atual = {}, None
    for item, _desc, nbs, dnbs, _, _, indop, _local, cct, ncct in (l[:10] for l in linhas[1:]):
        if item:
            atual = str(item).strip()
        if not atual:
            continue
        d = itens.setdefault(atual, {"nbs": [], "cclass": []})
        if nbs:
            cod = str(nbs).strip().replace(".", "")
            existente = next((n for n in d["nbs"] if n["codigo"] == cod), None)
            if not existente:
                d["nbs"].append({"codigo": cod, "descricao": (dnbs or "").strip(), "cind_op": str(indop).strip() if indop else None})
            elif indop and not existente["cind_op"]:
                existente["cind_op"] = str(indop).strip()
        if cct and not any(c["codigo"] == str(cct).strip().zfill(6) for c in d["cclass"]):
            d["cclass"].append({"codigo": str(cct).strip().zfill(6), "nome": (ncct or "").strip()})
    itens = {k: v for k, v in itens.items() if v["nbs"]}
    destino = Path(__file__).resolve().parent.parent / "app" / "dados" / "anexo8.json"
    destino.write_text(json.dumps({"fonte": f"{Path(caminho).name} — Correlação item LC 116 × NBS × cIndOp × cClassTrib",
                                   "itens": itens}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(len(itens), "itens ->", destino)


if __name__ == "__main__":
    main(sys.argv[1])
