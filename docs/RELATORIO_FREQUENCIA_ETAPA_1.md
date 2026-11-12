# Frequência — etapa 1

Data: 12/11/2026, America/Fortaleza. Implementação das etapas 1 e 2 autorizada; este registro descreve a primeira etapa.

Fechamento posterior das três etapas: [RELATORIO_FREQUENCIA_ETAPA_3.md](RELATORIO_FREQUENCIA_ETAPA_3.md). Os resultados abaixo preservam a validação desta etapa.

## Entrega

- Módulo `attendance`: check-in administrativo, histórico individual paginado e resumo com última visita/total.
- Uma presença por aluno por dia em Fortaleza. Horário definido pelo servidor, sem retroatividade, edição ou exclusão.
- Chaves idempotentes persistidas inclusive para solicitações diferentes que retornam a presença diária existente. Replay de uma chave conserva a resposta original mesmo em outro dia; reuso incompatível retorna 409.
- Aluno ativo e matrícula pertencente ao aluno, vigente, ativa e sem suspensão são exigidos para uma nova solicitação.
- Suspensão e retomada com motivo, períodos preservados e auditoria. Retomar um período antigo não encerra uma suspensão posterior. Contratos, preço e obrigações financeiras permanecem com suas regras anteriores.
- Novo painel React para presença e suspensão. Migração `20261112_01` escrita; aplicada apenas em bancos descartáveis.
- Campo interno `cancelled_at` preserva o instante final da elegibilidade. Migração recupera o instante do histórico de cancelamento quando disponível, com fallback para a criação da matrícula antiga.

## Verificação desta etapa

- **59 testes de backend passaram:** 17 de frequência/suspensões e 42 de regressão de negócio.
- **13 testes de navegador passaram**, incluindo o novo fluxo completo em API/SQLite/Redis reais descartáveis.
- **24 testes JavaScript passaram**; build Vite passou, com 39 módulos; verificador dos segredos configurados no bundle passou.
- Testes cobrem concorrência, idempotência, virada do dia, matrícula inválida, permissões, auditoria atômica, restrição diária e bloqueio de downgrade quando há histórico.
- Ruff/format aplicado com ferramenta existente, sem instalar dependências. Verificações globais serão repetidas ao concluir a etapa 2.

## Falha corrigida durante a validação

O primeiro teste de navegador revelou que `crypto.randomUUID` não estava disponível na origem HTTP interna de testes. O painel passou a gerar UUID v4 com `crypto.getRandomValues`, preservando aleatoriedade e compatibilidade. A suíte de navegador completa passou após a correção.

Uma tentativa de testes também foi interrompida por erro transitório de sintaxe no arquivo de alunos durante edição simultânea; o arquivo já estava corrigido na leitura seguinte. Nenhuma alteração foi feita nesse arquivo por esta implementação.

## Limites

Sem check-in por aula, importação de presença antiga ou alteração das cobranças por suspensão. Suspensões são imediatas, sem agendamento futuro. O painel de acompanhamento de ausências continua reservado à etapa 3.

O banco e os contêineres principais não foram alterados. Sem commit, push ou deploy. O ambiente descartável será parado ao terminar as duas etapas.
