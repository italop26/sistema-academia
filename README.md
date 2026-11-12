# Academia/Pilates

Sistema administrativo para academias e estúdios de Pilates, com cadastros, matrículas, mensalidades, presença e acompanhamento de ausência. Construído como monólito modular com **FastAPI, SQLAlchemy, SQLite, Alembic, Redis, Celery e React com Vite em JavaScript**.

Este README apresenta o projeto para o GitHub. O [README_VALIDACAO.md](README_VALIDACAO.md) explica o uso passo a passo, os comandos de terminal e os roteiros de validação por etapa.

## Funcionalidades

| Módulo | Comportamento |
| --- | --- |
| Autenticação | Login administrativo, JWT em memória, expiração, permissões e logout com revogação no Redis |
| Alunos e planos | Cadastros administrativos, desativação e histórico |
| Matrículas | Vigência, preço contratado, vencimento e cancelamento |
| Mensalidades | Geração por competência, baixa manual integral, cancelamento e histórico transacional |
| Pix simulado | Cobrança de teste, webhook autenticado, validação e proteção contra quitação duplicada |
| Lembretes financeiros | Identificação de vencidas, envio exclusivamente simulado, retries e acompanhamento |
| Frequência | Uma presença diária por aluno, histórico individual, última visita e suspensão/retomada com motivo |
| Ausência | Detecção de alunos elegíveis após 240 horas completas sem presença |
| Acompanhamento | Fila com pendente, em acompanhamento, resolvido e encerrado; responsável, observações e histórico |

Pix e mensagens externas não estão integrados a provedores reais. Não há portal do aluno, presença por aula ou emissão automática de novas mensalidades nesta versão.

## Regras de frequência e ausência

O check-in usa o horário do servidor e a data de **America/Fortaleza**. Exige aluno ativo e matrícula pertencente ao aluno, vigente, ativa e sem suspensão. Repetições no mesmo dia conservam uma única presença; chaves de idempotência ficam persistidas. Não há lançamento retroativo ou exclusão de presença pela API.

A suspensão afeta a disponibilidade para frequência, preservando as regras de cobrança existentes. Seu início, retomada, responsável e motivo ficam registrados.

A ausência considera **240 horas transcorridas**, a partir da última presença ou do início da elegibilidade, respeitando a carência inicial da ativação. Alunos sem check-in também são considerados. Se todas as matrículas ficarem indisponíveis, a contagem reinicia após a retomada; uma matrícula disponível mantém a elegibilidade.

Cada episódio gera no máximo um acompanhamento. Um novo check-in resolve o caso aberto na mesma transação da presença. Casos finalizados ficam no histórico e não são recriados durante o mesmo episódio. Perda de elegibilidade é reconciliada na próxima varredura.

## Arquitetura

```text
backend/
  app/
    core/                 # configuração, sessões, segurança, Redis e Celery
    models/               # Base e convenções SQLAlchemy
    modules/
      auth/ users/ health/
      students/ plans/ enrollments/
      billing/ payments/ webhooks/
      attendance/         # check-in, histórico e última visita
      absence/            # detecção e acompanhamento administrativo
      audit/              # eventos transacionais
  migrations/             # revisões Alembic
  tests/                  # regras, concorrência, migrações e integração
frontend/
  src/api/                # transporte autenticado e utilitários
  src/auth/               # sessão em memória
  src/components/         # login e painéis administrativos
  e2e/                    # testes Chromium com API real
docs/                     # contratos, relatórios e evidências
scripts/                  # preparação de ambiente e verificações
```

Routers validam HTTP e permissões; services coordenam regras e transações; repositories concentram consultas; models representam a persistência. Auditoria e alteração de negócio são confirmadas juntas. SQLite usa chaves estrangeiras e `BEGIN IMMEDIATE` nas escritas.

O banco usado neste projeto é **SQLite**. A compatibilidade anterior com PostgreSQL foi preservada, mas não é necessária para validar estas etapas. O Compose original ainda inicia seu serviço PostgreSQL auxiliar; a aplicação usa o banco definido por `DATABASE_URL`.

## Execução local com Docker

Requisitos: Docker Desktop com contêineres Linux, Docker Compose e Node.js compatível com o projeto. Na raiz:

```powershell
node scripts/setup-env.mjs --sqlite
docker compose -p sistemadeacademia up --build -d
docker compose -p sistemadeacademia ps -a
```

O script prepara o `.env`, gera segredos ausentes e preserva os existentes. O Compose aplica as migrações antes de iniciar a API. **Em uma instalação com dados, revise as migrações e faça backup antes de atualizar.** A autorização desta entrega não incluiu atualizar o banco principal com as novas etapas de frequência.

| Endereço | Finalidade |
| --- | --- |
| http://localhost:5174 | Interface administrativa |
| http://localhost:8002/docs | Contratos da API em desenvolvimento |
| http://localhost:8002/health | Prontidão de banco e Redis |
| http://localhost:8002/health/live | Processo da API |

Após as migrações, crie o administrador inicial em terminal interativo:

```powershell
docker compose -p sistemadeacademia run --rm --no-deps backend python -m app.modules.users.cli --name "Seu nome" --email "seu.email@exemplo.com"
```

A senha é solicitada duas vezes, sem exibição, com 12 a 128 caracteres. Não há credencial padrão nem cadastro público. A CLI recusa criar outro administrador inicial se já existir um.

## Configuração

Variáveis documentadas em [.env.example](.env.example):

| Variável | Uso |
| --- | --- |
| `DATABASE_URL` | Para SQLite local: `sqlite+pysqlite:///./data/academia.db` |
| `JWT_SECRET_KEY` | Assinatura de autenticação; segredo aleatório de pelo menos 32 caracteres |
| `REDIS_PASSWORD` | Autenticação da infraestrutura Redis |
| `VITE_API_URL` | `/api`; proxy do frontend para a API |
| `PIX_SIMULATOR_ENABLED` | Simulador de teste; desativado por padrão e bloqueado em produção |
| `FINANCIAL_AUTOMATION_ENABLED` | Lembretes financeiros simulados; desativado por padrão |
| `ABSENCE_TRACKING_ENABLED` | Detecção de ausência; desativada por padrão |
| `ABSENCE_BATCH_SIZE` | Alunos por lote; padrão 50, intervalo 1–200 |

Nunca versione `.env`, credenciais, backups ou bancos. O frontend recebe somente configuração pública; segredos não devem usar o prefixo `VITE_`.

## Tarefas e recuperação

O Beat identifica mensalidades vencidas a cada cinco minutos, publica lembretes a cada minuto e verifica ausência a cada cinco minutos. Cada funcionalidade respeita sua flag de ativação. Mantenha uma instância do scheduler.

Redis transporta tarefas; o SQLite guarda intenções, detecções, progresso, tentativas e histórico. A varredura de ausência usa cursor e reserva temporária, revalida cada aluno e confirma seu progresso junto da detecção. Falhas transitórias têm até três retries por execução, com esperas de 60/300/900 segundos. Execuções periódicas posteriores permitem nova recuperação; indisponibilidade pode atrasar a identificação.

A fila administrativa é persistida no banco. Os resultados temporários do Celery e o ping do Redis não comprovam conclusão de uma operação de negócio.

## Principais endpoints

Rotas `/admin/*` exigem usuário ativo com perfil administrador.

| Método | Caminho | Finalidade |
| --- | --- | --- |
| POST | `/auth/login` | Entrar |
| POST | `/auth/logout` | Revogar a sessão |
| GET/POST | `/admin/students`, `/admin/plans`, `/admin/enrollments` | Cadastros e contratos |
| POST | `/admin/attendance/check-ins` | Presença idempotente |
| GET | `/admin/attendance/students/{id}` | Última visita e total |
| GET | `/admin/attendance/students/{id}/check-ins` | Histórico paginado |
| POST | `/admin/enrollments/{id}/suspend` | Suspender frequência |
| POST | `/admin/enrollments/{id}/suspensions/{period_id}/resume` | Retomar um período específico |
| GET | `/admin/absence/detections` | Fila e histórico de casos, com filtro e paginação |
| POST | `/admin/absence/detections/{id}/status` | Alterar estado com observação e versão esperada |
| GET | `/admin/absence/status`, `/admin/absence/runs` | Estado e execuções da detecção |
| POST | `/admin/absence/scan` | Verificação administrativa, respeitando reserva e backoff |
| GET | `/admin/history` | Eventos de auditoria |

Os schemas completos ficam no OpenAPI da aplicação. O transporte usa respostas de erro padronizadas e impede cache das rotas administrativas.

## Desenvolvimento e testes

O [guia de validação](README_VALIDACAO.md) contém os comandos de ambiente virtual, instalação do Alembic, desenvolvimento sem contêineres e testes descartáveis das três etapas.

No frontend:

```powershell
Set-Location frontend
npm ci
npm test
npm run build
```

Os testes backend usam arquivos SQLite temporários; o ambiente de navegador possui rede e volume próprios, sem portas públicas e sem os volumes principais. As verificações incluem autenticação, integridade, transações, concorrência, idempotência, datas, migrações e fluxos administrativos reais.

Validação registrada em **12/11/2026**: **271 testes de backend** (269 de regressão e 2 de infraestrutura), **24 JavaScript** e **14 Chromium** passaram. Build, Ruff, formatação, ensaio de migrações e detecção pelo Beat/worker reais passaram. Consulte o [relatório de fechamento](docs/RELATORIO_FREQUENCIA_ETAPA_3.md) para evidências e limitações.

## Documentação e limites

- [Guia de uso e validação](README_VALIDACAO.md)
- [Autenticação](docs/AUTENTICACAO.md)
- [Matrículas e mensalidades](docs/MATRICULAS_MENSALIDADES.md)
- [Pix de teste](docs/PIX_SIMULADO.md)
- [Automações financeiras](docs/AUTOMACAO_FINANCEIRA.md)
- [Relatório de frequência — etapa 1](docs/RELATORIO_FREQUENCIA_ETAPA_1.md)
- [Relatório de ausência — etapa 2](docs/RELATORIO_FREQUENCIA_ETAPA_2.md)
- [Acompanhamento e fechamento — etapa 3](docs/RELATORIO_FREQUENCIA_ETAPA_3.md)

O Compose é destinado a desenvolvimento local e usa Vite para servir o frontend. Publicação na internet, TLS, backup recorrente, retenção e monitoramento de produção exigem preparação própria. SQLite aceita um escritor por vez; os testes locais não definem capacidade máxima. Histórico protegido pela API e por transações não é inviolável contra acesso SQL privilegiado.
