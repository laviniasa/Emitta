"""Acesso ao banco SQLite (biblioteca padrão do Python, sem ORM)."""

from __future__ import annotations

import functools
import sqlite3
import threading
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
    criado_em TEXT NOT NULL,
    reg_ap_trib_sn TEXT NOT NULL DEFAULT '1',
    p_tot_trib_sn TEXT,
    cert_pfx_cifrado BLOB,
    cert_senha_cifrada BLOB,
    cert_validade TEXT,
    cert_titular TEXT
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
    competencia TEXT,
    iss_retido INTEGER NOT NULL DEFAULT 0,
    id_dps TEXT,
    xml_dps TEXT,
    chave_envio TEXT,
    UNIQUE (cliente_id, numero_dps),
    UNIQUE (cliente_id, chave_envio)
);

CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    nome TEXT NOT NULL,
    senha_hash TEXT NOT NULL,
    papel TEXT NOT NULL CHECK (papel IN ('contador', 'empresa')),
    cliente_id INTEGER REFERENCES clientes(id) ON DELETE CASCADE,
    trocar_senha INTEGER NOT NULL DEFAULT 0,
    totp_segredo TEXT,
    totp_ativo INTEGER NOT NULL DEFAULT 0,
    totp_ultimo_passo INTEGER,
    falhas_seguidas INTEGER NOT NULL DEFAULT 0,
    bloqueado_ate TEXT,
    criado_em TEXT NOT NULL,
    CHECK ((papel = 'empresa') = (cliente_id IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS sessoes (
    token_hash TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    criada_em TEXT NOT NULL,
    expira_em TEXT NOT NULL,
    ultimo_uso TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS desafios_2fa (
    token_hash TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    expira_em TEXT NOT NULL,
    tentativas INTEGER NOT NULL DEFAULT 0
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
    reg_ap_trib_sn: str = "1"
    p_tot_trib_sn: str | None = None
    cert_pfx_cifrado: bytes | None = None
    cert_senha_cifrada: bytes | None = None
    cert_validade: str | None = None
    cert_titular: str | None = None

    def publico(self) -> dict:
        """Dados que podem sair na API (sem o certificado cifrado)."""
        d = {k: v for k, v in self.__dict__.items() if not k.startswith("cert_")}
        d["certificado"] = (
            {"titular": self.cert_titular, "validade": self.cert_validade}
            if self.cert_pfx_cifrado else None
        )
        return d


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
    competencia: str | None = None
    iss_retido: int = 0
    id_dps: str | None = None
    xml_dps: str | None = None
    chave_envio: str | None = None


@dataclass
class Usuario:
    id: int
    email: str
    nome: str
    senha_hash: str
    papel: str  # contador | empresa
    cliente_id: int | None
    trocar_senha: int
    totp_segredo: str | None
    totp_ativo: int
    totp_ultimo_passo: int | None
    falhas_seguidas: int
    bloqueado_ate: str | None
    criado_em: str


def _com_trava(classe):
    """O servidor atende várias requisições ao mesmo tempo (em threads) e todas
    usam a mesma conexão SQLite. Esta trava garante que só uma operação use o
    banco por vez, evitando resultados misturados entre requisições."""
    for nome, metodo in list(vars(classe).items()):
        if callable(metodo) and not nome.startswith("_"):
            def envolver(m):
                @functools.wraps(m)
                def com_trava(self, *args, **kwargs):
                    with self._trava:
                        return m(self, *args, **kwargs)
                return com_trava
            setattr(classe, nome, envolver(metodo))
    return classe


@_com_trava
class Repositorio:
    def __init__(self, caminho: Path | str):
        if str(caminho) != ":memory:":
            Path(caminho).parent.mkdir(parents=True, exist_ok=True)
        self._trava = threading.RLock()
        self.con = sqlite3.connect(str(caminho), check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys = ON")
        self.con.executescript(ESQUEMA)
        self._migrar()

    # Colunas acrescentadas depois da primeira versão (bancos já existentes).
    _COLUNAS_NOVAS = {
        "clientes": {
            "reg_ap_trib_sn": "TEXT NOT NULL DEFAULT '1'", "p_tot_trib_sn": "TEXT",
            "cert_pfx_cifrado": "BLOB", "cert_senha_cifrada": "BLOB",
            "cert_validade": "TEXT", "cert_titular": "TEXT",
        },
        "notas": {
            "competencia": "TEXT", "iss_retido": "INTEGER NOT NULL DEFAULT 0", "id_dps": "TEXT",
            "xml_dps": "TEXT", "chave_envio": "TEXT",
        },
    }

    def _migrar(self) -> None:
        with self.con:
            for tabela, colunas in self._COLUNAS_NOVAS.items():
                existentes = {l[1] for l in self.con.execute(f"PRAGMA table_info({tabela})")}
                for nome, tipo in colunas.items():
                    if nome not in existentes:
                        self.con.execute(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}")
            self.con.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS notas_chave_envio ON notas (cliente_id, chave_envio)"
            )

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
        p_tot_trib_sn: str | None = None,
        reg_ap_trib_sn: str = "1",
    ) -> Cliente:
        with self.con:
            cur = self.con.execute(
                """INSERT INTO clientes (cnpj, razao_social, municipio_ibge, municipio_nome,
                   opcao_simples, aliquota_iss, prazo_cancelamento_dias, criado_em,
                   p_tot_trib_sn, reg_ap_trib_sn)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (cnpj, razao_social, municipio_ibge, municipio_nome, opcao_simples,
                 aliquota_iss, prazo_cancelamento_dias, datetime.now().astimezone().isoformat(),
                 p_tot_trib_sn, reg_ap_trib_sn),
            )
        return self.buscar_cliente(cur.lastrowid)

    def buscar_cliente(self, cliente_id: int) -> Cliente | None:
        linha = self.con.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
        return Cliente(**dict(linha)) if linha else None

    def guardar_certificado(self, cliente_id: int, pfx_cifrado: bytes, senha_cifrada: bytes,
                            validade: str, titular: str) -> Cliente:
        with self.con:
            self.con.execute(
                """UPDATE clientes SET cert_pfx_cifrado = ?, cert_senha_cifrada = ?,
                   cert_validade = ?, cert_titular = ? WHERE id = ?""",
                (pfx_cifrado, senha_cifrada, validade, titular, cliente_id),
            )
        return self.buscar_cliente(cliente_id)

    def remover_certificado(self, cliente_id: int) -> Cliente:
        with self.con:
            self.con.execute(
                """UPDATE clientes SET cert_pfx_cifrado = NULL, cert_senha_cifrada = NULL,
                   cert_validade = NULL, cert_titular = NULL WHERE id = ?""", (cliente_id,))
        return self.buscar_cliente(cliente_id)

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

    def buscar_nota_por_chave_envio(self, cliente_id: int, chave_envio: str) -> Nota | None:
        linha = self.con.execute(
            "SELECT * FROM notas WHERE cliente_id = ? AND chave_envio = ?", (cliente_id, chave_envio)
        ).fetchone()
        return Nota(**dict(linha)) if linha else None

    _CAMPOS_NOTA = {"situacao", "chave_acesso", "xml_nfse", "mensagem"}

    def atualizar_nota(self, nota_id: int, **campos) -> Nota:
        invalidos = set(campos) - self._CAMPOS_NOTA
        if invalidos:
            raise ValueError(f"Campos não permitidos: {invalidos}")
        atribuicoes = ", ".join(f"{c} = ?" for c in campos)
        with self.con:
            self.con.execute(f"UPDATE notas SET {atribuicoes} WHERE id = ?", (*campos.values(), nota_id))
        return self.buscar_nota(nota_id)

    def marcar_cancelada(self, nota_id: int, motivo: str, quando: str) -> Nota:
        with self.con:
            self.con.execute(
                "UPDATE notas SET situacao = 'cancelada', cancelada_em = ?, motivo_cancelamento = ? WHERE id = ?",
                (quando, motivo, nota_id),
            )
        return self.buscar_nota(nota_id)

    # ------------------------------------------------------------ usuários

    def contar_usuarios(self) -> int:
        return int(self.con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0])

    def criar_usuario(self, email: str, nome: str, senha_hash: str, papel: str,
                      cliente_id: int | None = None, trocar_senha: bool = False, criado_em: str = "") -> Usuario:
        with self.con:
            cur = self.con.execute(
                """INSERT INTO usuarios (email, nome, senha_hash, papel, cliente_id, trocar_senha, criado_em)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (email, nome, senha_hash, papel, cliente_id, int(trocar_senha), criado_em),
            )
        return self.buscar_usuario(cur.lastrowid)

    def buscar_usuario(self, usuario_id: int) -> Usuario | None:
        linha = self.con.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        return Usuario(**dict(linha)) if linha else None

    def buscar_usuario_por_email(self, email: str) -> Usuario | None:
        linha = self.con.execute("SELECT * FROM usuarios WHERE email = ?", (email,)).fetchone()
        return Usuario(**dict(linha)) if linha else None

    def usuarios_da_empresa(self, cliente_id: int) -> list[Usuario]:
        linhas = self.con.execute(
            "SELECT * FROM usuarios WHERE cliente_id = ? ORDER BY nome", (cliente_id,)
        ).fetchall()
        return [Usuario(**dict(l)) for l in linhas]

    _CAMPOS_USUARIO = {
        "senha_hash", "trocar_senha", "totp_segredo", "totp_ativo", "totp_ultimo_passo",
        "falhas_seguidas", "bloqueado_ate", "nome",
    }

    def atualizar_usuario(self, usuario_id: int, **campos) -> Usuario:
        invalidos = set(campos) - self._CAMPOS_USUARIO
        if invalidos:
            raise ValueError(f"Campos não permitidos: {invalidos}")
        atribuicoes = ", ".join(f"{c} = ?" for c in campos)
        with self.con:
            self.con.execute(f"UPDATE usuarios SET {atribuicoes} WHERE id = ?", (*campos.values(), usuario_id))
        return self.buscar_usuario(usuario_id)

    # ------------------------------------------------------------ sessões

    def criar_sessao(self, token_hash: str, usuario_id: int, criada_em: str, expira_em: str) -> None:
        with self.con:
            self.con.execute(
                "INSERT INTO sessoes (token_hash, usuario_id, criada_em, expira_em, ultimo_uso) VALUES (?, ?, ?, ?, ?)",
                (token_hash, usuario_id, criada_em, expira_em, criada_em),
            )

    def buscar_sessao(self, token_hash: str) -> dict | None:
        linha = self.con.execute("SELECT * FROM sessoes WHERE token_hash = ?", (token_hash,)).fetchone()
        return dict(linha) if linha else None

    def tocar_sessao(self, token_hash: str, quando: str) -> None:
        with self.con:
            self.con.execute("UPDATE sessoes SET ultimo_uso = ? WHERE token_hash = ?", (quando, token_hash))

    def apagar_sessao(self, token_hash: str) -> None:
        with self.con:
            self.con.execute("DELETE FROM sessoes WHERE token_hash = ?", (token_hash,))

    def apagar_sessoes_do_usuario(self, usuario_id: int, exceto: str | None = None) -> None:
        with self.con:
            self.con.execute(
                "DELETE FROM sessoes WHERE usuario_id = ? AND token_hash IS NOT ?", (usuario_id, exceto)
            )

    # ------------------------------------------------------------ desafios 2FA

    def criar_desafio(self, token_hash: str, usuario_id: int, expira_em: str) -> None:
        with self.con:
            self.con.execute("DELETE FROM desafios_2fa WHERE usuario_id = ?", (usuario_id,))
            self.con.execute(
                "INSERT INTO desafios_2fa (token_hash, usuario_id, expira_em) VALUES (?, ?, ?)",
                (token_hash, usuario_id, expira_em),
            )

    def buscar_desafio(self, token_hash: str) -> dict | None:
        linha = self.con.execute("SELECT * FROM desafios_2fa WHERE token_hash = ?", (token_hash,)).fetchone()
        return dict(linha) if linha else None

    def contar_tentativa_desafio(self, token_hash: str) -> None:
        with self.con:
            self.con.execute("UPDATE desafios_2fa SET tentativas = tentativas + 1 WHERE token_hash = ?", (token_hash,))

    def apagar_desafio(self, token_hash: str) -> None:
        with self.con:
            self.con.execute("DELETE FROM desafios_2fa WHERE token_hash = ?", (token_hash,))
