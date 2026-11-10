# Validação isolada da base

Use Docker Compose 2.24.4+ (suporte a `!override`) e contêineres Linux. A validação usa o projeto **academia-validation**, arquivos/volumes próprios e portas 15173 (frontend), 18000 (API), 15432 (PostgreSQL) e 16379 (Redis). Nunca execute este override com o nome do projeto real.

Na raiz:

```sh
node scripts/setup-validation.mjs
docker compose -p academia-validation --env-file .env.validation -f compose.yaml -f compose.validation.yaml build backend frontend tests seed e2e
docker compose -p academia-validation --env-file .env.validation -f compose.yaml -f compose.validation.yaml up -d --no-build backend frontend worker scheduler
docker compose -p academia-validation --env-file .env.validation -f compose.yaml -f compose.validation.yaml run --rm --no-deps seed
docker compose -p academia-validation --env-file .env.validation -f compose.yaml -f compose.validation.yaml run --rm --no-deps tests pytest -q
docker compose -p academia-validation --env-file .env.validation -f compose.yaml -f compose.validation.yaml run --rm --no-deps e2e
node scripts/check-validation-logs.mjs
```

O smoke HTTP adicional pode ser executado após o seed com `tests python tests/smoke_auth_http.py`, usando o mesmo prefixo Compose. Depois do build local do frontend, `node scripts/check-bundle.mjs` procura os segredos configurados nos arquivos gerados, sem imprimi-los.

O setup cria `.env.validation` com segredos aleatórios independentes; esse arquivo é ignorado pelo Git. As contas de navegador são sintéticas e ficam somente no SQLite `validation.db` do volume separado. A senha é aleatória e não é exibida. O seed exige `APP_ENV=test`, `VALIDATION_ONLY=1` e o nome de banco de validação.

Os testes de navegador usam Chromium e desabilitam trace, vídeo e captura automática de falhas para evitar gravar dados de autenticação. O runner `e2e/run.mjs` remove senhas de teste e JWTs antes de exibir a saída. Capturas explícitas da tela vazia de login ficam em `frontend/test-results/`.

Para testar também a migração e comunicação PostgreSQL, sem trocar o banco da API em execução:

```sh
docker compose -p academia-validation --env-file .env.validation -f compose.yaml -f compose.validation.yaml run --rm --no-deps -e DATABASE_URL= migrate
docker compose -p academia-validation --env-file .env.validation -f compose.yaml -f compose.validation.yaml run --rm --no-deps -e DATABASE_URL= tests alembic check
docker compose -p academia-validation --env-file .env.validation -f compose.yaml -f compose.validation.yaml run --rm --no-deps -e DATABASE_URL= tests pytest tests/test_integration.py -q
```

Para encerrar os serviços de validação, preservando seus volumes:

```sh
docker compose -p academia-validation --env-file .env.validation -f compose.yaml -f compose.validation.yaml down
```

O banco da aplicação e os seus usuários não são acessados por esses comandos. Não copie as contas de teste para o ambiente real. Para usar a aplicação, crie seu administrador pela CLI documentada no README e inicie o Compose normal.

O relatório de resultados fica em [RELATORIO_FINAL.md](RELATORIO_FINAL.md). Um build estático aprovado não comprova publicação: a configuração atual continua voltada a desenvolvimento local, com proxy Vite. Uma publicação futura precisa fornecer o encaminhamento de `/api` no servidor escolhido.
