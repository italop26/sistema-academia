# Gestão de academias e estúdios de Pilates

Monólito modular com FastAPI, React em **JavaScript** com Vite, SQLite ou PostgreSQL, SQLAlchemy, Alembic, Redis e Celery. Inclui o módulo inicial de usuários e autenticação; demais módulos de negócio ainda não foram implementados.

## Executar com Docker

Requisitos: Docker Desktop com contêineres Linux e Docker Compose; Node.js 22.12+ ou 24 para gerar o ambiente. Execute na raiz:

```sh
node scripts/setup-env.mjs --sqlite
docker compose up --build -d
docker compose ps -a
```

O script gera os segredos ausentes e preserva as senhas existentes. `--sqlite` seleciona `DATABASE_URL=sqlite+pysqlite:///./data/academia.db` e cria `backend/data/` para uso local. No Docker, o arquivo fica no volume `sqlite_data`, compartilhado entre API e migrações. Para continuar com PostgreSQL, remova `DATABASE_URL` do `.env`; a configuração anterior foi preservada. Não compartilhe nem versione `.env`. Configure `JWT_SECRET_KEY` com pelo menos 32 caracteres aleatórios; o script gera 64 caracteres hexadecimais.

| Endereço | Uso |
| --- | --- |
| http://localhost:5174 | Frontend |
| http://localhost:8002/docs | Documentação interativa da API em desenvolvimento |
| http://localhost:8002/health | Prontidão: verifica o banco selecionado e Redis |
| http://localhost:8002/health/live | Processo da API ativo, sem depender de outros serviços |

As portas 5174 e 8002 separam a academia de outros projetos locais que usam 5173 e 8000. A publicação das portas fica em `compose.yaml`; no desenvolvimento sem Docker, o frontend usa `frontend/vite.config.js`. O Docker mantém a porta interna 8000 da API.

`/health` retorna HTTP 200 quando as duas dependências respondem e HTTP 503 quando alguma está indisponível:

```json
{"status":"ok","database":"ok","redis":"ok"}
```

O Compose aguarda PostgreSQL e Redis, executa `alembic upgrade head` em um serviço temporário e inicia a aplicação. `migrate` terminar com código zero é esperado. Worker e scheduler usam a mesma imagem do backend. Portas ficam vinculadas somente a `127.0.0.1`; dados persistem em volumes Docker.

A infraestrutura PostgreSQL foi mantida no Compose, inclusive suas dependências de inicialização. Com `DATABASE_URL` apontando para SQLite, a aplicação usa SQLite. Não há dois bancos de usuários. Dados de um banco não são transferidos automaticamente ao trocar a configuração.

## Usuários e autenticação

Depois das migrações, crie o administrador inicial em um terminal interativo:

```sh
docker compose run --rm --no-deps backend python -m app.modules.users.cli --name "Seu nome" --email "seu.email@exemplo.com"
```

A senha é solicitada duas vezes sem exibição e deve ter de 12 a 128 caracteres. Não há senha padrão, opção de senha na linha de comando ou cadastro público. O comando recusa um segundo administrador inicial, mesmo se o primeiro estiver inativo.

| Método | Endpoint | Acesso |
| --- | --- | --- |
| POST | `/auth/login` | E-mail e senha em JSON; retorna JWT Bearer e validade em segundos |
| GET | `/auth/me` | Header `Authorization: Bearer <token>`; retorna dados públicos do usuário ativo |
| GET | `/auth/admin` | Exige usuário ativo com perfil administrador |
| POST | `/auth/logout` | Revoga o JWT autenticado; retorna 204 |

O corpo do login usa `email` e `password`. JWT expira em 15 minutos por padrão; a senha é armazenada como hash Argon2id. E-mail desconhecido, senha incorreta e usuário inativo recebem o mesmo erro 401. O React apresenta login e painel administrativo, com carregamento, erros, expiração e saída. Não há refresh token ou gerenciamento público de usuários.

O frontend usa `VITE_API_URL=/api`. No desenvolvimento, o proxy Vite encaminha `/api` para `API_PROXY_TARGET` (no Docker, `http://backend:8000`; fora dele, `http://localhost:8002`). O navegador usa a mesma origem do frontend; nenhum hostname interno ou segredo precisa ser exposto no bundle.

O token fica somente em memória e é perdido ao recarregar a página. `GET /auth/admin` exige administrador no servidor. `POST /auth/logout` retorna 204 e revoga o identificador do JWT no Redis até sua expiração. Se a revogação falhar, a interface limpa a sessão local e informa que a saída remota não pôde ser confirmada. Redis indisponível bloqueia consultas autenticadas com 503.

Para repetir a validação completa em dados isolados, consulte [docs/VALIDACAO.md](docs/VALIDACAO.md).

Veja [docs/AUTENTICACAO.md](docs/AUTENTICACAO.md) para contratos, permissões, configuração e testes.

```sh
docker compose logs --tail=100 backend worker scheduler
docker compose stop
docker compose start
docker compose down
```

`down` preserva os volumes. Ao alterar senhas depois de inicializar PostgreSQL, atualize também as credenciais no banco: editar o `.env` não altera uma conta já persistida. Não remova volumes com dados que queira manter.

## Organização e expansão

```text
backend/
  app/
    main.py                 # composição da aplicação
    core/                   # ambiente, banco, Redis, Celery, logs e erros
    models/                 # Base SQLAlchemy
    modules/
      health/
        routers.py          # HTTP e dependências
        services.py         # coordenação da verificação
        repositories.py     # acesso ao banco
        schemas.py          # contratos de entrada e saída
      users/                # model, repository, service, schemas e CLI de bootstrap
      auth/                 # router, service, schemas e dependências de autenticação
  migrations/               # Alembic, incluindo a criação de users
  tests/                    # testes isolados e de integração
frontend/
  src/
    api/                    # cliente HTTP e testes
    App.jsx                 # tela inicial de conectividade
scripts/setup-env.mjs
compose.yaml
```

Para um futuro módulo, crie `app/modules/<nome>/` com `routers.py`, `services.py`, `repositories.py`, `models.py` e `schemas.py`. Routers validam HTTP e chamam services; services coordenam regras; repositories recebem a sessão SQLAlchemy e acessam os dados. Models representam persistência e schemas representam contratos. Importe os models em `migrations/env.py` para que Alembic conheça o metadata e registre o router em `main.py`. A autenticação reutiliza `UserRepository` do módulo de usuários; não duplica o acesso a esses dados.

Use transações explícitas no service (`with session.begin()`) quando implementar escritas. O backend não cria tabelas automaticamente e não executa migrações a cada requisição. Não há abstrações de CRUD ou entidades de exemplo.

### Migrações

A revisão `20261109_01` cria `users` com e-mail único e restrição de perfil. Para aplicar a revisão atual sem iniciar os outros serviços:

```sh
docker compose run --rm --no-deps migrate
```

Para futuras alterações de models:

```sh
docker compose run --rm --no-deps --volume ./backend/migrations:/app/migrations backend alembic revision --autogenerate -m "criar tabelas do modulo"
docker compose run --rm --no-deps migrate
docker compose run --rm --no-deps backend alembic current
```

Revise a migração gerada antes de aplicá-la. O volume no primeiro comando salva a revisão na pasta local. Se estiver usando PostgreSQL, ele deve estar em execução. Nunca execute downgrade em dados importantes sem revisar o que será removido.

### Automações

`app/core/celery_app.py` prepara o broker Redis no banco lógico 0 e resultados no banco lógico 1. Serialização é JSON, fuso UTC e resultados expiram em uma hora. O Beat não possui tarefas da aplicação agendadas. Mantenha uma única instância do scheduler para evitar disparos duplicados.

Ao criar automações, adicione um `tasks.py` ao módulo e registre seu import em `celery_app.conf.imports`; então configure `beat_schedule`. Tarefas futuras devem ser idempotentes e ter políticas de timeout e retry adequadas à operação. O armazenamento local do Beat em `/tmp` é suficiente para esta estrutura sem agendas de negócio.

## Desenvolvimento sem contêineres para a aplicação

Python 3.12+ e Node.js 22.12+ ou 24. Para SQLite local, mantenha Redis no Docker:

```sh
node scripts/setup-env.mjs --sqlite
docker compose up -d redis
```

Backend, a partir de `backend/`:

```sh
python -m venv .venv
# PowerShell: .venv\Scripts\Activate.ps1
# Linux/macOS: source .venv/bin/activate
python -m pip install -e ".[dev]"
alembic upgrade head
python -m app.modules.users.cli --name "Seu nome" --email "seu.email@exemplo.com"
uvicorn app.main:app --reload --port 8002
```

Frontend, em outro terminal a partir de `frontend/`:

```sh
npm ci
npm run dev
```

No Windows com restrição de scripts PowerShell, use `npm.cmd` no lugar de `npm`. Para o backend sem ativação do virtualenv, use diretamente `.venv\Scripts\python.exe`. Execute worker e Beat pelo Docker, inclusive no Windows:

```sh
docker compose up -d worker scheduler
```

Variáveis são lidas do `.env` da raiz quando os comandos Python são executados em `backend/`, e do ambiente do processo nos contêineres. O Compose troca os hosts por `postgres` e `redis`. O frontend recebe somente a URL pública `VITE_API_URL`; nunca coloque segredos em variáveis `VITE_*`.

## Testes e verificações

Testes isolados do backend e análise estática, sem exigir Python no host:

```sh
docker compose build tests
docker compose run --rm --no-deps tests pytest -m "not integration" -q
docker compose run --rm --no-deps tests ruff check app migrations tests
docker compose run --rm --no-deps tests ruff format --check app migrations tests
docker compose run --rm --no-deps tests pip check
```

Integração com o banco configurado, Redis e worker reais:

```sh
docker compose up --build -d
docker compose run --rm tests
```

A integração verifica o banco configurado e executa uma tarefa nativa de manutenção do Celery, confirmando o resultado no Redis. Se executar `pytest` localmente sem `RUN_INTEGRATION_TESTS=1`, esses dois testes de infraestrutura são pulados. Os testes de autenticação já executam migrações e operações reais em arquivos SQLite temporários e independentes do banco da aplicação.

Frontend, a partir de `frontend/`:

```sh
npm ci
npm test
npm run build
npm audit
```

Na raiz, `docker compose config --quiet` valida a composição sem imprimir segredos. Evite compartilhar a saída de `docker compose config` sem `--quiet`, pois ela pode conter valores do ambiente.

## Configuração e limites atuais

- CORS aceita somente as origens explícitas de `CORS_ORIGINS` (array JSON). Métodos atuais: GET, POST e OPTIONS; headers incluem Content-Type e Authorization. Cookies entre origens estão desabilitados.
- Logs JSON incluem identificador de requisição, método, caminho, status e duração. Não registram corpos, query strings ou credenciais. `X-Request-ID` permite localizar a requisição. Erros inesperados retornam mensagem genérica e registram a classe da exceção.
- Erros HTTP e de validação usam `{"error":{"code":"...","message":"...","request_id":"..."}}`; falhas de prontidão usam o contrato próprio de `/health`.
- A autenticação exige usuário ativo e token não revogado. A dependência `require_admin` protege a rota administrativa utilizada pelo React. O painel mostra a conta e a conectividade; o ping do Redis não comprova atividade do worker ou do scheduler.
- O Compose é para desenvolvimento local; frontend usa o servidor Vite. Antes de publicar, configure build estático e servidor de arquivos, TLS, segredos do ambiente de destino, backup, observabilidade e acesso à infraestrutura. `APP_ENV=production` desabilita a documentação interativa.
- Dependências JavaScript têm lockfile; dependências Python têm faixas limitadas no `pyproject.toml`. Um lock de deploy e uma pipeline de CI podem ser adicionados conforme o ambiente de entrega for definido.

O relatório da criação e validação fica em [RELATORIO.md](RELATORIO.md).
