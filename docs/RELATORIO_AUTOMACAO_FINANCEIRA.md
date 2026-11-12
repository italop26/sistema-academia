# Relatório completo — automação financeira

Data: **10/11/2026**, referência America/Fortaleza. Escopo autorizado: três etapas, com migrações e falhas de infraestrutura restritas ao ambiente descartável. Nenhuma mensagem real enviada.

## Resultado entregue

1. **Identificação de vencidas:** tarefa periódica identifica mensalidades pendentes com vencimento anterior ao dia local, em lotes limitados, revalida a elegibilidade e cria uma intenção única por mensalidade/regra.
2. **Lembretes simulados:** outbox específica persistida no banco, reserva por token, publicação no Redis após commit, histórico de tentativas, recibo local único, revalidação antes do envio e retry controlado.
3. **Painel e validação:** acompanhamento administrativo, filtros/paginação, consulta de histórico, reabertura com motivo, testes financeiros e testes reais de Beat/worker/Redis, inclusive interrupção do worker durante a transação.

FastAPI, SQLAlchemy, SQLite, Alembic, Celery, Redis, worker e scheduler existentes foram preservados. Não foi criado outro broker, instalada dependência ou configurado serviço externo de mensagens.

## Comportamento e política

- A agenda normal executa identificação a cada **300 segundos** e publicação a cada **60 segundos**. O teste de agenda vazia foi substituído por verificação dos nomes, intervalos, registro e parâmetros das tarefas.
- `FINANCIAL_AUTOMATION_ENABLED=false` por padrão. O `.env` atual não foi alterado.
- Regra `overdue-v1`: **um lembrete por mensalidade**, sem repetição diária.
- O estado `vencida` continua calculado; não foi adicionado estado financeiro incompatível ao banco.
- Entrega usa três tentativas por ciclo, com espera de 60 e 300 segundos. Depois, fica esgotada. Até três ciclos administrativos adicionais são permitidos com motivo; total de até 12 tentativas, sem apagar o histórico.
- Falhas de publicação no Redis são separadas de falhas de envio e não consomem tentativas de envio. A publicação pode ser tentada novamente após 60 segundos.
- Pagamento, cancelamento ou ausência de atraso dispensam o lembrete antes de chamar o remetente. Há revalidação também antes da reabertura administrativa.
- `sent` significa somente **simulação registrada**, com recibo `TEST-REMINDER-<id>`. Não representa e-mail, WhatsApp, SMS ou outra mensagem efetivamente enviada.

## Outbox, concorrência e recuperação

Foi adotada uma outbox restrita ao domínio: `reminders` guarda intenção e pendência de transporte, e `reminder_attempts` guarda tentativas. Não foi criado barramento genérico ou infraestrutura adicional.

A intenção e seu histórico são confirmados antes de publicar. O dispatcher reserva com token e prazo; a publicação usa somente IDs/tokens. Reservas vencidas podem ser retomadas. Token antigo, intenção concluída ou reentrega de tarefa não geram outro recibo.

Antes da simulação, o serviço bloqueia mensalidade e lembrete, nessa ordem, e verifica novamente pagamento, cancelamento e vencimento. SQLite usa `BEGIN IMMEDIATE`. As regras de pagamento existentes são reutilizadas; não há alteração automática do valor ou nova quitação nessa tarefa.

Recibo, tentativa, estado e histórico são gravados na mesma transação. Queda do worker antes do commit reverte os efeitos e deixa a intenção anterior recuperável. As tarefas de entrega usam confirmação tardia, rejeição em perda do worker e prefetch 1. A reserva padrão de 120 segundos é maior que o limite rígido de 20 segundos da tarefa.

O banco é a fonte de verdade. O painel não interpreta resultado Celery expirado ou ping do Redis como prova de envio. Se o Redis estiver indisponível, a autenticação existente pode responder 503; essa proteção foi preservada, sem criar acesso administrativo alternativo.

## Arquivos envolvidos

| Área | Arquivos |
| --- | --- |
| Módulo novo | `backend/app/modules/notifications/{models,schemas,repositories,services,sender,tasks,routers}.py` e `__init__.py` |
| Configuração/agenda | `backend/app/core/config.py`, `backend/app/core/celery_app.py`, `.env.example` |
| Registro e histórico | `backend/app/main.py`, `backend/app/modules/audit/routers.py`, `backend/migrations/env.py` |
| Migração | Nova `backend/migrations/versions/20261110_05_reminders.py`; revisões anteriores preservadas |
| Testes | Novo `backend/tests/test_notifications.py`; atualização de `test_config.py`; execução do `test_integration.py` existente |
| Probes operacionais isolados | `backend/tests/notification_test_worker.py`, `notification_test_scheduler.py`, `notification_runtime_check.py` |
| Ambiente de teste | `compose.business-tests.yaml`, com worker, scheduler e verificador usando as imagens locais já disponíveis |
| Painel | Novo `frontend/src/components/NotificationsPanel.jsx`; integração em `Dashboard.jsx`, mensagens em `src/api/http.js` e estilos em `src/styles.css` |
| Navegador | Novo `frontend/e2e/notifications.spec.js` |
| Documentação | README, guia de matrículas, `AUTOMACAO_FINANCEIRA.md`, este relatório, registro diário e evidência JSON |

A nova migração cria apenas tabelas/índices/restrições de lembretes e tentativas. O downgrade recusa descartar lembretes existentes. Nenhuma migração foi aplicada ao banco principal da academia.

## Testes executados e evidências

| Verificação | Resultado observado |
| --- | --- |
| Compatibilidade inicial de configuração e financeiro | **51 passaram** |
| Primeira suíte de lembretes interrompida no bug NF-001 | **16 passaram e 1 falhou**; causa corrigida e teste preservado |
| Repetição inicial após correção | **21 passaram** |
| Regressão final `pytest -m "not integration" -q --tb=short -p no:cacheprovider` | **219 passaram**, incluindo os **25 casos finais de lembretes**; 2 testes de infraestrutura excluídos nessa execução |
| Infraestrutura real `RUN_INTEGRATION_TESTS=1 pytest tests/test_integration.py ...` | **2 passaram**, em SQLite/Redis/worker reais do ambiente descartável |
| Total de casos distintos de backend nas duas execuções finais | **221 passaram** |
| Frontend, `npm test` | **24 passaram** |
| Frontend, `npm run build` | **Passou**, 38 módulos; JS ~251,64 kB (~77,90 kB gzip) |
| Playwright | **11 passaram**, sem testes pulados no ambiente utilizado |
| Ruff `check` e `format --check` | **Passaram**, 105 arquivos Python formatados |
| `node scripts/check-bundle.mjs` | **Passou** para os segredos configurados |
| `git diff --check` | **Passou** nos arquivos rastreados |

As execuções de teste Python usaram imagem de ferramentas existente, código montado somente leitura, rede desativada e SQLite temporário. Ruff foi executado com as ferramentas já disponíveis; não foi usado `--unsafe-fixes` nem suprimida regra.

O ambiente operacional era o projeto **academia-business-tests**, com banco, volume e rede próprios, sem portas públicas. O caminho Python foi explicitado para carregar o código montado, evitando testar a versão antiga instalada na imagem. Worker, Beat e Redis utilizados nos probes eram processos reais, não mocks.

### Falhas operacionais exercitadas

| Cenário | Evidência |
| --- | --- |
| Agendamento periódico | Uma mensalidade foi criada e identificada/processada por Beat/worker sem varredura manual |
| Redis indisponível | Redis do teste foi parado; intenção permaneceu no banco, sem consumir tentativa de envio |
| Redis restaurado | Pendência foi republicada e recebeu um único recibo |
| Worker interrompido durante transação | Remetente foi pausado e o contêiner worker recebeu SIGKILL; verificado rollback sem tentativa ou recibo parcial |
| Worker reiniciado | Nova reserva recuperou a pendência; tarefa com token antigo foi ignorada e permaneceu somente um recibo |

Os sete registros operacionais, incluindo as preparações, estão preservados em [EVIDENCIAS/2026-11-10-automacao-runtime.json](EVIDENCIAS/2026-11-10-automacao-runtime.json), com datas UTC e IDs descartáveis. O registro diário converte os marcos para Fortaleza.

Para reduzir a duração do teste, Beat usou intervalos de 1/2 segundos somente no probe. A mensagem pausada recebeu timeout maior de teste, permitindo o SIGKILL determinístico. Datas de backoff/reserva foram aceleradas no banco descartável durante a recuperação. A agenda normal 300/60 segundos, os limites normais 15/20 segundos e a política de retry não foram alterados por esses probes.

O teste de navegador criou mensalidade vencida, verificou o processamento pelo worker real, consultou o histórico e repetiu a varredura sem aumentar o número de tentativas. Os testes anteriores de login, permissões, pagamentos, Pix simulado e apresentação móvel continuaram passando.

## Bug encontrado e resolvido em 10/11/2026

**NF-001 — transação implícita após registrar falha de envio.** Encontrado na implementação nova, antes da implantação. `_send_failed` lia `reminder.status` depois do commit; a expiração padrão do SQLAlchemy disparava nova consulta e abria transação automaticamente. A sessão ficava ocupada para uma operação seguinte.

O teste `test_failed_service_does_not_open_implicit_transaction` falhou e comprovou o comportamento. A correção captura o estado antes de encerrar a transação e retorna a variável. O mesmo teste passou depois da correção e permanece na suíte. O bug e os registros do dia estão em [REGISTRO_DIARIO/2026-11-10.md](REGISTRO_DIARIO/2026-11-10.md).

Nenhum outro bug foi confirmado nesta rodada. Falhas de Redis, remetente e worker foram injeções intencionais de teste, com comportamento de recuperação verificado; não foram classificadas como bugs novos.

## Pendências, riscos remanescentes e validação manual

1. **Implantação:** o banco principal e os contêineres atuais não foram atualizados. Para ver o recurso no servidor atual, falta autorização para backup, migração `20261110_05`, atualização das imagens e ativação explícita da automação.
2. **PostgreSQL real e carga:** não validados nesta rodada. SQLite permite um escritor por vez; lotes pequenos e transações curtas reduzem disputa, mas não substituem teste de carga ou validação em PostgreSQL.
3. **Mensagens reais:** fora do escopo. Um futuro remetente externo precisará de idempotência própria e tratamento de falhas entre envio externo e commit; o recibo local não prova entrega externa.
4. **Prazos:** o scheduler e o Redis precisam estar operacionais para novas publicações. Recuperação é eventual; não é prometido envio no minuto exato. Reiniciar Beat pode perder sua agenda temporária, mas não as intenções e recibos do banco.
5. **Histórico e retenção:** a API não permite apagar registros; o downgrade protege contra descarte acidental. Backup, retenção e controle de operadores com acesso SQL privilegiado continuam necessários.
6. **Dependências:** permanece o aviso preexistente Starlette/TestClient referente a `httpx`. Nenhuma dependência foi atualizada nesta entrega.
7. **Verificações manuais sugeridas:** testar filtros/paginação com muitos alunos; nomes longos e layout móvel do novo painel; quitar/cancelar enquanto uma intenção aguarda o worker; conferir fuso na virada do dia; reabrir ciclo esgotado com motivo; observar autenticação durante indisponibilidade controlada de Redis em ambiente de teste.

Os testes passaram para os casos descritos; isso não significa ausência de bugs em entradas ou condições ainda não exercitadas. As alterações anteriores da pasta foram preservadas, sem commit, reset ou remoção de caches do usuário. O trabalho foi interrompido a pedido do usuário. O comando de encerramento do ambiente descartável foi rejeitado e não executado; seus contêineres e volume podem continuar presentes. Não houve nova tentativa. As evidências documentais foram preservadas.

Guia de uso e contratos: [AUTOMACAO_FINANCEIRA.md](AUTOMACAO_FINANCEIRA.md).
