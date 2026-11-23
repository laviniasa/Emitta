"""Notas recorrentes: a mesma nota emitida sozinha todo mês, no dia escolhido.

Regras (pensadas para nunca duplicar nem emitir sem querer):
- Cada recorrência emite no máximo uma nota por mês. A chave de envio é
  "rec-<id>-<AAAA-MM>-<tentativa>", então mesmo que duas rodadas aconteçam juntas
  o servidor devolve a mesma nota em vez de criar outra.
- Não recupera meses que passaram: se o servidor ficou desligado o mês inteiro,
  ela só volta no mês seguinte.
- Criada depois do dia escolhido (ou no próprio dia), começa no mês seguinte.
- Se a prefeitura recusar ou faltar algo (certificado, serviço liberado), registra o
  erro e não tenta de novo sozinha naquele mês: a empresa vê o aviso e toca em
  "Tentar de novo" depois de corrigir.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Callable

try:
    from zoneinfo import ZoneInfo
    FUSO = ZoneInfo("America/Sao_Paulo")
except Exception:  # sem base de fusos no sistema
    FUSO = timezone(timedelta(hours=-3))

_trava = threading.Lock()


def agora_brasil() -> datetime:
    return datetime.now(FUSO)


def mes_de(data: datetime) -> str:
    return data.strftime("%Y-%m")


def mes_inicial(dia: int, hoje: datetime) -> str | None:
    """Valor de "ultimo_mes" para uma recorrência nova: se o dia deste mês já chegou,
    este mês fica de fora (evita emitir de novo a nota que acabou de sair)."""
    return mes_de(hoje) if hoje.day >= dia else None


def proxima_data(rec: dict, hoje: datetime) -> str | None:
    """Data (AAAA-MM-DD) da próxima emissão, para mostrar na tela."""
    if not rec.get("ativa"):
        return None
    ano, mes = hoje.year, hoje.month
    if rec.get("ultimo_mes") == mes_de(hoje) or hoje.day > rec["dia"]:
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return f"{ano:04d}-{mes:02d}-{rec['dia']:02d}"


def chave_envio(rec: dict, mes: str) -> str:
    return f"rec-{rec['id']}-{mes}-{rec.get('tentativa') or 0}"


def processar(repo, emitir: Callable[[dict, str], tuple[str, int | None]], hoje: datetime | None = None,
              cliente_id: int | None = None, avisar: Callable[[dict, str, str], None] | None = None) -> list[dict]:
    """Emite as recorrências que venceram hoje (ou antes, neste mês) e ainda não saíram.

    emitir(rec, chave) devolve ("autorizada" | "processando", nota_id) ou levanta exceção
    com a mensagem para a empresa. Devolve a lista do que foi feito.
    """
    hoje = hoje or agora_brasil()
    mes = mes_de(hoje)
    feitos = []
    with _trava:
        for rec in repo.recorrencias(cliente_id, so_ativas=True):
            if rec["ultimo_mes"] == mes or hoje.day < rec["dia"]:
                continue
            momento = hoje.isoformat()
            try:
                situacao, nota_id = emitir(rec, chave_envio(rec, mes))
                repo.atualizar_recorrencia(rec["id"], ultimo_mes=mes, ultima_nota_id=nota_id,
                                           ultimo_erro=None, ultima_tentativa_em=momento)
                feitos.append({"id": rec["id"], "situacao": situacao, "nota_id": nota_id})
            except Exception as erro:  # cada recorrência é independente
                mensagem = str(erro) or "Não foi possível emitir a nota."
                repo.atualizar_recorrencia(rec["id"], ultimo_mes=mes, ultimo_erro=mensagem[:500],
                                           ultima_tentativa_em=momento)
                feitos.append({"id": rec["id"], "situacao": "erro", "mensagem": mensagem})
                print(f"[recorrente] {rec['id']} cliente {rec['cliente_id']}: {mensagem}", flush=True)
            if avisar:
                avisar(rec, feitos[-1]["situacao"], feitos[-1].get("mensagem", ""))
    return feitos


def iniciar_agendador(executar: Callable[[], object], intervalo_seg: int = 20 * 60) -> threading.Thread:
    """Roda `executar` logo ao ligar o servidor e depois a cada `intervalo_seg`."""
    parar = threading.Event()

    def laco():
        while not parar.is_set():
            try:
                executar()
            except Exception as erro:
                print(f"[recorrente] falha na rodada: {erro}", flush=True)
            parar.wait(intervalo_seg)

    t = threading.Thread(target=laco, name="emitta-recorrentes", daemon=True)
    t.parar = parar  # type: ignore[attr-defined]
    t.start()
    return t
