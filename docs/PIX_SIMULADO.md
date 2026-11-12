# Pix simulado — arquitetura e confirmação de testes

Implementação de 10/11/2026 para estudo e portfólio. **SIMULAÇÃO — NÃO REALIZA PAGAMENTO.** Não existe conexão com banco, instituição de pagamento ou provedor externo. Não há SDK, credenciais reais, QR Code ou código Pix utilizável.

## Entidades

| Entidade | Responsabilidade |
| --- | --- |
| `MonthlyFee` / `monthly_fees` | Obrigação mensal por matrícula e competência; valor devido e estado financeiro |
| `Charge` / `charges` | Tentativa de cobrança vinculada à mensalidade, com referência, valor, moeda e expiração próprios |
| `Payment` / `payments` | Recebimento aplicado à mensalidade; manual ou Pix simulado, com origem identificada |

Uma mensalidade pode ter várias tentativas de cobrança e no máximo um pagamento aplicado. Cobrança criada não significa pagamento. O índice único de `payments.monthly_fee_id` protege os dois canais; a tabela não é um extrato de recebimentos bancários adicionais ou de devoluções.

A tabela antiga `manual_payments` é migrada para `payments` pela revisão `20261110_03`. Todos os IDs, valores, autores, observações e datas são copiados sem alteração. Não são mantidos dois livros de pagamentos. O nome Python `ManualPayment` permanece como alias temporário de `Payment` para compatibilidade com chamadas anteriores.

## Interface e simulador

`backend/app/modules/payments/providers.py` define:

- `PixProvider`, contrato estrutural para criação de cobrança.
- `ChargeRequest` e `ProviderCharge`, objetos imutáveis de entrada/saída.
- `SimulatedPixProvider`, único adaptador disponível nesta etapa.

O simulador produz uma referência determinística `TEST-PIX-<UUID da cobrança>` e conserva a expiração solicitada. Não gera um payload EMV. As respostas contêm `is_simulated=true`, o aviso explícito de simulação e `payment_code=null`.

O contrato constitui um ponto de extensão, não uma integração real pronta. Um adaptador real exigirá regras próprias de autenticação, consulta, status, conciliação, timeout e entrega. O adaptador atual não faz I/O; por isso é executado na transação local. Não se deve simplesmente substituir esse adaptador por chamadas de rede dentro de uma transação financeira longa.

## Ativação e permissões

`PIX_SIMULATOR_ENABLED` é `false` por padrão. A configuração está documentada em `.env.example`; o `.env` atual não foi alterado nesta entrega.

A ativação exige ambiente `development` ou `test` e configuração explícita `PIX_SIMULATOR_ENABLED=true`. A combinação de `APP_ENV=production` com simulador habilitado é rejeitada na validação de configuração. Os serviços de criação/liquidação simulada também verificam o bloqueio em tempo de execução.

Todos os endpoints exigem administrador autenticado pelo mecanismo existente. O corpo da solicitação não permite escolher provedor, valor ou flag de simulação. Esses dados são definidos no servidor.

Leituras administrativas permanecem disponíveis para consultar registros já existentes mesmo se o simulador tiver sido desativado. Desativação bloqueia novas criações e liquidações simuladas, sem apagar o histórico.

## Endpoints da etapa 1

| Método | Caminho | Uso |
| --- | --- | --- |
| POST | `/admin/pix/charges` | Criar ou recuperar uma cobrança simulada idempotente |
| GET | `/admin/pix/charges?monthly_fee_id=<UUID>` | Consultar tentativas da mensalidade; aceita `offset` e `limit` |
| GET | `/admin/pix/charges/{id}` | Consultar cobrança e estado efetivo |

Exemplo de corpo para criação, com UUIDs ilustrativos que devem ser substituídos pelos dados de teste:

```json
{
  "monthly_fee_id": "11111111-1111-4111-8111-111111111111",
  "idempotency_key": "22222222-2222-4222-8222-222222222222",
  "expires_in_seconds": 3600
}
```

A mensalidade precisa existir e estar pendente, incluindo as que a API apresenta como vencidas. Valor e moeda são copiados no servidor; somente BRL está suportado. Expiração aceita inteiros entre 60 e 86.400 segundos, com padrão de 3.600.

A chave de idempotência é única por adaptador. Repetir a chave para a mesma mensalidade e mesma duração devolve a mesma cobrança, sem renovar a expiração ou duplicar histórico. Reutilizá-la para outra mensalidade ou duração retorna 409. Uma repetição legítima pode retornar cobrança já expirada, cancelada ou paga. Uma nova chave representa outra tentativa.

Estados persistidos: `pending`, `paid`, `cancelled`. `expired` é calculado quando a expiração UTC é alcançada e o registro ainda está pendente. Não há tarefa Celery nem alteração diária do banco.

## Liquidação comum e compatibilidade

O endpoint manual existente `/admin/monthly-fees/{id}/pay` chama `SettlementService`, que concentra validação de valor, moeda, estado, deduplicação e registro do recebimento. A liquidação usa os bloqueios já existentes: `BEGIN IMMEDIATE` no SQLite e bloqueio de linha no PostgreSQL.

Existe uma entrada **interna de teste** `SettlementService.settle_simulated(SimulatedReceipt)`, usada pelos testes para exercitar a mesma proteção entre canais. Ela exige o simulador habilitado, referência da cobrança correta, identificador de teste com prefixo `TEST-PAY-`, valor integral e cobrança válida. Confirmações HTTP passam pelo webhook autenticado e pela persistência de eventos, documentados em [WEBHOOKS_PIX_SIMULADOS.md](WEBHOOKS_PIX_SIMULADOS.md); não há rota de liquidação que contorne esse recebimento durável.

Uma confirmação idêntica devolve o pagamento existente; não cria outro evento de quitação. Outra origem ou referência para a mesma mensalidade recebe conflito. Uma mensalidade cancelada não é paga. Uma cobrança expirada/cancelada não liquida uma mensalidade pendente. O tratamento futuro de confirmações externas tardias dependerá do módulo de eventos e do contrato do provedor.

Pagamento manual mantém administrador e observação; Pix simulado registra autoria de sistema, sem criar usuário fictício. `audit_events.actor_type` é `admin` com `actor_id` obrigatório, ou `system` com `actor_id` nulo. O banco verifica essa combinação.

Pagamento, estado da mensalidade, encerramento das cobranças e histórico são confirmados na mesma transação. Falha no histórico reverte todos eles. Pagar a mensalidade encerra as demais tentativas pendentes; cancelar a mensalidade encerra suas cobranças pendentes. Não há cancelamento externo de uma cobrança real.

O endpoint existente `/admin/monthly-fees/{id}/payment` conserva os campos anteriores e acrescenta método, moeda, vínculo da cobrança, provedor, referência externa e indicador de simulação. Mensalidades acrescentam `payment_method`, `is_simulated` e `simulation_notice`. O frontend preserva **Concluída** para baixa manual e usa **Concluída (simulação)** quando aplicável.

## Migração e rollback

A revisão `20261110_03` cria `charges` e `payments`, transfere as baixas e adapta o histórico. As revisões anteriores não foram editadas. O teste de migração compara IDs, valores, autores, notas, datas e snapshots anteriores depois de downgrade/upgrade em banco descartável.

O downgrade somente permite retornar ao schema anterior quando não houver cobranças, pagamentos não manuais ou eventos de sistema. Caso contrário, ele interrompe antes das mudanças para preservar o histórico. Isso exige um plano específico de reversão após uso do simulador.

A migração foi executada apenas em bancos de testes. SQLite tem particularidades de DDL e reconstrução de tabela; em eventual implantação, é necessário backup e validação prévia, sem presumir rollback integral de DDL diante de falhas. PostgreSQL real ainda não foi validado para esta etapa.

## Evolução e limites atuais

As etapas 2 e 3 foram autorizadas e implementadas: webhook de testes autenticado, eventos persistidos, processamento imediato, nova tentativa administrativa e matriz adversarial. Consulte [WEBHOOKS_PIX_SIMULADOS.md](WEBHOOKS_PIX_SIMULADOS.md) e os relatórios das etapas.

A revisão `20261110_04` acrescenta a caixa de entrada durável de eventos. Nenhum provedor real foi selecionado. O banco principal e os contêineres da aplicação não foram atualizados.
