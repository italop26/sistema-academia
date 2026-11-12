# Automação financeira — lembretes simulados

Implementação de 10/11/2026. **Nenhuma mensagem real é enviada.** O único remetente disponível é `SimulatedReminderSender`, que produz recibo/texto locais, sem endereço de destinatário, SDK ou conexão com serviço de mensagens.

## Fluxo

1. Beat publica `notifications.scan_overdue` a cada 300 segundos.
2. O worker procura mensalidades `pendente` cujo vencimento seja anterior ao dia atual em `America/Fortaleza`.
3. Cada mensalidade/regra gera uma intenção persistida em `reminders`, na mesma transação do histórico.
4. Beat publica `notifications.dispatch_pending` a cada 60 segundos. O dispatcher reserva pendências e publica somente IDs/tokens no Redis.
5. O worker revalida a mensalidade, simula o envio e confirma recibo, tentativa e histórico na mesma transação.

O teste que exigia agenda vazia foi substituído por verificação dos nomes, intervalos e parâmetros das tarefas. Redis, worker, scheduler e instância Celery existentes são reutilizados; não há novo broker.

Mensalidade vencida continua sendo um estado calculado. A tarefa não reescreve o estado persistido para `vencida`, não quita mensalidades e não gera novas competências. Uma matrícula/aluno desativado não apaga uma obrigação já emitida; a elegibilidade depende da mensalidade e do pagamento.

## Configuração

| Variável | Padrão | Limites |
| --- | --- | --- |
| `FINANCIAL_AUTOMATION_ENABLED` | `false` | Ativa planejamento, publicação e simulação |
| `NOTIFICATION_BATCH_SIZE` | `50` | 1 a 200 registros por rodada |
| `NOTIFICATION_DISPATCH_LEASE_SECONDS` | `120` | 30 a 600 segundos |

O `.env` atual não foi alterado. O recurso fica desligado até ativação explícita. As tarefas continuam registradas, mas não processam intenções enquanto estiver desativado. Consultas de histórico permanecem disponíveis.

As tarefas têm limite suave de 15 segundos e limite rígido de 20 segundos. A reserva padrão é mais longa que o limite rígido. A entrega usa `acks_late`, `reject_on_worker_lost` e prefetch 1; o transporte Redis tem `visibility_timeout=300`. As tarefas de notificações ignoram o backend de resultados: o estado operacional vem do banco, não de `AsyncResult`.

Mantenha um scheduler operacional. Se ele for duplicado ou reiniciado, a unicidade por mensalidade/regra e a reserva impedem envio simulado repetido. Se o Beat ficar indisponível, as próximas rodadas retomam as pendências; não há garantia de execução no horário exato.

## Outbox e idempotência

`Reminder` funciona como intenção de envio e outbox específica do domínio. Não foi criado um barramento genérico de eventos. `ReminderAttempt` preserva cada tentativa efetiva de simulação.

- Chave única `(monthly_fee_id, rule_key)`, com regra atual `overdue-v1`: **um lembrete de atraso por mensalidade**, sem repetição diária.
- Recibo único determinístico `TEST-REMINDER-<id>`.
- Tentativas únicas por `(reminder_id, number)`.
- Relações com `ON DELETE RESTRICT`; sem endpoints de exclusão de histórico.

A seleção em lotes exclui intenções já existentes, evitando que as mesmas mensalidades ocupem indefinidamente o primeiro lote. Planejamento e entrega revalidam o estado dentro da transação. SQLite usa `BEGIN IMMEDIATE`; PostgreSQL preserva o caminho de bloqueio de linha, ainda pendente de validação com banco real.

A publicação ocorre **depois do commit** da intenção. Cada publicação reserva um token com prazo. Publicação falha libera a reserva, registra erro seguro e agenda nova publicação após 60 segundos. Isso não consome tentativa de envio.

Se o broker aceitar a mensagem e o processo cair antes de qualquer confirmação local, a reserva permite recuperar a pendência. Se o Redis perder a fila durante reinício, a intenção permanece no banco. Reservas vencidas podem ser republicadas com novo token; tarefas com token antigo são ignoradas. Se a simulação já foi confirmada, a reentrega também não gera outro recibo.

Antes da simulação, a ordem de bloqueio é mensalidade → lembrete, compatível com as transações financeiras. Leituras após espera por bloqueio recarregam o lembrete para não usar token/estado antigo da sessão.

## Pagamento, cancelamento e retry

O serviço verifica novamente:

- Mensalidade ainda pendente e em atraso.
- Ausência de pagamento aplicado, inclusive se houver inconsistência entre pagamento e status.
- Reserva válida, token atual e data da próxima tentativa atingida.

Se paga/cancelada/sem atraso, o lembrete fica `suppressed`, com motivo e histórico. Nenhum remetente é chamado e nenhuma tentativa de envio é consumida. Uma pendência pode continuar aparecendo como pendente até o worker fazer essa revalidação; isso não representa nova dívida.

Envio simulado que falha permite **três tentativas por ciclo**: inicial, nova tentativa após 60 segundos e última após mais 300 segundos. Depois, fica `exhausted`. O retry usa as datas persistidas; não há loop infinito de `Celery.retry` ou duplicação de agendas para o mesmo lembrete.

O administrador pode reabrir no máximo três ciclos adicionais, sempre com motivo. O total histórico é preservado, podendo chegar a 12 tentativas em quatro ciclos. Pagamento/cancelamento é revalidado também nessa reabertura. Lembretes enviados ou dispensados não podem ser reabertos.

Falha no histórico desfaz o recibo e o estado do envio. Se a própria gravação do erro falhar, a reserva anterior permanece recuperável após expirar. Exceções e dados internos não são copiados para mensagens administrativas; são usados códigos seguros e logs com tipo da exceção.

Essa atomicidade vale para o remetente **local simulado**. Um futuro remetente externo precisará oferecer idempotência própria e tratamento do intervalo entre envio externo e commit. A implementação não promete entrega externa exatamente uma vez.

## Administração e painel

Todas as rotas exigem administrador autenticado:

| Método | Caminho | Uso |
| --- | --- | --- |
| GET | `/admin/notifications/summary` | Ativação e contadores por estado |
| POST | `/admin/notifications/scan` | Planeja um lote e tenta publicar pendências já persistidas |
| GET | `/admin/notifications/reminders` | Lista; filtros `student_id`, `status`, `offset`, `limit` até 200 |
| GET | `/admin/notifications/reminders/{id}` | Detalhe do lembrete |
| GET | `/admin/notifications/reminders/{id}/attempts` | Histórico de tentativas |
| POST | `/admin/notifications/reminders/{id}/retry` | Reabre ciclo elegível, com `reason` |

O histórico comum aceita `entity_type=reminder`. A lista mostra aluno, competência, valor, estado e tentativas. O painel consulta os dados periodicamente, possui filtros/paginação, consulta de histórico e reabertura com motivo. Não mostra tokens internos de reserva.

Estados: `pending`, `retry_wait`, `sent`, `exhausted`, `suppressed`. `sent` significa somente **simulação registrada**, nunca mensagem real enviada.

A autenticação existente depende do Redis e continua falhando de modo fechado: se ele estiver indisponível, ações administrativas podem retornar 503. Isso não apaga a outbox e não cria um caminho alternativo que dispense autenticação.

## Migração, testes e implantação

`20261110_05` cria `reminders`, `reminder_attempts`, índices e restrições. Revisões anteriores são preservadas. Downgrade é bloqueado quando existirem lembretes, para não descartar histórico.

`test_notifications.py` cobre regras, concorrência, retry, permissões e regressão NF-001. O ambiente `academia-business-tests` usa worker e Beat reais, Redis próprio e SQLite descartável. Os probes `notification_test_worker.py`, `notification_test_scheduler.py` e `notification_runtime_check.py` são exclusivos desse ambiente e recusam outro banco/ambiente.

O Beat de testes é acelerado para 1/2 segundos; a agenda normal continua 300/60 segundos. O teste de queda pausa o remetente local e usa uma janela de timeout maior somente na mensagem de teste para permitir SIGKILL determinístico. Recuperação acelera datas da reserva/backoff no banco descartável; a política normal permanece inalterada.

Consulte [RELATORIO_AUTOMACAO_FINANCEIRA.md](RELATORIO_AUTOMACAO_FINANCEIRA.md) e o [registro diário](REGISTRO_DIARIO/2026-11-10.md) para resultados, bug corrigido e pendências. O banco principal e os contêineres atuais não foram atualizados. Implantação exige autorização específica, backup, migração, atualização das imagens e ativação explícita do recurso.
