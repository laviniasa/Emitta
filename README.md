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

1. Abra `/admin`, informe o código de instalação e crie a conta de administração
   (depois ative a verificação em duas etapas, obrigatória nessa área).
2. Em outra janela, abra `/entrar` → **Sou contador** → **Criar conta de contador**;
   depois aprove o pedido em `/admin` → Contas.
3. No painel, cadastre uma empresa (ex.: CNPJ `11.222.333/0001-81`, município IBGE `3550308`),
   libere um serviço e crie o acesso da empresa (anote a senha provisória).
4. Em outra janela anônima (ou no celular), **Sou empresa** → entre com o acesso, crie a senha,
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
secreto). Ele é pedido uma única vez, em `/admin`, para criar a conta de administração.

## Login e segurança

- **Três tipos de conta:**
  - **Administração** (dona da plataforma): criada uma única vez em `/admin` com o código de instalação.
  - **Contador:** pede a conta em `/entrar` → "Sou contador" → "Criar conta". A conta só
    funciona depois que a administração **aprovar** o pedido (em `/admin` → Contas).
  - **Empresa:** o acesso é criado pelo contador no painel. O sistema gera uma senha provisória
    (mostrada uma única vez) e a empresa cria a própria senha no primeiro acesso.
- **Separação por login:** cada contador vê só as empresas que ele cadastrou; a empresa vê só
  a si mesma. Pedidos para empresas de outra conta respondem "não encontrada" (404), sem
  confirmar que existem.
- **Administração (`/admin`):**
  - Verificação em duas etapas **obrigatória** (não abre sem ela e não pode ser desligada).
  - Sessão de no máximo 30 minutos sem uso.
  - Mostra contas e o registro de atividades (entradas, saídas, senhas erradas, bloqueios,
    cadastros, emissões e cancelamentos, com data, hora e IP).
  - Ajuda com contas: senha provisória, desbloquear, desconectar de todos os aparelhos,
    remover a verificação em duas etapas (celular perdido), desativar e reativar.
  - Toda ação da administração fica registrada.
  - **Não** mostra notas nem certificados das empresas.
- **Senhas:** mínimo de 10 caracteres, guardadas com scrypt (nunca em texto puro).
- **Bloqueio:** 5 senhas erradas seguidas bloqueiam a conta por 15 minutos; há também
  limite de tentativas por IP e de contas criadas por IP.
- **Verificação em duas etapas:** opcional para contador e empresa (menu "Segurança" do painel),
  com Google Authenticator, Microsoft Authenticator ou Authy.
- **Sessão:** cookie protegido (HttpOnly, Secure, SameSite=Strict), expira em 12 h ou
  após 2 h sem uso. Trocar a senha encerra as outras sessões.
- **Proteções extras:** cabeçalho anti-CSRF (`X-Emitta`), Content-Security-Policy, HSTS,
  bloqueio de iframes.

Para rodar no seu computador sem HTTPS, use `EMITTA_COOKIE_SEGURO=0` (só no modo simulação).

## Emissão real (governo)

O que já está pronto para o Emissor Nacional:

- **Conexão conferida com o manual oficial** (APIs do Sistema Nacional NFS-e v1.2):
  `POST /nfse`, `GET /dps/{id}`, `GET /nfse/{chave}`, `POST /nfse/{chave}/eventos`.
- **Leiaute 1.01** com as regras por regime (MEI, ME/EPP do Simples, fora do Simples):
  tributos aproximados, alíquota do ISS só quando exigida, MEI sem retenção.
- **Assinatura XMLDSig RSA-SHA1** (padrão das notas brasileiras), com canonicalização
  isolada do elemento para o hash bater com o calculado pelo governo.
- **Sem nota duplicada:** cada envio tem uma chave única; a nota é gravada como
  "processando" antes de ir ao governo e, se a resposta se perder, o Emitta consulta
  `GET /dps/{id}` antes de qualquer reenvio.
- **Certificado A1 por empresa**, enviado pelo painel e guardado **criptografado**
  (chave em `EMITTA_CHAVE_CERTIFICADOS`).
- **Competência** (data do serviço), **retenção de ISS** pelo tomador e **CNPJ alfanumérico**.
- **Download** da nota em PDF e XML.
- **Consulta de CNPJ** (dados públicos da Receita via BrasilAPI) para preencher nomes e cadastro.

Para ligar a homologação: enviar o certificado da empresa piloto pelo painel e mudar
`NFSE_AMBIENTE=homologacao`. Antes, ter banco permanente (os dados e certificados do
plano gratuito somem quando o servidor reinicia).

## Como o código está organizado

| Arquivo | O que faz |
|---|---|
| `app/regras.py` | Regras de negócio: trava de serviço, CNPJ/CPF, ISS, prazo e motivos de cancelamento |
| `app/repositorio.py` | Banco SQLite: empresas, serviços liberados, notas |
| `app/catalogo.py` + `app/dados/` | Lista de serviços (códigos de tributação nacional) |
| `app/dps.py` | Monta o XML da DPS e do pedido de cancelamento |
| `app/assinatura.py` | Assinatura digital XML com o certificado A1 |
| `app/certificados.py` | Certificado A1 de cada empresa, guardado criptografado |
| `app/pdf_nota.py` | PDF da nota |
| `app/consulta_cnpj.py` | Dados públicos de CNPJ (Receita) |
| `app/sefin.py` | Conversa com a API do governo (real e simulada) |
| `app/emissao.py` | Junta tudo: fluxos de emitir e cancelar |
| `app/autenticacao.py` + `app/seguranca.py` | Login, senhas, sessões, duas etapas, contas |
| `app/api.py` | Rotas web (painel do contador, app da empresa, administração) |

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
