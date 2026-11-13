"""Converte a planilha oficial (Anexo B da NFS-e Nacional) para app/dados/servicos_nacional.json.

Precisa do openpyxl (pip install openpyxl). Uso: python3 scripts/converter_anexo_b.py ANEXO_B-...xlsx app/dados/servicos_nacional.json
"""
import json, re, sys, openpyxl
wb = openpyxl.load_workbook(sys.argv[1], read_only=True); ws = wb["LISTA.SERV.NAC."]
limpa = lambda t: re.sub(r"\s+", " ", str(t or "")).strip().rstrip(".").strip()
itens, subitens, servicos = {}, {}, []
for i, r in enumerate(ws.iter_rows(values_only=True)):
    if i == 0 or not any(r): continue
    cod, it, sub, des, txt = r[:5]
    it, sub, des = int(str(it).strip()), int(str(sub).strip()), int(str(des).strip())
    if sub == 0: itens[it] = limpa(txt); continue
    if des == 0: subitens[(it, sub)] = limpa(txt); continue
    codigo = f"{it:02d}{sub:02d}{des:02d}"
    assert cod is None or str(cod).strip().zfill(6) == codigo, (cod, codigo)
    servicos.append({"codigo": codigo, "item": f"{it:02d}", "subitem": f"{it:02d}.{sub:02d}", "descricao": limpa(txt)})
for s in servicos:
    it, sub = int(s["item"]), int(s["subitem"][3:])
    s["item_descricao"] = itens.get(it, "")
    sd = subitens.get((it, sub), "")
    if sd and sd != s["descricao"]: s["subitem_descricao"] = sd
json.dump({"_fonte": "Anexo B - Lista de Serviços Nacional (SN NFS-e), planilha ANEXO_B-NBS2-LISTA_SERVICO_NACIONAL-SNNFSe.xlsx, gov.br/nfse, versão de 10/12/2025",
           "servicos": servicos}, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(len(servicos), "códigos,", len(itens), "áreas,", len(subitens), "subitens")
print([ (s["codigo"], s["descricao"][:50]) for s in servicos if s["subitem"] in ("06.01","17.19","01.03","99.01")])
