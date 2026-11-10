# Emitta

Emissor de NFS-e no **padrão nacional** (Emissor Nacional), pensado para
escritórios de contabilidade:

- o **contador** cadastra a empresa e **libera só os serviços** que ela pode emitir;
- o **cliente** emite e cancela pelo app, vendo apenas os serviços liberados;
- o **servidor** confere tudo (trava de serviço, CNPJ/CPF, prazo de cancelamento),
  monta o XML, assina com o certificado A1 e conversa com a API do governo.

> Estado atual: **versão inicial**. Funciona de ponta a ponta no modo
> **simulação** (sem internet nem certificado). Para homologação, veja
> "Antes do primeiro teste real".

## Como rodar

Precisa de Python 3.11 ou mais novo.

```bash
python -m venv .venv
source .venv/bin/activate        # no Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env

uvicorn app.api:app --reload --env-file .env
```

Abra **http://localhost:8000** e entre por `/entrar`. A documentação técnica da API
fica em `/docs` (as rotas exigem login).

### Testar o fluxo completo

1. Abra `/entrar`, informe o código de instalação e crie a conta do contador.
2. No painel, cadastre uma empresa (ex.: CNPJ `11.222.333/0001-81`, município IBGE `3550308`).
3. Libere um serviço e crie o acesso da empresa (anote a senha provisória).
4. Em outra janela anônima (ou no celular), entre com o acesso da empresa, crie a senha,
   emita uma nota (tomador `11.444.777/0001-61`) e cancele.

### Rodar os testes

```bash
pytest -v
```

Os testes também rodam sozinhos no GitHub a cada envio (aba **Actions**).

## Publicar no Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/laviniasa/Emitta)

O arquivo `render.yaml` já tem tudo configurado (plano gratuito, modo simulação).
Cada envio para a branch `main` atualiza o site sozinho.

No plano gratuito, o servidor "dorme" depois de um tempo sem uso (o primeiro acesso
demora uns 30 segundos) e **os dados do banco somem quando ele reinicia**. Serve
para demonstração; para uso real será preciso um banco PostgreSQL.

Defina no Render a variável `EMITTA_CODIGO_INSTALACAO` (um código longo e
secreto). Ele é pedido uma única vez, para criar a primeira conta de contador.

## Login e segurança

- **Primeiro acesso:** abra `/entrar`, informe o código de instalação e crie a conta do contador.
- **Acesso das empresas:** no painel, em "Acesso da empresa ao app", o contador cria o login.
  O sistema gera uma senha provisória (mostrada uma única vez) e a empresa cria a própria
  senha no primeiro acesso.
- **Senhas:** mínimo de 10 caracteres, guardadas com scrypt (nunca em texto puro).
- **Bloqueio:** 5 senhas erradas seguidas bloqueiam a conta por 15 minutos; há também
  limite de tentativas por IP.
- **Verificação em duas etapas:** opcional, no menu "Segurança" do painel, com
  Google Authenticator, Microsoft Authenticator ou Authy.
- **Sessão:** cookie protegido (HttpOnly, Secure, SameSite=Strict), expira em 12 h ou
  após 2 h sem uso. Trocar a senha encerra as outras sessões.
- **Isolamento:** a empresa só acessa os próprios dados; o painel é só do contador.
- **Proteções extras:** cabeçalho anti-CSRF (`X-Emitta`), Content-Security-Policy, HSTS,
  bloqueio de iframes.

Para rodar no seu computador sem HTTPS, use `EMITTA_COOKIE_SEGURO=0` (só no modo simulação).

## Como o código está organizado

| Arquivo | O que faz |
|---|---|
| `app/regras.py` | Regras de negócio: trava de serviço, CNPJ/CPF, ISS, prazo e motivos de cancelamento |
| `app/repositorio.py` | Banco SQLite: empresas, serviços liberados, notas |
| `app/catalogo.py` + `app/dados/` | Lista de serviços (códigos de tributação nacional) |
| `app/dps.py` | Monta o XML da DPS e do pedido de cancelamento |
| `app/assinatura.py` | Assinatura digital XML com o certificado A1 |
| `app/certificados.py` | Encontra o certificado de cada empresa |
| `app/sefin.py` | Conversa com a API do governo (real e simulada) |
| `app/emissao.py` | Junta tudo: fluxos de emitir e cancelar |
| `app/api.py` | Rotas web (painel do contador e app do cliente) |

## Antes do primeiro teste real (homologação)

O modo simulação não fala com o governo. Para o ambiente de **produção restrita**:

1. **Certificado A1**: coloque `certificados/<CNPJ>.pfx` e defina `CERT_SENHA_<CNPJ>` no `.env`.
2. **Tabela de serviços oficial**: troque `app/dados/servicos_exemplo.json` pela
   tabela de Códigos de Tributação Nacional publicada em gov.br/nfse.
3. **XSDs oficiais**: baixe os esquemas em gov.br/nfse (Documentação técnica), coloque
   numa pasta e defina `NFSE_PASTA_XSD`. O sistema passa a validar o XML antes de enviar.
   Ajuste `app/dps.py` até a validação passar (principalmente os campos de tributação
   do Simples Nacional).
4. **Conferir no Swagger oficial**: URLs em `app/config.py`, rotas e nomes dos campos
   JSON em `app/sefin.py`, códigos de motivo de cancelamento em `app/regras.py` e o
   algoritmo de assinatura em `app/assinatura.py`.
5. Mude `NFSE_AMBIENTE=homologacao` e emita a primeira nota de teste.

Nunca use `producao` antes de tudo funcionar em homologação.

## Próximos passos

- [x] Login do contador e da empresa, com verificação em duas etapas
- [ ] Cadastro da empresa pelo CNPJ (buscar dados públicos automaticamente)
- [ ] Sugerir serviços pelo CNAE e pelo histórico de notas
- [ ] Gerar o PDF (DANFSe) e enviar por e-mail
- [ ] Aviso ao contador em cancelamentos e rejeições
- [ ] Painel web do contador e app do cliente (telas já desenhadas)
- [ ] Trocar SQLite por PostgreSQL quando houver vários usuários ao mesmo tempo
