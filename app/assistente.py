"""Assistente do Emitta: conversa com a pessoa e prepara tarefas (nota, cancelamento).

Regra de ouro: a assistente NUNCA emite nem cancela sozinha. Ela só monta um
rascunho ("ação") que o app mostra num cartão; a pessoa confere e confirma na
tela de sempre, que passa pelas mesmas validações de qualquer emissão.

Funciona com qualquer serviço de IA compatível com a API da OpenAI (por
padrão a Groq, que tem plano gratuito e não usa as conversas para treino).
Sem chave configurada, cai na "ajuda básica", com respostas prontas.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

import requests

from . import regras

URL_PADRAO = "https://api.groq.com/openai/v1"
MODELO_PADRAO = "openai/gpt-oss-120b"  # o Llama 3.3 saiu do plano gratuito do Groq em 16/08/2026
MAX_MENSAGENS = 14
MAX_CARACTERES = 1200
MAX_RODADAS_FERRAMENTAS = 4


@dataclass
class ConfigIA:
    chave: str | None
    url: str = URL_PADRAO
    modelo: str = MODELO_PADRAO

    @classmethod
    def do_ambiente(cls) -> "ConfigIA":
        return cls(
            chave=(os.environ.get("EMITTA_IA_CHAVE") or "").strip() or None,
            url=(os.environ.get("EMITTA_IA_URL") or URL_PADRAO).rstrip("/"),
            modelo=os.environ.get("EMITTA_IA_MODELO") or MODELO_PADRAO,
        )


@dataclass
class Contexto:
    """O que a assistente pode saber sobre quem está conversando."""
    papel: str  # contador | empresa | autonomo
    nome: str
    ambiente: str  # simulacao | homologacao | producao
    hoje: date
    empresa: dict | None = None  # razao_social, municipio, aliquota_iss, regime, prazo_cancelamento_dias
    servicos: list[dict] = field(default_factory=list)  # liberados: codigo, apelido, descricao
    notas: list[dict] = field(default_factory=list)  # recentes
    catalogo: dict = field(default_factory=dict)  # lista nacional (codigo -> dados)
    consultar_cnpj: Callable[[str], dict] | None = None


# ---------------------------------------------------------------- utilidades

def _sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", str(t or "")) if unicodedata.category(c) != "Mn").lower()


def buscar_no_catalogo(catalogo: dict, termo: str, limite: int = 8) -> list[dict]:
    """Mesma ideia da busca do painel: palavras, sem acento, pelo começo da palavra."""
    digitos = re.sub(r"\D", "", termo)
    if digitos and re.fullmatch(r"[\d.\s]+", termo.strip()):
        return [s for c, s in catalogo.items() if c.startswith(digitos)][:limite]
    palavras = [p for p in _sem_acento(termo).split() if len(p) > 1]
    if not palavras:
        return []

    def texto(s):
        return _sem_acento(f"{s['descricao']} {s.get('item_descricao', '')} {' '.join(s.get('palavras', []))}")

    def casa(ps):
        return [s for s in catalogo.values() if all(p in texto(s) for p in ps)]

    achados = casa(palavras) or casa([p[:-2] if len(p) > 5 else p[:4] if len(p) > 4 else p for p in palavras])
    return achados[:limite]


def _reais(centavos: int) -> str:
    """18000 -> '180,00' (como a pessoa digita no app)."""
    return f"{centavos // 100},{centavos % 100:02d}"


def _resolver_servico(ctx: Contexto, pedido: str) -> dict | None:
    """Acha o serviço liberado pelo código (060101 / 06.01.01) ou pelo nome."""
    if not ctx.servicos:
        return None
    digitos = re.sub(r"\D", "", pedido or "")
    for s in ctx.servicos:
        if digitos and s["codigo"] == digitos.zfill(6):
            return s
    alvo = _sem_acento(pedido)
    for s in ctx.servicos:
        if alvo and (alvo == _sem_acento(s["apelido"]) or alvo in _sem_acento(s["apelido"])):
            return s
    palavras = [p for p in alvo.split() if len(p) > 2]
    melhores = [s for s in ctx.servicos if palavras and all(p[:5] in _sem_acento(f"{s['apelido']} {s['descricao']}") for p in palavras)]
    if len(melhores) == 1:
        return melhores[0]
    if len(ctx.servicos) == 1 and not pedido:
        return ctx.servicos[0]
    return None


# ---------------------------------------------------------------- ferramentas

def _ferramentas(ctx: Contexto) -> list[dict]:
    def f(nome, descricao, propriedades, obrigatorios):
        return {"type": "function", "function": {
            "name": nome, "description": descricao,
            "parameters": {"type": "object", "properties": propriedades, "required": obrigatorios}}}

    lista = [
        f("buscar_servico_lista_nacional",
          "Procura códigos na lista nacional de serviços (LC 116) por palavras (ex.: 'cabelo', 'contabilidade') ou código.",
          {"termo": {"type": "string"}}, ["termo"]),
    ]
    if ctx.empresa is not None:
        lista += [
            f("preparar_nota",
              "Monta o rascunho de uma nota para a pessoa conferir e confirmar no app. NÃO emite. "
              "Use só quando souber serviço, documento do cliente e valor.",
              {"servico": {"type": "string", "description": "Nome ou código de um serviço LIBERADO da empresa"},
               "cliente_documento": {"type": "string", "description": "CPF ou CNPJ de quem contratou"},
               "cliente_nome": {"type": "string", "description": "Nome ou razão social (opcional se for CNPJ)"},
               "valor": {"type": "string", "description": "Valor em reais, ex.: 180,00"},
               "descricao": {"type": "string", "description": "Descrição curta do que foi feito"}},
              ["servico", "cliente_documento", "valor"]),
            f("preparar_cancelamento",
              "Monta o pedido de cancelamento de uma nota autorizada para a pessoa confirmar no app. NÃO cancela.",
              {"numero_nota": {"type": "string", "description": "Número da nota, ex.: 12 ou 000012"},
               "motivo": {"type": "string", "enum": ["erro", "nao_prestado", "outro"],
                          "description": "erro = erro na emissão; nao_prestado = serviço não foi feito; outro = outro motivo"},
               "texto_motivo": {"type": "string", "description": "Obrigatório se motivo = outro (frase de 15+ letras)"}},
              ["numero_nota", "motivo"]),
        ]
    return lista


def _executar(nome: str, args: dict, ctx: Contexto, acoes: list[dict]) -> dict:
    try:
        if nome == "buscar_servico_lista_nacional":
            achados = buscar_no_catalogo(ctx.catalogo, str(args.get("termo", "")))
            return {"servicos": [{"codigo": s["codigo"], "descricao": s["descricao"][:160]} for s in achados]}

        if nome == "preparar_nota" and ctx.empresa is not None:
            servico = _resolver_servico(ctx, str(args.get("servico", "")))
            if not servico:
                return {"erro": "Serviço não está liberado para esta empresa.",
                        "servicos_liberados": [s["apelido"] for s in ctx.servicos]}
            try:
                doc = regras.validar_documento(str(args.get("cliente_documento", "")))
            except regras.DocumentoInvalido as e:
                return {"erro": str(e)}
            try:
                centavos = regras.valor_em_centavos(str(args.get("valor", "")))
            except regras.ErroDeNegocio as e:
                return {"erro": str(e)}
            nome_cliente = str(args.get("cliente_nome") or "").strip()
            if not nome_cliente and doc.tipo == "CNPJ" and ctx.consultar_cnpj:
                try:
                    nome_cliente = ctx.consultar_cnpj(doc.numero).get("razao_social") or ""
                except Exception:
                    nome_cliente = ""
            if not nome_cliente:
                return {"erro": "Falta o nome de quem contratou (para CPF, pergunte o nome)."}
            valor = _reais(centavos)
            dados = {"codigo": servico["codigo"], "servico": servico["apelido"], "documento": doc.numero,
                     "tipo_documento": doc.tipo, "nome": nome_cliente[:150], "valor": valor,
                     "descricao": (str(args.get("descricao") or "").strip() or servico["apelido"])[:500]}
            acoes[:] = [a for a in acoes if a["tipo"] != "nota"] + [{"tipo": "nota", "dados": dados}]
            iss = _reais(regras.calcular_iss(centavos, ctx.empresa.get("aliquota_iss") or 0))
            return {"ok": True, "rascunho": dados, "iss_estimado": iss,
                    "lembrete": "Rascunho pronto. A pessoa precisa conferir e tocar em Emitir no app."}

        if nome == "preparar_cancelamento" and ctx.empresa is not None:
            numero = re.sub(r"\D", "", str(args.get("numero_nota", "")))
            nota = next((n for n in ctx.notas if numero and int(n["numero"]) == int(numero)), None)
            if not nota:
                return {"erro": "Não achei essa nota entre as recentes.",
                        "notas_recentes": [{"numero": n["numero"], "cliente": n["cliente"], "situacao": n["situacao"]} for n in ctx.notas[:8]]}
            if nota["situacao"] != "autorizada":
                return {"erro": f"Essa nota está '{nota['situacao']}'; só nota autorizada pode ser cancelada."}
            motivo = str(args.get("motivo", ""))
            try:
                regras.motivo_cancelamento(motivo, args.get("texto_motivo"))
            except regras.ErroDeNegocio as e:
                return {"erro": str(e)}
            dados = {"nota_id": nota["id"], "numero": nota["numero"], "cliente": nota["cliente"], "valor": nota["valor"],
                     "motivo": motivo, "texto_motivo": str(args.get("texto_motivo") or "")[:255]}
            acoes[:] = [a for a in acoes if a["tipo"] != "cancelamento"] + [{"tipo": "cancelamento", "dados": dados}]
            return {"ok": True, "rascunho": dados,
                    "lembrete": "Pedido pronto. A pessoa precisa conferir e confirmar o cancelamento no app."}
    except Exception:  # nunca derruba a conversa por causa de uma ferramenta
        return {"erro": "Não consegui fazer isso agora."}
    return {"erro": "Ferramenta indisponível aqui."}


# ---------------------------------------------------------------- conversa com a IA

def _instrucoes(ctx: Contexto) -> str:
    amb = {"simulacao": "SIMULAÇÃO (notas sem valor, não vão ao governo)",
           "homologacao": "TESTE DO GOVERNO (notas sem valor fiscal)",
           "producao": "PRODUÇÃO (notas valem de verdade)"}.get(ctx.ambiente, ctx.ambiente)
    partes = [
        "Você é a assistente do Emitta, um app brasileiro que emite NFS-e (nota fiscal de serviço, padrão nacional) direto para o governo.",
        "Seu papel: ajudar a pessoa a fazer as tarefas no app (emitir, cancelar, baixar, configurar) e, quando ela pedir, preparar a nota ou o cancelamento para ela só conferir e confirmar.",
        "ESTILO: português do Brasil, simples, gentil e curto (no máximo 4 frases, ou passos numerados curtos). "
        "Escreva texto puro: sem markdown, sem asteriscos, sem emojis, sem títulos. Para passos, use linhas começando com 1. 2. 3. "
        "Use os nomes exatos dos botões entre aspas. Não fale de códigos técnicos (código municipal, cTribNac etc.) a não ser que a pessoa pergunte.",
        f"Hoje é {ctx.hoje.strftime('%d/%m/%Y')}. Ambiente do app: {amb}.",
        f"Quem está falando: {ctx.nome} ({'contador(a)' if ctx.papel == 'contador' else 'empresa' if ctx.papel == 'empresa' else 'MEI/autônomo sem contador'}).",
        "REGRAS:",
        "- Você NUNCA emite nem cancela nota sozinha. Quando a pessoa pedir uma nota, use a ferramenta para preparar; o app mostra um cartão 'Conferir e emitir' e ela confirma. Nunca diga que a nota foi emitida ou cancelada.",
        "- Para preparar uma nota você precisa de: serviço (um dos liberados), CPF ou CNPJ do cliente, nome (se for CPF) e valor. Pergunte o que faltar, uma coisa por vez. Se ela já deu tudo, prepare direto.",
        "- Se a pessoa só quer saber como fazer, explique os passos do app; ofereça preparar a nota por ela ('Se quiser, me diga o cliente e o valor que eu preencho para você').",
        "- Nunca peça senha, código de verificação nem certificado digital. Certificado só se envia pela tela própria.",
        "- Não invente regras fiscais, alíquotas ou prazos. Na dúvida, sugira confirmar com o contador ou a prefeitura.",
        "- Assuntos fora do Emitta/nota fiscal: diga com gentileza que só ajuda com o Emitta.",
        "COMO USAR O APP:",
        "Emitir: na tela inicial, tocar em 'Nova nota' (ou 'Emitir' no menu de baixo) > escolher o serviço > CPF ou CNPJ do cliente, nome, valor e descrição > 'Emitir nota'. A nota vai para o governo e aparece como autorizada.",
        "Cancelar: tocar na nota na lista > 'Cancelar esta nota' > escolher o motivo > confirmar.",
        "Baixar: abrir a nota > 'Baixar PDF' ou 'Baixar XML' (no celular abre a opção de salvar ou compartilhar).",
        "Contador: painel > escolher a empresa > abas Serviços (chave 'Liberados | Todos os serviços' para liberar), Notas, Certificado, Acesso ao app, Dados da empresa.",
        "MEI/autônomo sem contador: a tela inicial mostra 'Seu passo a passo' (1. enviar o certificado, 2. escolher os serviços, 3. emitir a primeira nota) e os atalhos 'Meus serviços', 'Certificado' e 'Dados'. "
        "Também há 'Ajustes' no menu de baixo. Para escolher serviços: 'Meus serviços' > 'Todos os serviços' > buscar > 'Liberar' > 'Salvar e enviar para o app'.",
    ]
    if ctx.empresa:
        e = ctx.empresa
        partes.append(f"EMPRESA: {e.get('razao_social')} · {e.get('municipio')} · ISS {e.get('aliquota_iss')}% · regime {e.get('regime')}.")
        partes.append("SERVIÇOS LIBERADOS: " + ("; ".join(f"{s['apelido']} ({s['codigo']})" for s in ctx.servicos) or ("nenhum ainda (a pessoa escolhe em Meus serviços)" if ctx.papel == "autonomo" else "nenhum (o contador precisa liberar)")))
        if ctx.notas:
            partes.append("NOTAS RECENTES: " + "; ".join(
                f"nº {n['numero']} {n['data']} {n['cliente']} R$ {n['valor']} {n['situacao']}" for n in ctx.notas[:10]))
    return "\n".join(partes)


def _limpar_historico(mensagens: list[dict]) -> list[dict]:
    saida = []
    for m in mensagens[-MAX_MENSAGENS:]:
        texto = str(m.get("texto") or "")[:MAX_CARACTERES].strip()
        if not texto:
            continue
        saida.append({"role": "assistant" if m.get("de") == "assistente" else "user", "content": texto})
    return saida


def responder(ctx: Contexto, mensagens: list[dict], config: ConfigIA | None = None,
              chamar: Callable[[dict], dict] | None = None) -> dict:
    """Devolve {"resposta": str, "acoes": [...], "modo": "ia" | "basico"}."""
    config = config or ConfigIA.do_ambiente()
    historico = _limpar_historico(mensagens)
    if not historico:
        return {"resposta": "Oi! Como posso ajudar?", "acoes": [], "modo": "basico"}
    if not config.chave and chamar is None:
        return ajuda_basica(ctx, historico[-1]["content"])

    def chamar_api(corpo: dict) -> dict:
        r = requests.post(f"{config.url}/chat/completions", json=corpo, timeout=40,
                          headers={"Authorization": f"Bearer {config.chave}"})
        if r.status_code == 429:
            raise _Ocupada()
        if not r.ok:
            # registra o motivo (nunca a chave) para descobrir o problema nos registros do Render
            print(f"[assistente] IA respondeu HTTP {r.status_code}: {r.text[:400]}", flush=True)
        r.raise_for_status()
        return r.json()

    chamar = chamar or chamar_api
    conversa = [{"role": "system", "content": _instrucoes(ctx)}] + historico
    acoes: list[dict] = []
    ferramentas = _ferramentas(ctx)
    try:
        for _ in range(MAX_RODADAS_FERRAMENTAS + 1):
            resp = chamar({"model": config.modelo, "messages": conversa, "tools": ferramentas,
                           "tool_choice": "auto", "temperature": 0.2, "max_tokens": 600})
            msg = resp["choices"][0]["message"]
            pedidos = msg.get("tool_calls") or []
            if not pedidos:
                texto = (msg.get("content") or "").strip() or "Pronto."
                return {"resposta": texto, "acoes": acoes, "modo": "ia"}
            conversa.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": pedidos})
            for p in pedidos:
                try:
                    args = json.loads(p["function"].get("arguments") or "{}")
                except (ValueError, TypeError):
                    args = {}
                resultado = _executar(p["function"]["name"], args if isinstance(args, dict) else {}, ctx, acoes)
                conversa.append({"role": "tool", "tool_call_id": p.get("id", ""), "content": json.dumps(resultado, ensure_ascii=False)})
        return {"resposta": "Preparei o que consegui. Confira abaixo.", "acoes": acoes, "modo": "ia"}
    except _Ocupada:
        r = ajuda_basica(ctx, historico[-1]["content"])
        r["resposta"] = "Estou com muitas conversas agora. " + r["resposta"]
        return r
    except Exception as erro:
        print(f"[assistente] falha ao falar com a IA ({config.url}, modelo {config.modelo}): {type(erro).__name__}: {str(erro)[:300]}", flush=True)
        r = ajuda_basica(ctx, historico[-1]["content"])
        r["resposta"] = "Não consegui falar com a IA agora, mas posso ajudar assim: " + r["resposta"]
        return r


class _Ocupada(Exception):
    pass


# ---------------------------------------------------------------- ajuda básica (sem IA)

def ajuda_basica(ctx: Contexto, pergunta: str) -> dict:
    """Respostas prontas para as dúvidas mais comuns. Funciona sem chave de IA."""
    p = _sem_acento(pergunta)
    tem = lambda *ps: any(x in p for x in ps)  # noqa: E731
    acoes: list[dict] = []
    if tem("cancel"):
        resposta = ("Para cancelar: toque na nota na tela inicial, depois em \"Cancelar esta nota\", escolha o motivo e confirme. "
                    "Só nota autorizada pode ser cancelada, dentro do prazo da prefeitura.")
    elif tem("emitir", "nota nova", "nova nota", "fazer nota", "fazer uma nota", "gerar nota"):
        resposta = ("Para emitir: toque em \"Nova nota\", escolha o serviço, coloque o CPF ou CNPJ do cliente, o nome, o valor "
                    "e uma descrição curta, e toque em \"Emitir nota\".")
        if ctx.empresa is not None:
            acoes.append({"tipo": "abrir", "dados": {"tela": "nova", "rotulo": "Abrir nova nota"}})
    elif tem("pdf", "xml", "baixar", "download", "salvar"):
        resposta = ("Abra a nota e toque em \"Baixar PDF\" ou \"Baixar XML\". No celular, abre o Compartilhar: "
                    "escolha \"Salvar em Arquivos\", WhatsApp ou e-mail.")
    elif tem("servico", "codigo") and ctx.papel in ("contador", "autonomo"):
        inicio = "Toque em \"Ajustes\", abra a aba Serviços" if ctx.papel == "autonomo" else "Na empresa, abra a aba Serviços"
        resposta = (inicio + " e toque em \"Todos os serviços\". Busque por palavra (ex.: cabelo) ou código, "
                    "toque em \"Liberar\" e depois em \"Salvar e enviar para o app\". Use \"Conferir na prefeitura\" para ver se a cidade aceita.")
    elif tem("servico", "codigo"):
        resposta = "Os serviços que aparecem são os que seu contador liberou. Se faltar algum, peça para ele liberar no painel."
    elif tem("certificado"):
        resposta = ("O certificado digital A1 (.pfx) é enviado na aba Certificado da empresa, com a senha dele. "
                    "Ele fica guardado criptografado. Nunca mande o certificado por mensagem.")
    elif tem("senha", "esqueci", "acesso", "login", "entrar"):
        resposta = ("Se esqueceu a senha, fale com o suporte do Emitta." if ctx.papel == "autonomo" else
                    "Se esqueceu a senha, peça ao seu contador para gerar uma nova senha provisória na aba Acesso ao app.")
    elif tem("recus", "erro", "rejeit", "nao foi", "deu errado"):
        resposta = ("Quando a prefeitura recusa, nada é emitido. Leia a mensagem na tela, toque em \"Corrigir dados\" e envie de novo. "
                    "Se o erro falar do código do serviço, o contador pode usar \"Conferir na prefeitura\".")
    else:
        resposta = ("Posso ajudar a emitir ou cancelar nota, baixar PDF e XML, liberar serviços e enviar o certificado. "
                    "Me diga o que você quer fazer.")
    return {"resposta": resposta, "acoes": acoes, "modo": "basico"}
