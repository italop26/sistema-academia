# Relatório — Pix simulado, etapa 2

Data: 10/11/2026, referência America/Fortaleza. Implementação simplificada autorizada: processamento imediato, sem nova fila ou automação Celery.

## Resultado

- `POST /webhooks/pix/simulated`: exige simulador habilitado e segredo exclusivo de testes, com HMAC-SHA256 sobre timestamp e corpo original. A assinatura expira após cinco minutos de diferença do relógio.
- Novo módulo `backend/app/modules/webhooks/` com autenticação, schemas, model, repository, service e routers.
- Revisão `20261110_04`: tabela de eventos com payload normalizado, hash, contadores, resultado, falhas e vínculos de cobrança/pagamento. Nenhuma revisão anterior alterada.
- Recebimento e processamento usam transações separadas. A confirmação financeira, o resultado do evento e o histórico são atômicos; após rollback, a falha é registrada em nova transação.
- Eventos repetidos são identificados por provedor/ID. Reuso do ID com conteúdo diferente recebe 409 e registra contagem/hash do conflito, sem substituir o original.
- Eventos recebidos, processados, ignorados, rejeitados e com falha são distinguíveis. Falhas e interrupções anteriores ao processamento podem ser retomadas administrativamente.
- `GET /admin/pix/events`, `GET /admin/pix/events/{id}` e `POST /admin/pix/events/{id}/retry` exigem administrador. Nova tentativa exige motivo e gera histórico com o responsável; a quitação continua atribuída ao sistema simulado.
- Configuração e `.env.example` documentam `PIX_WEBHOOK_TEST_SECRET`. O segredo não é retornado, salvo no evento ou disponibilizado ao frontend. O `.env` atual não foi alterado.
- Histórico administrativo inclui `webhook_event`; respostas de webhook não usam cache. O verificador de bundle também procura o novo segredo quando configurado.

## Validação desta etapa

Executado `pytest tests/test_webhooks.py -q -x --tb=short -p no:cacheprovider`: **10 testes passaram** em SQLite temporário, em contêiner sem rede. Os casos incluem confirmação, repetição, assinatura falsa/ausente, conflito de conteúdo, falha durável, recuperação administrativa, recuperação de interrupção, valor divergente, permissões e filtro de eventos.

O teste de falha comprovou que mensalidade, cobrança e pagamento voltam ao estado anterior, enquanto o evento permanece com erro genérico e pode ser processado após corrigir a falha. A confirmação posterior registra somente um pagamento.

As verificações finais e a matriz ampliada são registradas no [relatório da etapa 3](RELATORIO_PIX_ETAPA_3.md), autorizada em conjunto: **194 testes de backend, 24 de frontend e 10 de navegador passaram**. Ruff e build também passaram. Houve somente o aviso existente de depreciação Starlette/TestClient sobre `httpx`; não foram instaladas ou atualizadas dependências.

## Regras e limites

O contrato aceita confirmação de pagamento, indicação de pendência e cancelamento da cobrança. Estados terminais não regridem. Divergências de referência, valor, moeda, data ou estado são preservadas como rejeição para análise, sem quitação automática. Cobrança cancelada/expirada não é reativada por confirmação tardia nesta simulação.

HTTP 200 indica processamento concluído/ignorado; 202 indica evento guardado que exige nova tentativa ou análise. HTTP 401/413/422 rejeita autenticação/tamanho/formato antes da persistência; 409 indica reutilização conflitante de ID.

O segredo e a autenticação são exclusivos do contrato de testes. A integração futura precisará das regras do provedor real. Sem SDK, credenciais reais, provedor escolhido, alteração do banco principal ou atualização do servidor atual.

Não existe tela administrativa dedicada aos eventos nesta entrega; consultas e nova tentativa são disponibilizadas pela API. Nenhum job automático foi criado. A operação deve consultar eventos `received`/`failed` e acionar a nova tentativa administrativa após resolver o problema.
