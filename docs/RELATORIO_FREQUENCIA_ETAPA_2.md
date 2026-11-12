# Frequência — etapa 2: ausência

Data: 12/11/2026, America/Fortaleza. Etapa autorizada junto com o check-in.

Atualização: a integração real e a regressão final passaram no [fechamento das três etapas](RELATORIO_FREQUENCIA_ETAPA_3.md). Os resultados abaixo registram a rodada desta etapa.

## Entrega

- Tarefa `absence.scan` no Celery/Beat existente, a cada 300 segundos.
- `ABSENCE_TRACKING_ENABLED=false` por padrão; `.env` principal preservado.
- Regra fixa de 240 horas em UTC, com vigência contratual interpretada em Fortaleza.
- Sem check-in: carência desde o início elegível ou a primeira ativação persistida do acompanhamento, o mais recente.
- Elegibilidade considera vigência, criação efetiva, cancelamento e suspensões. Uma matrícula disponível mantém o aluno elegível; uma lacuna em todas as matrículas reinicia a carência.
- Unicidade por aluno, regra e início do episódio impede alertas repetidos.
- Cursor persistido, lotes limitados, reserva com prazo de 120 segundos e histórico de execuções. Progresso por aluno, detecção e auditoria são confirmados na mesma transação.
- Até três retries Celery por execução para falhas transitórias, com 60/300/900 segundos. Varreduras periódicas futuras também podem recuperar o trabalho; não é prometido o minuto exato.
- Migração `20261112_02` exercitada somente em SQLite temporário.

## Testes desta etapa

**27 testes passaram**, incluindo ausência e configuração/agenda. Cobertura: limite exato de 240 horas, carência inicial, último check-in, inatividade/cancelamento/vigência, suspensão/retomada, múltiplas matrículas, lacunas, lotes, concorrência, idempotência, rollback, backoff, reserva interrompida, retries, schema e downgrade protegido. A data `9999-12-31` foi testada para evitar overflow.

Integração com Beat/worker reais e regressão global serão verificadas ao concluir a etapa 3, autorizada durante esta implementação.

## Limites

Não envia mensagens. Os estados e ações administrativos serão adicionados na etapa 3. Se o processo perder acesso ao SQLite, a gravação do erro também poderá falhar; a reserva expira e permite recuperação. Falha persistente no mesmo aluno exige análise, preservando o cursor para não perder a detecção.

Sem dependências instaladas, migração principal, commit, push ou deploy.
