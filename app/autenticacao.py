"""Contas, login, sessões e 2FA.

Regras de segurança:
- senha forte obrigatória (mínimo 10 caracteres, sem senhas óbvias);
- 5 erros seguidos bloqueiam a conta por 15 minutos;
- mensagens de erro não revelam se o e-mail existe;
- sessão expira em 12 h, ou em 2 h sem uso;
- trocar a senha encerra as outras sessões;
- 2FA opcional (obrigatório recomendar ao contador), com código de uso único.
"""

from __future__ import annotations

import hmac
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import seguranca as seg
from .regras import ErroDeNegocio
from .repositorio import Repositorio, Usuario

MAX_FALHAS = 5
BLOQUEIO = timedelta(minutes=15)
DURACAO_SESSAO = timedelta(hours=12)
SESSAO_OCIOSA = timedelta(hours=2)
SESSAO_OCIOSA_ADMIN = timedelta(minutes=30)
DURACAO_DESAFIO = timedelta(minutes=5)
MAX_TENTATIVAS_DESAFIO = 5

MSG_LOGIN_INVALIDO = "E-mail ou senha incorretos."
MSG_BLOQUEADO = "Muitas tentativas. Por segurança, aguarde 15 minutos e tente de novo."


class ErroAutenticacao(ErroDeNegocio):
    pass


class AcessoNegado(ErroDeNegocio):
    pass


class ContaDesativada(ErroAutenticacao):
    pass


class ContaPendente(ErroAutenticacao):
    pass


MSG_PENDENTE = ("Sua conta ainda está aguardando aprovação do Emitta. "
                "Você vai conseguir entrar assim que ela for liberada.")


@dataclass
class ResultadoLogin:
    token_sessao: str | None = None
    desafio_2fa: str | None = None
    usuario: Usuario | None = None


def _iso(d: datetime) -> str:
    return d.isoformat()


def _de_iso(t: str) -> datetime:
    return datetime.fromisoformat(t)


_EMAIL_VALIDO = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9\-]+(\.[a-z0-9\-]+)*\.[a-z]{2,}$")


def normalizar_email(email: str) -> str:
    email = (email or "").strip().lower()
    # Celulares às vezes colam o e-mail como link ("mailto:fulano@...").
    if email.startswith("mailto:"):
        email = email[len("mailto:"):].split("?")[0].strip()
    if len(email) > 254 or not _EMAIL_VALIDO.match(email):
        raise ErroAutenticacao("Informe um e-mail válido, por exemplo nome@empresa.com.br.")
    return email


class ServicoAutenticacao:
    def __init__(self, repo: Repositorio, relogio=lambda: datetime.now(timezone.utc),
                 codigo_instalacao: str | None = None):
        self.repo = repo
        self.agora = relogio
        self.codigo_instalacao = codigo_instalacao if codigo_instalacao is not None else os.getenv("EMITTA_CODIGO_INSTALACAO")

    # ------------------------------------------------------------ instalação

    def precisa_instalar(self) -> bool:
        """Ainda não existe a conta de administração da plataforma."""
        return self.repo.contar_admins() == 0

    def instalar(self, codigo: str, nome: str, email: str, senha: str) -> Usuario:
        """Cria a conta de ADMINISTRAÇÃO da plataforma (dona do Emitta). Exige o
        código da variável EMITTA_CODIGO_INSTALACAO e só funciona uma vez."""
        if not self.precisa_instalar():
            raise AcessoNegado("A administração já foi configurada. Entre com a sua conta.")
        if not self.codigo_instalacao:
            raise AcessoNegado("Instalação desativada: defina EMITTA_CODIGO_INSTALACAO no servidor.")
        if not hmac.compare_digest((codigo or "").strip().encode(), self.codigo_instalacao.encode()):
            raise AcessoNegado("Código de instalação incorreto.")
        return self.criar_usuario(nome, email, senha, papel="admin")

    def cadastrar_contador(self, nome: str, email: str, senha: str) -> Usuario:
        """Contador pede a própria conta. Ela só funciona depois que a
        administração aprovar. Ele só enxerga o que cadastrar."""
        usuario = self.criar_usuario(nome, email, senha, papel="contador")
        return self.repo.atualizar_usuario(usuario.id, aprovado=0)

    # ------------------------------------------------------------ contas

    def criar_usuario(self, nome: str, email: str, senha: str, papel: str,
                      cliente_id: int | None = None, trocar_senha: bool = False) -> Usuario:
        email = normalizar_email(email)
        nome = (nome or "").strip()
        if not nome:
            raise ErroAutenticacao("Informe o nome.")
        problema = seg.problema_na_senha(senha, email)
        if problema:
            raise ErroAutenticacao(problema)
        if self.repo.buscar_usuario_por_email(email):
            raise ErroAutenticacao("Já existe uma conta com esse e-mail.")
        return self.repo.criar_usuario(
            email=email, nome=nome, senha_hash=seg.hash_senha(senha), papel=papel,
            cliente_id=cliente_id, trocar_senha=trocar_senha, criado_em=_iso(self.agora()),
        )

    def criar_acesso_empresa(self, cliente_id: int, nome: str, email: str) -> tuple[Usuario, str]:
        """Cria (ou redefine) o acesso de uma empresa. Devolve a senha provisória,
        que deve ser trocada no primeiro acesso."""
        email = normalizar_email(email)
        provisoria = seg.senha_temporaria()
        existente = self.repo.buscar_usuario_por_email(email)
        if existente:
            if existente.papel != "empresa" or existente.cliente_id != cliente_id:
                raise ErroAutenticacao("Esse e-mail já é usado por outra conta.")
            usuario = self.repo.atualizar_usuario(
                existente.id, senha_hash=seg.hash_senha(provisoria), trocar_senha=1,
                falhas_seguidas=0, bloqueado_ate=None, nome=(nome or existente.nome).strip(),
            )
            self.repo.apagar_sessoes_do_usuario(usuario.id)
            return usuario, provisoria
        usuario = self.repo.criar_usuario(
            email=email, nome=(nome or "").strip() or email, senha_hash=seg.hash_senha(provisoria),
            papel="empresa", cliente_id=cliente_id, trocar_senha=True, criado_em=_iso(self.agora()),
        )
        return usuario, provisoria

    # ------------------------------------------------------------ login

    def entrar(self, email: str, senha: str) -> ResultadoLogin:
        try:
            email = normalizar_email(email)
        except ErroAutenticacao:
            seg.verificar_senha(senha or "", seg.HASH_FALSO)
            raise ErroAutenticacao(MSG_LOGIN_INVALIDO) from None
        usuario = self.repo.buscar_usuario_por_email(email)
        agora = self.agora()

        if usuario is None:
            seg.verificar_senha(senha or "", seg.HASH_FALSO)  # mesmo tempo de resposta
            raise ErroAutenticacao(MSG_LOGIN_INVALIDO)

        if usuario.bloqueado_ate and _de_iso(usuario.bloqueado_ate) > agora:
            raise ErroAutenticacao(MSG_BLOQUEADO)

        if not seg.verificar_senha(senha or "", usuario.senha_hash):
            falhas = usuario.falhas_seguidas + 1
            bloqueio = _iso(agora + BLOQUEIO) if falhas >= MAX_FALHAS else None
            self.repo.atualizar_usuario(
                usuario.id, falhas_seguidas=0 if bloqueio else falhas, bloqueado_ate=bloqueio
            )
            raise ErroAutenticacao(MSG_BLOQUEADO if bloqueio else MSG_LOGIN_INVALIDO)

        self.repo.atualizar_usuario(usuario.id, falhas_seguidas=0, bloqueado_ate=None)
        if not usuario.ativo:
            raise ContaDesativada("Esta conta está desativada. Fale com quem administra o Emitta.")
        if not usuario.aprovado:
            raise ContaPendente(MSG_PENDENTE)

        if usuario.totp_ativo:
            desafio = seg.gerar_token()
            self.repo.criar_desafio(seg.hash_token(desafio), usuario.id, _iso(agora + DURACAO_DESAFIO))
            return ResultadoLogin(desafio_2fa=desafio, usuario=usuario)

        return ResultadoLogin(token_sessao=self._abrir_sessao(usuario.id), usuario=usuario)

    def confirmar_2fa(self, desafio: str, codigo: str) -> ResultadoLogin:
        h = seg.hash_token(desafio or "")
        registro = self.repo.buscar_desafio(h)
        agora = self.agora()
        if not registro or _de_iso(registro["expira_em"]) < agora:
            raise ErroAutenticacao("O tempo para digitar o código acabou. Entre de novo.")
        if registro["tentativas"] >= MAX_TENTATIVAS_DESAFIO:
            self.repo.apagar_desafio(h)
            raise ErroAutenticacao(MSG_BLOQUEADO)
        usuario = self.repo.buscar_usuario(registro["usuario_id"])
        passo = seg.conferir_totp(usuario.totp_segredo, codigo, usuario.totp_ultimo_passo, agora.timestamp())
        if passo is None:
            self.repo.contar_tentativa_desafio(h)
            raise ErroAutenticacao("Código incorreto. Confira no aplicativo autenticador.")
        self.repo.apagar_desafio(h)
        self.repo.atualizar_usuario(usuario.id, totp_ultimo_passo=passo)
        return ResultadoLogin(token_sessao=self._abrir_sessao(usuario.id), usuario=usuario)

    def _abrir_sessao(self, usuario_id: int) -> str:
        token = seg.gerar_token()
        agora = self.agora()
        self.repo.atualizar_usuario(usuario_id, ultimo_acesso=_iso(agora))
        self.repo.criar_sessao(seg.hash_token(token), usuario_id, _iso(agora), _iso(agora + DURACAO_SESSAO))
        return token

    def usuario_da_sessao(self, token: str | None) -> Usuario | None:
        if not token:
            return None
        h = seg.hash_token(token)
        sessao = self.repo.buscar_sessao(h)
        if not sessao:
            return None
        agora = self.agora()
        if _de_iso(sessao["expira_em"]) < agora or agora - _de_iso(sessao["ultimo_uso"]) > SESSAO_OCIOSA:
            self.repo.apagar_sessao(h)
            return None
        usuario = self.repo.buscar_usuario(sessao["usuario_id"])
        if not usuario or not usuario.ativo or not usuario.aprovado:
            self.repo.apagar_sessao(h)
            return None
        # A administração tem acesso a todas as contas: sessão bem mais curta.
        if usuario.papel == "admin" and agora - _de_iso(sessao["ultimo_uso"]) > SESSAO_OCIOSA_ADMIN:
            self.repo.apagar_sessao(h)
            return None
        self.repo.tocar_sessao(h, _iso(agora))
        return usuario

    def sair(self, token: str | None) -> None:
        if token:
            self.repo.apagar_sessao(seg.hash_token(token))

    # ------------------------------------------------------------ senha e 2FA

    def trocar_senha(self, usuario: Usuario, senha_atual: str, nova: str, token_atual: str | None) -> Usuario:
        if not seg.verificar_senha(senha_atual or "", usuario.senha_hash):
            raise ErroAutenticacao("A senha atual está incorreta.")
        problema = seg.problema_na_senha(nova, usuario.email)
        if problema:
            raise ErroAutenticacao(problema)
        if seg.verificar_senha(nova, usuario.senha_hash):
            raise ErroAutenticacao("A nova senha precisa ser diferente da atual.")
        atualizado = self.repo.atualizar_usuario(usuario.id, senha_hash=seg.hash_senha(nova), trocar_senha=0)
        # Encerra as outras sessões: se alguém tinha a senha antiga, perde o acesso.
        self.repo.apagar_sessoes_do_usuario(usuario.id, exceto=seg.hash_token(token_atual) if token_atual else None)
        return atualizado

    def iniciar_2fa(self, usuario: Usuario) -> tuple[str, str]:
        if usuario.totp_ativo:
            raise ErroAutenticacao("A verificação em duas etapas já está ativa.")
        segredo = seg.gerar_segredo_totp()
        self.repo.atualizar_usuario(usuario.id, totp_segredo=segredo, totp_ultimo_passo=None)
        return segredo, seg.uri_totp(segredo, usuario.email)

    def ativar_2fa(self, usuario: Usuario, codigo: str) -> Usuario:
        if usuario.totp_ativo:
            raise ErroAutenticacao("A verificação em duas etapas já está ativa.")
        if not usuario.totp_segredo:
            raise ErroAutenticacao("Comece a configuração de novo.")
        passo = seg.conferir_totp(usuario.totp_segredo, codigo, None, self.agora().timestamp())
        if passo is None:
            raise ErroAutenticacao("Código incorreto. Confira se o relógio do celular está certo e tente de novo.")
        return self.repo.atualizar_usuario(usuario.id, totp_ativo=1, totp_ultimo_passo=passo)

    def desativar_2fa(self, usuario: Usuario, senha: str) -> Usuario:
        if not seg.verificar_senha(senha or "", usuario.senha_hash):
            raise ErroAutenticacao("Senha incorreta.")
        return self.repo.atualizar_usuario(usuario.id, totp_ativo=0, totp_segredo=None, totp_ultimo_passo=None)

    # ------------------------------------------------------------ administração

    def _alvo(self, usuario_id: int) -> Usuario:
        usuario = self.repo.buscar_usuario(usuario_id)
        if not usuario:
            raise ErroAutenticacao("Conta não encontrada.")
        return usuario

    def redefinir_senha(self, usuario_id: int) -> tuple[Usuario, str]:
        """Gera senha provisória (troca obrigatória no próximo acesso) e
        desconecta a pessoa de todos os aparelhos."""
        alvo = self._alvo(usuario_id)
        provisoria = seg.senha_temporaria()
        atualizado = self.repo.atualizar_usuario(
            alvo.id, senha_hash=seg.hash_senha(provisoria), trocar_senha=1, falhas_seguidas=0, bloqueado_ate=None,
        )
        self.repo.apagar_sessoes_do_usuario(alvo.id)
        return atualizado, provisoria

    def desbloquear(self, usuario_id: int) -> Usuario:
        return self.repo.atualizar_usuario(self._alvo(usuario_id).id, falhas_seguidas=0, bloqueado_ate=None)

    def definir_ativo(self, usuario_id: int, ativo: bool, quem: Usuario) -> Usuario:
        alvo = self._alvo(usuario_id)
        if alvo.id == quem.id and not ativo:
            raise ErroAutenticacao("Você não pode desativar a própria conta.")
        atualizado = self.repo.atualizar_usuario(alvo.id, ativo=int(ativo))
        if not ativo:
            self.repo.apagar_sessoes_do_usuario(alvo.id)
        return atualizado

    def aprovar(self, usuario_id: int) -> Usuario:
        alvo = self._alvo(usuario_id)
        if alvo.aprovado:
            raise ErroAutenticacao("Esta conta já está aprovada.")
        return self.repo.atualizar_usuario(alvo.id, aprovado=1)

    def recusar(self, usuario_id: int) -> Usuario:
        """Apaga o pedido (o e-mail fica livre; o registro de atividades continua)."""
        alvo = self._alvo(usuario_id)
        if alvo.aprovado:
            raise ErroAutenticacao("Só dá para recusar contas que estão aguardando aprovação.")
        self.repo.apagar_usuario(alvo.id)
        return alvo

    def remover_2fa(self, usuario_id: int) -> Usuario:
        """Para quem perdeu o celular do autenticador. Não vale para administração."""
        alvo = self._alvo(usuario_id)
        if alvo.papel == "admin":
            raise AcessoNegado("Na administração, a verificação em duas etapas não pode ser removida.")
        atualizado = self.repo.atualizar_usuario(alvo.id, totp_ativo=0, totp_segredo=None, totp_ultimo_passo=None)
        self.repo.apagar_sessoes_do_usuario(alvo.id)
        return atualizado

    def encerrar_sessoes(self, usuario_id: int) -> None:
        self.repo.apagar_sessoes_do_usuario(self._alvo(usuario_id).id)
