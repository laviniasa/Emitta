"""Acesso ao banco SQLite (biblioteca padrão do Python, sem ORM)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cnpj TEXT NOT NULL UNIQUE,
    razao_social TEXT NOT NULL,
    municipio_ibge TEXT NOT NULL,
    municipio_nome TEXT NOT NULL,
    opcao_simples TEXT NOT NULL DEFAULT '3',
    aliquota_iss TEXT NOT NULL,
    prazo_cancelamento_dias INTEGER,
    serie_dps TEXT NOT NULL DEFAULT '1',
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS servicos_liberados (
    cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    codigo TEXT NOT NULL,
    apelido TEXT NOT NULL,
    PRIMARY KEY (cliente_id, codigo)
);

CREATE TABLE IF NOT EXISTS notas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    numero_dps INTEGER NOT NULL,
    codigo_servico TEXT NOT NULL,
    tomador_tipo TEXT NOT NULL,
    tomador_documento TEXT NOT NULL,
    tomador_nome TEXT NOT NULL,
    descricao TEXT NOT NULL,
    valor_centavos INTEGER NOT NULL,
    iss_centavos INTEGER NOT NULL,
    situacao TEXT NOT NULL,
    chave_acesso TEXT,
    xml_nfse TEXT,
    mensagem TEXT,
    emitida_em TEXT NOT NULL,
    cancelada_em TEXT,
    motivo_cancelamento TEXT,
    UNIQUE (cliente_id, numero_dps)
);
"""


@dataclass
class Cliente:
    id: int
    cnpj: str
    razao_social: str
    municipio_ibge: str
    municipio_nome: str
    opcao_simples: str
    aliquota_iss: str
    prazo_cancelamento_dias: int | None
    serie_dps: str
    criado_em: str


@dataclass
class Nota:
    id: int
    cliente_id: int
    numero_dps: int
    codigo_servico: str
    tomador_tipo: str
    tomador_documento: str
    tomador_nome: str
    descricao: str
    valor_centavos: int
    iss_centavos: int
    situacao: str  # autorizada | rejeitada | cancelada
    chave_acesso: str | None
    xml_nfse: str | None
    mensagem: str | None
    emitida_em: str
    cancelada_em: str | None
    motivo_cancelamento: str | None


class Repositorio:
    def __init__(self, caminho: Path | str):
        if str(caminho) != ":memory:":
            Path(caminho).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(caminho), check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys = ON")
        self.con.executescript(ESQUEMA)

    # ------------------------------------------------------------ clientes

    def criar_cliente(
        self,
        cnpj: str,
        razao_social: str,
        municipio_ibge: str,
        municipio_nome: str,
        aliquota_iss: str,
        opcao_simples: str = "3",
        prazo_cancelamento_dias: int | None = None,
    ) -> Cliente:
        with self.con:
            cur = self.con.execute(
                """INSERT INTO clientes (cnpj, razao_social, municipio_ibge, municipio_nome,
                   opcao_simples, aliquota_iss, prazo_cancelamento_dias, criado_em)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (cnpj, razao_social, municipio_ibge, municipio_nome, opcao_simples,
                 aliquota_iss, prazo_cancelamento_dias, datetime.now().astimezone().isoformat()),
            )
        return self.buscar_cliente(cur.lastrowid)

    def buscar_cliente(self, cliente_id: int) -> Cliente | None:
        linha = self.con.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
        return Cliente(**dict(linha)) if linha else None

    def listar_clientes(self) -> list[Cliente]:
        linhas = self.con.execute("SELECT * FROM clientes ORDER BY razao_social").fetchall()
        return [Cliente(**dict(l)) for l in linhas]

    # ------------------------------------------------------------ serviços

    def definir_servicos_liberados(self, cliente_id: int, servicos: list[tuple[str, str]]) -> None:
        """Substitui toda a lista de serviços liberados (codigo, apelido)."""
        with self.con:
            self.con.execute("DELETE FROM servicos_liberados WHERE cliente_id = ?", (cliente_id,))
            self.con.executemany(
                "INSERT INTO servicos_liberados (cliente_id, codigo, apelido) VALUES (?, ?, ?)",
                [(cliente_id, codigo, apelido) for codigo, apelido in servicos],
            )

    def servicos_liberados(self, cliente_id: int) -> list[dict]:
        linhas = self.con.execute(
            "SELECT codigo, apelido FROM servicos_liberados WHERE cliente_id = ? ORDER BY apelido",
            (cliente_id,),
        ).fetchall()
        return [dict(l) for l in linhas]

    # ------------------------------------------------------------ notas

    def proximo_numero_dps(self, cliente_id: int) -> int:
        linha = self.con.execute(
            "SELECT COALESCE(MAX(numero_dps), 0) + 1 FROM notas WHERE cliente_id = ?",
            (cliente_id,),
        ).fetchone()
        return int(linha[0])

    def salvar_nota(self, **campos) -> Nota:
        colunas = ", ".join(campos)
        marcadores = ", ".join("?" for _ in campos)
        with self.con:
            cur = self.con.execute(
                f"INSERT INTO notas ({colunas}) VALUES ({marcadores})", tuple(campos.values())
            )
        return self.buscar_nota(cur.lastrowid)

    def buscar_nota(self, nota_id: int) -> Nota | None:
        linha = self.con.execute("SELECT * FROM notas WHERE id = ?", (nota_id,)).fetchone()
        return Nota(**dict(linha)) if linha else None

    def listar_notas(self, cliente_id: int) -> list[Nota]:
        linhas = self.con.execute(
            "SELECT * FROM notas WHERE cliente_id = ? ORDER BY id DESC", (cliente_id,)
        ).fetchall()
        return [Nota(**dict(l)) for l in linhas]

    def marcar_cancelada(self, nota_id: int, motivo: str, quando: str) -> Nota:
        with self.con:
            self.con.execute(
                "UPDATE notas SET situacao = 'cancelada', cancelada_em = ?, motivo_cancelamento = ? WHERE id = ?",
                (quando, motivo, nota_id),
            )
        return self.buscar_nota(nota_id)
