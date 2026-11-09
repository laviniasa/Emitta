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

Abra **http://localhost:8000/docs** para testar todas as rotas pelo navegador.

### Testar o fluxo completo pelo /docs

1. `POST /contador/clientes`: cadastre uma empresa (ex.: CNPJ `11.222.333/0001-81`,
   município IBGE `3550308`, alíquota `3`, prazo de cancelamento `30`).
2. `PUT /contador/clientes/{id}/servicos`: libere `{"servicos": [{"codigo": "010101"}]}`.
3. `GET /app/{id}/servicos`: o app só recebe o serviço liberado.
4. `POST /app/{id}/notas`: emita (tomador `11.444.777/0001-61`, valor `1.500,00`).
   Tente um código não liberado e veja o bloqueio (erro 403).
5. `POST /app/{id}/notas/{nota_id}/cancelar`: cancele com `{"motivo": "erro"}`.

### Rodar os testes

```bash
pytest -v
```

Os testes também rodam sozinhos no GitHub a cada envio (aba **Actions**).

## Publicar no Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/laviniasa/emitta)

O arquivo `render.yaml` já tem tudo configurado (plano gratuito, modo simulação).
Cada envio para a branch `main` atualiza o site sozinho.

No plano gratuito, o servidor "dorme" depois de um tempo sem uso (o primeiro acesso
demora uns 30 segundos) e **os dados do banco somem quando ele reinicia**. Serve
para demonstração; para uso real será preciso um banco PostgreSQL.

O sistema **se recusa a iniciar** em homologação ou produção enquanto não houver
login, para ninguém emitir notas reais por um endereço aberto.

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

- [ ] Login do contador e do cliente (hoje as rotas estão abertas: **não colocar no ar assim**)
- [ ] Cadastro da empresa pelo CNPJ (buscar dados públicos automaticamente)
- [ ] Sugerir serviços pelo CNAE e pelo histórico de notas
- [ ] Gerar o PDF (DANFSe) e enviar por e-mail
- [ ] Aviso ao contador em cancelamentos e rejeições
- [ ] Painel web do contador e app do cliente (telas já desenhadas)
- [ ] Trocar SQLite por PostgreSQL quando houver vários usuários ao mesmo tempo
