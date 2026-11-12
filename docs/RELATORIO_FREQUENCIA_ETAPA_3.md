# Frequência e acompanhamento — fechamento das três etapas

Data: **12/11/2026**, America/Fortaleza. Etapas 1 e 2 autorizadas inicialmente; etapa 3 autorizada depois, com orientação para manter o acompanhamento simples. Documentação pública e guia pessoal solicitados em seguida.

## Resultado entregue

1. **Check-in:** presença diária por aluno, histórico paginado, última visita, matrícula válida, proteção contra duplicidade e suspensão/retomada com motivo.
2. **Ausência:** tarefa Celery após 240 horas completas de ausência elegível, carência inicial, consideração de alunos sem presença, suspensão de todas as matrículas e detecção única por episódio.
3. **Acompanhamento:** lista administrativa com filtro/paginação, pendente, em acompanhamento, resolvido e encerrado, responsável ao assumir o caso, observações e histórico.

Um novo check-in resolve o caso aberto na mesma transação. Falha no histórico reverte tanto a presença quanto a resolução. Comandos administrativos repetidos não duplicam a mesma alteração; versão esperada impede sobrescrita por uma tela desatualizada. Casos finalizados não reabrem durante o mesmo episódio. Perda de elegibilidade é reconciliada pela varredura periódica.

Não foi criado outro broker, SDK, serviço externo ou arquitetura genérica de filas. A fila administrativa usa os registros de ausência no SQLite.

## Arquivos desta entrega

| Área | Criações/alterações |
| --- | --- |
| Check-in | Novo `backend/app/modules/attendance/` com models, schemas, repositories, services e routers |
| Matrículas | Períodos de suspensão, instante interno de cancelamento e endpoints em `modules/enrollments/` |
| Ausência e acompanhamento | Novo `backend/app/modules/absence/`, incluindo `tasks.py`, `followups.py`, schemas e routers |
| Integração | `core/config.py`, `core/celery_app.py`, `main.py`, `audit/routers.py`, `migrations/env.py`, `.env.example` |
| Migrações novas | `20261112_01_attendance.py`, `20261112_02_absence.py`, `20261112_03_followups.py` |
| Interface | `AttendancePanel.jsx`, `FollowupsPanel.jsx`, integração no Dashboard, mensagens HTTP e geração de UUID com `getRandomValues` |
| Testes | `test_attendance.py`, `test_absence.py`, `test_followups.py`, `absence_runtime_check.py`, atualização da agenda de teste e de `test_config.py` |
| Navegador | `attendance.spec.js`, `followups.spec.js`; seletor de `Pendente` do teste financeiro limitado ao painel financeiro |
| Ambiente descartável | `compose.business-tests.yaml`, com ausência habilitada somente para os testes |
| Documentação | `README.md`, `README_VALIDACAO.md`, relatórios das três etapas e evidência operacional |
| Ensaio existente | `scripts/sqlite-stage.py` passa a reconhecer o head Alembic atual, sem depender da revisão antiga fixa |

Alterações anteriores da pasta foram preservadas. As revisões Alembic anteriores não foram reescritas.

## Testes executados

| Verificação | Resultado observado |
| --- | --- |
| Etapa 1, frequência e regressão financeira | **59 passaram** |
| Etapa 2, ausência e configuração | **27 passaram** |
| Conjunto das três suítes novas | **48 passaram**, já incluídos na regressão |
| Regressão final `pytest -m "not integration"` | **269 passaram**, 2 de infraestrutura separados |
| Infraestrutura real com SQLite/Redis/worker descartáveis | **2 passaram** |
| Total distinto de backend | **271 passaram** |
| JavaScript | **24 passaram** |
| Build Vite | **Passou**, 40 módulos |
| Chromium com API/SQLite/Redis/worker reais | **14 passaram**, nenhum pulado na execução final |
| Ruff e formatação | **Passaram**, 127 arquivos Python verificados na rodada global |
| Verificador dos segredos configurados no bundle | **Passou** |
| Migrações e equivalência schema/metadata | **Passaram** em bancos temporários |
| Upgrade em cópia temporária do backup anterior | **Passou** até `20261112_03`, integridade e FKs válidas |
| Beat → worker → detecções de ausência | **Passou**, três casos criados pelo agendamento real |
| Tela móvel com nome de 100 caracteres | **Passou**; captura de acompanhamento inspecionada visualmente |
| `git diff --check` | **Passou** nos arquivos rastreados |

Os totais por etapa se sobrepõem e não devem ser somados. Evidência operacional: [2026-11-12-frequencia-runtime.json](EVIDENCIAS/2026-11-12-frequencia-runtime.json). Captura local ignorada pelo Git: `frontend/test-results/followups-mobile.png`.

O probe usa uma agenda acelerada de um segundo e datas ajustadas exclusivamente no SQLite descartável. Após preparar as condições, aguarda o Beat e o worker criarem as detecções sem disparar uma varredura manual de confirmação. A configuração normal de cinco minutos e o limite de 240 horas foram preservados.

Os testes cobrem limites de tempo, idempotência, concorrência, reservas expiradas, retry limitado, rollback de auditoria, permissões, restrições de banco e preservação de histórico ao migrar detecções anteriores ao acompanhamento. Não houve injeção de SIGKILL específica para ausência nesta rodada; a recuperação de sua reserva foi exercitada em teste controlado, além do fluxo operacional bem-sucedido com processos reais.

## Problemas encontrados na validação

- **Compatibilidade do navegador:** `crypto.randomUUID` não estava disponível no HTTP interno de teste. Substituído por UUID v4 com `crypto.getRandomValues`; fluxo completo passou.
- **Teste financeiro com seletor ambíguo:** a nova fila também apresenta `Pendente`. O teste passou a procurar esse texto na região de matrículas/mensalidades, mantendo a verificação original do aluno correto. A execução final passou integralmente.
- **Data máxima:** a detecção trata `9999-12-31` sem somar um dia além do limite de `datetime`; caso específico passou.
- **Aviso preexistente:** Starlette/TestClient ainda emite depreciação referente a `httpx`; sem falha de testes e sem alteração de dependências.

## Documentação solicitada

- [README.md](../README.md): apresentação pública, funcionamento, arquitetura, configuração, endpoints e limites.
- [README_VALIDACAO.md](../README_VALIDACAO.md): ambiente virtual, Alembic, diferença entre bancos local/Docker/teste, comandos reproduzíveis, roteiros e resultados esperados.

O guia pessoal registra cada parte entregue e deve ser atualizado nas próximas rodadas de desenvolvimento.

## Pendências e limites operacionais

- **Banco principal preservado:** nenhuma nova migração aplicada nele; nenhuma atualização de suas imagens/serviços. Os fontes novos não aparecerão automaticamente na instalação principal anterior.
- **Automação principal:** `.env` principal preservado; ausência continua desativada por padrão. A ativação depende de implantação autorizada das migrações e dos processos correspondentes.
- **Implantação futura:** exige autorização específica, backup atualizado, migração e atualização de imagens. O ensaio usou cópia de um backup anterior já existente e não substitui backup atual.
- **Validação manual:** o guia permite conferir os fluxos com dados descartáveis. Capacidade máxima, teste de carga amplo e outros navegadores não foram certificados.
- **Operação:** SQLite aceita um escritor por vez. Indisponibilidade de Redis/Beat/worker pode atrasar a detecção; falha persistente no mesmo aluno precisa de análise. O progresso e os casos permanecem no banco.
- **Escopo simples:** sem mensagens reais, presença por aula, agendamento futuro de suspensão ou reabertura de casos finalizados no mesmo episódio.
- **Encerramento:** serviços de `academia-attendance-tests` parados com `stop`, volumes preservados. Sem remoção dos dados anteriores.

Nenhuma dependência instalada, commit, push ou deploy nesta rodada.
