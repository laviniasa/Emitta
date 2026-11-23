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
    cnpj TEXT NOT NULL,
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
    cert_titular TEXT,
    contador_id INTEGER REFERENCES usuarios(id),
    UNIQUE (contador_id, cnpj)
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
    papel TEXT NOT NULL CHECK (papel IN ('admin', 'contador', 'empresa', 'autonomo')),
    cliente_id INTEGER REFERENCES clientes(id) ON DELETE CASCADE,
    trocar_senha INTEGER NOT NULL DEFAULT 0,
    totp_segredo TEXT,
    totp_ativo INTEGER NOT NULL DEFAULT 0,
    totp_ultimo_passo INTEGER,
    falhas_seguidas INTEGER NOT NULL DEFAULT 0,
    bloqueado_ate TEXT,
    criado_em TEXT NOT NULL,
    ativo INTEGER NOT NULL DEFAULT 1,
    ultimo_acesso TEXT,
    aprovado INTEGER NOT NULL DEFAULT 1,
    CHECK (papel = 'autonomo' OR (papel = 'empresa') = (cliente_id IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quando TEXT NOT NULL,
    tipo TEXT NOT NULL,
    usuario_id INTEGER,
    email TEXT,
    papel TEXT,
    detalhe TEXT,
    ip TEXT
);
CREATE INDEX IF NOT EXISTS eventos_quando ON eventos (quando DESC);

CREATE TABLE IF NOT EXISTS sessoes (
    token_hash TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    criada_em TEXT NOT NULL,
    expira_em TEXT NOT NULL,
    ultimo_uso TEXT NOT NULL
);

-- Guias e documentos que o contador manda para a empresa (DARF, DAS, ISS...)
CREATE TABLE IF NOT EXISTS documentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL,
    titulo TEXT NOT NULL,
    competencia TEXT,
    valor_centavos INTEGER,
    vencimento TEXT,
    arquivo_nome TEXT NOT NULL,
    arquivo BLOB NOT NULL,
    tamanho INTEGER NOT NULL,
    enviado_por INTEGER,
    criado_em TEXT NOT NULL,
    visto_em TEXT,
    pago_em TEXT
);
CREATE INDEX IF NOT EXISTS documentos_cliente ON documentos (cliente_id, criado_em DESC);

-- NFS-e em que a empresa é a tomadora (distribuídas pelo ADN)
CREATE TABLE IF NOT EXISTS notas_recebidas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    nsu INTEGER NOT NULL,
    chave TEXT NOT NULL,
    numero TEXT,
    emitida_em TEXT,
    emitente_documento TEXT,
    emitente_nome TEXT,
    descricao TEXT,
    codigo_servico TEXT,
    valor_centavos INTEGER,
    situacao TEXT NOT NULL DEFAULT 'autorizada',
    xml TEXT NOT NULL,
    recebida_em TEXT NOT NULL,
    UNIQUE (cliente_id, chave)
);
CREATE INDEX IF NOT EXISTS notas_recebidas_cliente ON notas_recebidas (cliente_id, emitida_em DESC);

-- Nota recorrente: emitida sozinha todo mês, no dia escolhido
CREATE TABLE IF NOT EXISTS recorrencias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    codigo_servico TEXT NOT NULL,
    tomador_documento TEXT NOT NULL,
    tomador_nome TEXT NOT NULL,
    valor_centavos INTEGER NOT NULL,
    descricao TEXT,
    info_compl TEXT,
    iss_retido INTEGER NOT NULL DEFAULT 0,
    dia INTEGER NOT NULL CHECK (dia BETWEEN 1 AND 28),
    ativa INTEGER NOT NULL DEFAULT 1,
    criada_em TEXT NOT NULL,
    criada_por INTEGER,
    ultimo_mes TEXT,          -- AAAA-MM do último mês já resolvido (emitida ou com erro)
    ultima_nota_id INTEGER,
    ultimo_erro TEXT,
    ultima_tentativa_em TEXT,
    tentativa INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS recorrencias_cliente ON recorrencias (cliente_id);

-- Contato do escritório de contabilidade que aparece no PDF das notas
CREATE TABLE IF NOT EXISTS escritorios (
    contador_id INTEGER PRIMARY KEY REFERENCES usuarios(id) ON DELETE CASCADE,
    nome TEXT,
    telefone TEXT,
    email TEXT
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
    contador_id: int | None = None
    abertura: str | None = None          # data de abertura do CNPJ (limite proporcional do MEI)
    adn_ult_nsu: int = 0                 # último NSU lido no ADN (notas recebidas)
    adn_buscado_em: str | None = None

    def publico(self) -> dict:
        """Dados que podem sair na API (sem o certificado cifrado)."""
        d = {k: v for k, v in self.__dict__.items() if not k.startswith(("cert_", "adn_ult"))}
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
    info_compl: str | None = None
    ibscbs: str | None = None  # JSON com NBS, cIndOp, CST e cClassTrib usados na nota


@dataclass
class Usuario:
    id: int
    email: str
    nome: str
    senha_hash: str
    papel: str  # admin | contador | empresa
    cliente_id: int | None
    trocar_senha: int
    totp_segredo: str | None
    totp_ativo: int
    totp_ultimo_passo: int | None
    falhas_seguidas: int
    bloqueado_ate: str | None
    criado_em: str
    ativo: int = 1
    ultimo_acesso: str | None = None
    aprovado: int = 1  # contador novo fica 0 até a administração aprovar


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
        "usuarios": {"ativo": "INTEGER NOT NULL DEFAULT 1", "ultimo_acesso": "TEXT",
                     "aprovado": "INTEGER NOT NULL DEFAULT 1"},
        "clientes": {
            "contador_id": "INTEGER",
            "reg_ap_trib_sn": "TEXT NOT NULL DEFAULT '1'", "p_tot_trib_sn": "TEXT",
            "cert_pfx_cifrado": "BLOB", "cert_senha_cifrada": "BLOB",
            "cert_validade": "TEXT", "cert_titular": "TEXT",
            "abertura": "TEXT", "adn_ult_nsu": "INTEGER NOT NULL DEFAULT 0", "adn_buscado_em": "TEXT",
        },
        "servicos_liberados": {"codigo_municipal": "TEXT", "nbs": "TEXT", "cind_op": "TEXT", "cclass_trib": "TEXT"},
        "notas": {
            "competencia": "TEXT", "iss_retido": "INTEGER NOT NULL DEFAULT 0", "id_dps": "TEXT",
            "xml_dps": "TEXT", "chave_envio": "TEXT", "info_compl": "TEXT", "ibscbs": "TEXT",
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
            # Bancos antigos só aceitavam admin/contador/empresa: o SQLite não muda um
            # CHECK com ALTER, então ajusta o texto da tabela (seguro: só amplia a regra).
            sql = self.con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='usuarios'").fetchone()
            if sql and "'autonomo'" not in sql[0]:
                novo = (sql[0].replace("('admin', 'contador', 'empresa')", "('admin', 'contador', 'empresa', 'autonomo')")
                        .replace("CHECK ((papel = 'empresa') = (cliente_id IS NOT NULL))",
                                 "CHECK (papel = 'autonomo' OR (papel = 'empresa') = (cliente_id IS NOT NULL))"))
                if novo != sql[0]:
                    versao = self.con.execute("PRAGMA schema_version").fetchone()[0]
                    self.con.execute("PRAGMA writable_schema = ON")
                    self.con.execute("UPDATE sqlite_master SET sql = ? WHERE type='table' AND name='usuarios'", (novo,))
                    self.con.execute(f"PRAGMA schema_version = {versao + 1}")
                    self.con.execute("PRAGMA writable_schema = OFF")

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
        contador_id: int | None = None,
    ) -> Cliente:
        with self.con:
            cur = self.con.execute(
                """INSERT INTO clientes (cnpj, razao_social, municipio_ibge, municipio_nome,
                   opcao_simples, aliquota_iss, prazo_cancelamento_dias, criado_em,
                   p_tot_trib_sn, reg_ap_trib_sn, contador_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (cnpj, razao_social, municipio_ibge, municipio_nome, opcao_simples,
                 aliquota_iss, prazo_cancelamento_dias, datetime.now().astimezone().isoformat(),
                 p_tot_trib_sn, reg_ap_trib_sn, contador_id),
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

    # ------------------------------------------------------------ notas recorrentes

    _CAMPOS_RECORRENCIA = ("codigo_servico", "tomador_documento", "tomador_nome", "valor_centavos", "descricao",
                           "info_compl", "iss_retido", "dia", "ativa")

    def criar_recorrencia(self, cliente_id: int, criada_por: int | None, **campos) -> dict:
        nomes = [c for c in self._CAMPOS_RECORRENCIA if c in campos]
        with self.con:
            cur = self.con.execute(
                f"INSERT INTO recorrencias (cliente_id, criada_por, criada_em, {', '.join(nomes)}) "
                f"VALUES (?, ?, ?, {', '.join('?' for _ in nomes)})",
                (cliente_id, criada_por, datetime.now().astimezone().isoformat(), *[campos[c] for c in nomes]))
        return self.buscar_recorrencia(cur.lastrowid)

    def buscar_recorrencia(self, recorrencia_id: int) -> dict | None:
        linha = self.con.execute("SELECT * FROM recorrencias WHERE id = ?", (recorrencia_id,)).fetchone()
        return dict(linha) if linha else None

    def recorrencias(self, cliente_id: int | None = None, so_ativas: bool = False) -> list[dict]:
        sql, args = "SELECT * FROM recorrencias WHERE 1=1", []
        if cliente_id is not None:
            sql += " AND cliente_id = ?"; args.append(cliente_id)
        if so_ativas:
            sql += " AND ativa = 1"
        return [dict(l) for l in self.con.execute(sql + " ORDER BY dia, id", args)]

    def atualizar_recorrencia(self, recorrencia_id: int, **campos) -> dict:
        permitidos = set(self._CAMPOS_RECORRENCIA) | {"ultimo_mes", "ultima_nota_id", "ultimo_erro", "ultima_tentativa_em", "tentativa"}
        nomes = [c for c in campos if c in permitidos]
        if nomes:
            with self.con:
                self.con.execute(f"UPDATE recorrencias SET {', '.join(f'{c} = ?' for c in nomes)} WHERE id = ?",
                                 (*[campos[c] for c in nomes], recorrencia_id))
        return self.buscar_recorrencia(recorrencia_id)

    def apagar_recorrencia(self, recorrencia_id: int) -> None:
        with self.con:
            self.con.execute("DELETE FROM recorrencias WHERE id = ?", (recorrencia_id,))

    # ------------------------------------------------------------ contato do escritório

    def escritorio(self, contador_id: int) -> dict:
        linha = self.con.execute("SELECT nome, telefone, email FROM escritorios WHERE contador_id = ?", (contador_id,)).fetchone()
        return dict(linha) if linha else {"nome": None, "telefone": None, "email": None}

    def salvar_escritorio(self, contador_id: int, nome: str | None, telefone: str | None, email: str | None) -> dict:
        with self.con:
            self.con.execute(
                "INSERT INTO escritorios (contador_id, nome, telefone, email) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (contador_id) DO UPDATE SET nome = excluded.nome, telefone = excluded.telefone, email = excluded.email",
                (contador_id, nome, telefone, email))
        return self.escritorio(contador_id)

    def contar_notas(self, cliente_id: int) -> int:
        return int(self.con.execute("SELECT COUNT(*) FROM notas WHERE cliente_id = ?", (cliente_id,)).fetchone()[0])

    def remover_cliente(self, cliente_id: int) -> None:
        """Apaga a empresa e tudo dela no Emitta: notas guardadas, serviços, guias, notas recebidas
        e os logins da empresa (com as sessões). As notas continuam no Emissor Nacional do governo."""
        with self.con:
            self.con.execute("DELETE FROM notas WHERE cliente_id = ?", (cliente_id,))
            self.con.execute("DELETE FROM clientes WHERE id = ?", (cliente_id,))

    def remover_certificado(self, cliente_id: int) -> Cliente:
        with self.con:
            self.con.execute(
                """UPDATE clientes SET cert_pfx_cifrado = NULL, cert_senha_cifrada = NULL,
                   cert_validade = NULL, cert_titular = NULL WHERE id = ?""", (cliente_id,))
        return self.buscar_cliente(cliente_id)

    def listar_clientes(self, contador_id: int | None = None) -> list[Cliente]:
        """Empresas de um contador (separação por login)."""
        linhas = self.con.execute(
            "SELECT * FROM clientes WHERE contador_id IS ? ORDER BY razao_social", (contador_id,)
        ).fetchall()
        return [Cliente(**dict(l)) for l in linhas]

    # ------------------------------------------------------------ serviços

    def definir_servicos_liberados(self, cliente_id: int, servicos: list[tuple]) -> None:
        """Substitui toda a lista de serviços liberados:
        (codigo, apelido[, codigo_municipal[, nbs, cind_op, cclass_trib]])."""
        def campo(s, i):
            return (s[i] if len(s) > i else None) or None
        linhas = [(cliente_id, s[0], s[1], campo(s, 2), campo(s, 3), campo(s, 4), campo(s, 5)) for s in servicos]
        with self.con:
            self.con.execute("DELETE FROM servicos_liberados WHERE cliente_id = ?", (cliente_id,))
            self.con.executemany(
                "INSERT INTO servicos_liberados (cliente_id, codigo, apelido, codigo_municipal, nbs, cind_op, cclass_trib)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                linhas,
            )

    def definir_codigo_municipal(self, cliente_id: int, codigo: str, codigo_municipal: str) -> None:
        with self.con:
            self.con.execute("UPDATE servicos_liberados SET codigo_municipal = ? WHERE cliente_id = ? AND codigo = ?",
                             (codigo_municipal, cliente_id, codigo))

    def servicos_liberados(self, cliente_id: int) -> list[dict]:
        linhas = self.con.execute(
            "SELECT codigo, apelido, codigo_municipal, nbs, cind_op, cclass_trib FROM servicos_liberados"
            " WHERE cliente_id = ? ORDER BY apelido",
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
            "SELECT * FROM notas WHERE cliente_id = ? AND situacao != 'descartada' ORDER BY id DESC", (cliente_id,)
        ).fetchall()
        return [Nota(**dict(l)) for l in linhas]

    def buscar_nota_por_chave_envio(self, cliente_id: int, chave_envio: str) -> Nota | None:
        linha = self.con.execute(
            "SELECT * FROM notas WHERE cliente_id = ? AND chave_envio = ?", (cliente_id, chave_envio)
        ).fetchone()
        return Nota(**dict(linha)) if linha else None

    _CAMPOS_NOTA = {"situacao", "chave_acesso", "xml_nfse", "mensagem"}

    def descartar_nota(self, nota_id: int) -> None:
        """Número recusado por já existir no governo (E0014): some das listas e libera a chave de envio."""
        with self.con:
            self.con.execute("UPDATE notas SET situacao = 'descartada', chave_envio = NULL WHERE id = ?", (nota_id,))

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

    # ---------------------------------------------------------------- resumo do escritório
    # ------------------------------------------------------------ resumo do ano

    def faturamento_por_mes(self, cliente_id: int, ano: int) -> list[dict]:
        """Notas autorizadas (sem as canceladas) de cada mês do ano: [{mes, notas, valor_centavos}] x 12."""
        meses = {m: [0, 0] for m in range(1, 13)}
        for r in self.con.execute(
            "SELECT CAST(substr(emitida_em, 6, 2) AS INTEGER) AS mes, COUNT(*) AS q, SUM(valor_centavos) AS v FROM notas"
            " WHERE cliente_id = ? AND situacao = 'autorizada' AND substr(emitida_em, 1, 4) = ? GROUP BY mes",
                (cliente_id, f"{ano:04d}")):
            meses[r["mes"]] = [r["q"], r["v"] or 0]
        return [{"mes": m, "notas": q, "valor_centavos": v} for m, (q, v) in meses.items()]

    def faturamento_ano_por_cliente(self, contador_id: int, ano: int) -> dict[int, int]:
        return {r["cliente_id"]: r["v"] or 0 for r in self.con.execute(
            "SELECT n.cliente_id, SUM(n.valor_centavos) AS v FROM notas n JOIN clientes c ON c.id = n.cliente_id"
            " WHERE c.contador_id = ? AND n.situacao = 'autorizada' AND substr(n.emitida_em, 1, 4) = ?"
            " GROUP BY n.cliente_id", (contador_id, f"{ano:04d}"))}

    def definir_abertura(self, cliente_id: int, abertura: str) -> None:
        with self.con:
            self.con.execute("UPDATE clientes SET abertura = ? WHERE id = ?", (abertura, cliente_id))

    # ------------------------------------------------------------ notas recebidas (ADN)

    def guardar_nota_recebida(self, cliente_id: int, d: dict) -> bool:
        """Guarda (ou atualiza, se veio um cancelamento) uma nota recebida. Devolve True se é nova."""
        with self.con:
            cur = self.con.execute(
                """INSERT INTO notas_recebidas (cliente_id, nsu, chave, numero, emitida_em, emitente_documento,
                   emitente_nome, descricao, codigo_servico, valor_centavos, situacao, xml, recebida_em)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (cliente_id, chave) DO NOTHING""",
                (cliente_id, d["nsu"], d["chave"], d.get("numero"), d.get("emitida_em"), d.get("emitente_documento"),
                 d.get("emitente_nome"), d.get("descricao"), d.get("codigo_servico"), d.get("valor_centavos"),
                 d.get("situacao", "autorizada"), d["xml"], datetime.now().astimezone().isoformat()))
            return cur.rowcount == 1

    def marcar_recebida_cancelada(self, cliente_id: int, chave: str) -> None:
        with self.con:
            self.con.execute("UPDATE notas_recebidas SET situacao = 'cancelada' WHERE cliente_id = ? AND chave = ?",
                             (cliente_id, chave))

    def avancar_nsu(self, cliente_id: int, nsu: int) -> None:
        with self.con:
            self.con.execute("UPDATE clientes SET adn_ult_nsu = MAX(adn_ult_nsu, ?), adn_buscado_em = ? WHERE id = ?",
                             (nsu, datetime.now().astimezone().isoformat(), cliente_id))

    def notas_recebidas(self, cliente_id: int, mes: str | None = None) -> list[dict]:
        sql = ("SELECT id, nsu, chave, numero, emitida_em, emitente_documento, emitente_nome, descricao,"
               " codigo_servico, valor_centavos, situacao FROM notas_recebidas WHERE cliente_id = ?")
        args: list = [cliente_id]
        if mes:
            sql += " AND substr(emitida_em, 1, 7) = ?"
            args.append(mes)
        return [dict(r) for r in self.con.execute(sql + " ORDER BY emitida_em DESC, id DESC", args)]

    def xml_nota_recebida(self, cliente_id: int, recebida_id: int) -> dict | None:
        r = self.con.execute("SELECT chave, numero, xml FROM notas_recebidas WHERE cliente_id = ? AND id = ?",
                             (cliente_id, recebida_id)).fetchone()
        return dict(r) if r else None

    def notas_autorizadas_do_contador(self, contador_id: int, desde: str) -> list[dict]:
        """Notas autorizadas (ou já canceladas depois) das empresas do contador, emitidas desde `desde`."""
        return [dict(r) for r in self.con.execute(
            "SELECT n.emitida_em, n.valor_centavos, n.situacao FROM notas n JOIN clientes c ON c.id = n.cliente_id"
            " WHERE c.contador_id = ? AND n.situacao = 'autorizada' AND n.emitida_em >= ?",
            (contador_id, desde))]

    def notas_do_contador(self, contador_id: int, mes: str | None = None, cliente_id: int | None = None,
                          situacao: str | None = None, limite: int = 2000) -> list[Nota]:
        """Notas de todas as empresas do contador (sem as descartadas), mais novas primeiro."""
        sql = ("SELECT n.* FROM notas n JOIN clientes c ON c.id = n.cliente_id"
               " WHERE c.contador_id = ? AND n.situacao != 'descartada'")
        args: list = [contador_id]
        if mes:
            sql += " AND substr(n.emitida_em, 1, 7) = ?"
            args.append(mes)
        if cliente_id:
            sql += " AND n.cliente_id = ?"
            args.append(cliente_id)
        if situacao:
            sql += " AND n.situacao = ?"
            args.append(situacao)
        sql += " ORDER BY n.emitida_em DESC, n.id DESC LIMIT ?"
        args.append(limite)
        return [Nota(**dict(l)) for l in self.con.execute(sql, args)]

    def guias_vencidas_por_cliente(self, contador_id: int, hoje: str) -> dict[int, int]:
        return {r[0]: r[1] for r in self.con.execute(
            "SELECT d.cliente_id, COUNT(*) FROM documentos d JOIN clientes c ON c.id = d.cliente_id"
            " WHERE c.contador_id = ? AND d.pago_em IS NULL AND d.vencimento IS NOT NULL AND d.vencimento < ?"
            " GROUP BY d.cliente_id", (contador_id, hoje))}

    def guias_do_contador(self, contador_id: int) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT d.vencimento, d.pago_em, d.visto_em FROM documentos d JOIN clientes c ON c.id = d.cliente_id"
            " WHERE c.contador_id = ?", (contador_id,))]

    # ---------------------------------------------------------------- documentos
    _CAMPOS_DOC = "id, cliente_id, tipo, titulo, competencia, valor_centavos, vencimento, arquivo_nome, tamanho, enviado_por, criado_em, visto_em, pago_em"

    def criar_documento(self, cliente_id: int, tipo: str, titulo: str, competencia: str | None, valor_centavos: int | None,
                        vencimento: str | None, arquivo_nome: str, arquivo: bytes, enviado_por: int | None, criado_em: str) -> dict:
        with self.con:
            cur = self.con.execute(
                "INSERT INTO documentos (cliente_id, tipo, titulo, competencia, valor_centavos, vencimento, arquivo_nome,"
                " arquivo, tamanho, enviado_por, criado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (cliente_id, tipo, titulo, competencia, valor_centavos, vencimento, arquivo_nome, arquivo, len(arquivo),
                 enviado_por, criado_em))
        return self.buscar_documento(cur.lastrowid)

    def buscar_documento(self, doc_id: int) -> dict | None:
        r = self.con.execute(f"SELECT {self._CAMPOS_DOC} FROM documentos WHERE id = ?", (doc_id,)).fetchone()
        return dict(r) if r else None

    def arquivo_documento(self, doc_id: int) -> bytes | None:
        r = self.con.execute("SELECT arquivo FROM documentos WHERE id = ?", (doc_id,)).fetchone()
        return bytes(r[0]) if r else None

    def listar_documentos(self, cliente_id: int) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            f"SELECT {self._CAMPOS_DOC} FROM documentos WHERE cliente_id = ? ORDER BY COALESCE(vencimento, '9999') DESC, id DESC",
            (cliente_id,))]

    def atualizar_documento(self, doc_id: int, **campos) -> dict:
        permitidos = {"visto_em", "pago_em"}
        assert set(campos) <= permitidos
        with self.con:
            self.con.execute(f"UPDATE documentos SET {', '.join(f'{k} = ?' for k in campos)} WHERE id = ?",
                             (*campos.values(), doc_id))
        return self.buscar_documento(doc_id)

    def apagar_documento(self, doc_id: int) -> None:
        with self.con:
            self.con.execute("DELETE FROM documentos WHERE id = ?", (doc_id,))

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

    def apagar_usuario(self, usuario_id: int) -> None:
        with self.con:
            self.con.execute("DELETE FROM usuarios WHERE id = ?", (usuario_id,))

    def usuarios_da_empresa(self, cliente_id: int) -> list[Usuario]:
        linhas = self.con.execute(
            "SELECT * FROM usuarios WHERE cliente_id = ? ORDER BY nome", (cliente_id,)
        ).fetchall()
        return [Usuario(**dict(l)) for l in linhas]

    _CAMPOS_USUARIO = {
        "senha_hash", "trocar_senha", "totp_segredo", "totp_ativo", "totp_ultimo_passo",
        "falhas_seguidas", "bloqueado_ate", "nome", "ativo", "ultimo_acesso", "aprovado", "cliente_id",
    }

    def contar_admins(self) -> int:
        return int(self.con.execute("SELECT COUNT(*) FROM usuarios WHERE papel = 'admin'").fetchone()[0])

    def listar_usuarios(self) -> list[dict]:
        """Todas as contas, com a empresa e o contador responsável (para a administração)."""
        linhas = self.con.execute(
            """SELECT u.id, u.email, u.nome, u.papel, u.ativo, u.ultimo_acesso, u.criado_em,
                      u.bloqueado_ate, u.totp_ativo, u.trocar_senha, u.aprovado,
                      c.razao_social AS empresa, dono.nome AS contador
               FROM usuarios u
               LEFT JOIN clientes c ON c.id = u.cliente_id
               LEFT JOIN usuarios dono ON dono.id = c.contador_id
               ORDER BY u.papel, u.nome"""
        ).fetchall()
        return [dict(l) for l in linhas]

    def contar_empresas_por_contador(self) -> dict[int, int]:
        linhas = self.con.execute(
            "SELECT contador_id, COUNT(*) FROM clientes WHERE contador_id IS NOT NULL GROUP BY contador_id"
        ).fetchall()
        return {l[0]: l[1] for l in linhas}

    # ------------------------------------------------------------ eventos

    def registrar_evento(self, quando: str, tipo: str, usuario_id: int | None = None, email: str | None = None,
                         papel: str | None = None, detalhe: str | None = None, ip: str | None = None) -> None:
        with self.con:
            self.con.execute(
                "INSERT INTO eventos (quando, tipo, usuario_id, email, papel, detalhe, ip) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (quando, tipo, usuario_id, email, papel, detalhe, ip),
            )

    def listar_eventos(self, limite: int = 200, usuario_id: int | None = None, tipo: str | None = None) -> list[dict]:
        condicoes, valores = [], []
        if usuario_id is not None:
            condicoes.append("usuario_id = ?")
            valores.append(usuario_id)
        if tipo:
            condicoes.append("tipo = ?")
            valores.append(tipo)
        onde = ("WHERE " + " AND ".join(condicoes)) if condicoes else ""
        linhas = self.con.execute(
            f"SELECT * FROM eventos {onde} ORDER BY id DESC LIMIT ?", (*valores, limite)
        ).fetchall()
        return [dict(l) for l in linhas]

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
