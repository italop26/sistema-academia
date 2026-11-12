# Fechamento da etapa local — SQLite

Data: **12/11/2026**, America/Fortaleza. Continuação autorizada pelo usuário para validar e atualizar o ambiente local. O usuário confirmou que o banco deste projeto é **SQLite**; validação em PostgreSQL não é requisito de fechamento desta etapa.

## Resultado

Etapa técnica local concluída: cadastros, matrículas, mensalidades, pagamentos, webhook Pix simulado e automação de lembretes foram validados em SQLite. O banco principal recebeu as migrações até `20261110_05`, depois de backup verificado e ensaio em cópia temporária. Nenhum dado de teste foi inserido no banco principal.

O frontend está em **http://localhost:5174**. API e Redis saudáveis; worker executou tarefa real; scheduler ativo; migração terminou com código zero. O proxy `/api/health` retornou banco e Redis `ok`.

`FINANCIAL_AUTOMATION_ENABLED=true` foi configurado somente no `.env` local. O remetente continua exclusivamente simulado. O simulador Pix permanece desativado no ambiente principal; foi habilitado somente nos testes. Nenhum pagamento real ou mensagem externa foi enviado.

O Compose original ainda inicia um serviço PostgreSQL auxiliar por sua dependência de infraestrutura. A URL efetiva da aplicação é SQLite; nenhum dado foi transferido para PostgreSQL. O ambiente descartável PostgreSQL inicialmente preparado foi parado assim que o usuário esclareceu o banco, e seus arquivos auxiliares de código foram retirados desta rodada.

## Achados e tratamento

| Prioridade | Área | Evidência | Impacto | Tratamento | Risco |
| --- | --- | --- | --- | --- | --- |
| P2 | Tela móvel | Novo teste em `frontend/e2e/notifications.spec.js` falhou por transbordamento com nome de 100 caracteres | Rolagem horizontal | `min-width`, limite de largura e quebra de texto em `frontend/src/styles.css`; teste passou | Baixo; regra restrita aos blocos das listas |
| P2 | Implantação local | Banco principal estava em `20261109_01` | Módulos novos indisponíveis | Backup, ensaio e upgrade até `20261110_05` concluídos | Migração financeira exige preservar backup |
| P2 | Acesso inicial | Contagem principal confirmou zero usuários | Login ainda exige cadastro inicial | Comando interativo documentado abaixo | Cadastro depende de nome, e-mail e senha do operador |
| P3 | Dependências de teste | Aviso Starlette/TestClient sobre `httpx` | Sem falha nos testes executados | Aviso registrado; nenhuma alteração de dependências no manifest | Avaliar atualização em trabalho separado |

## Verificações executadas

| Verificação | Resultado |
| --- | --- |
| Regressão final com imagem reconstruída | **221 passaram**, 2 testes de infraestrutura separados |
| Infraestrutura real, imagem reconstruída | **2 passaram** |
| Total distinto de backend | **223 passaram** |
| Frontend | **24 passaram** |
| Chromium, API/Redis/SQLite/worker reais descartáveis | **12 passaram**, nenhum pulado |
| Filtros, paginação, retorno e estado vazio | Passaram no navegador |
| Nome de 100 caracteres em viewport de 390 px | Passou após correção; captura inspecionada visualmente |
| Virada do dia em Fortaleza, incluindo fevereiro bissexto | 2 casos novos passaram |
| Pagamento/cancelamento antes de envio e recuperação | Cobertos pela regressão de lembretes |
| Beat → Redis → worker → recibo local | Passou |
| Carga limitada, imagem reconstruída | 120 mensalidades, 8 threads, 360 chamadas: 120 recibos únicos e 240 duplicatas ignoradas |
| Ruff e formatação | Passaram; 106 arquivos Python já formatados na verificação |
| Build Vite | Passou, 38 módulos |
| Verificação dos segredos configurados no bundle | Passou |
| Integridade e chaves estrangeiras do SQLite principal após migração | Passaram |
| Worker principal e frontend/proxy principal | Passaram |

Evidência operacional: [2026-11-12-sqlite-runtime.json](EVIDENCIAS/2026-11-12-sqlite-runtime.json). A carga é limitada e local; não determina capacidade máxima nem garante comportamento para qualquer volume. A captura móvel é um artefato local ignorado pelo Git em `frontend/test-results/notifications-mobile.png`.

## Backup e recuperação

Backup local ignorado pelo Git: `.backups/2026-11-12-stage/academia-before.db`. `manifest.json` guarda revisão, contagens, integridade e SHA-256; `environment-before.env` preserva a configuração anterior e contém segredos, portanto não deve ser compartilhado. O backup refletia um banco vazio, com zero usuários, na revisão `20261109_01`.

O procedimento reproduzível está em `scripts/sqlite-stage.py`: `backup` copia pela API SQLite e verifica a cópia; `rehearse` migra somente uma cópia em `/tmp`, confere metadata e contagens; `status` consulta integridade, revisão e flags sem imprimir credenciais. Rodar no contêiner backend, com `./scripts:/stage:ro` e o diretório de backup montado em `/backup`. O ensaio também exige os fontes atuais em `/app` e `PYTHONPATH=/app`.

Nenhuma restauração foi executada sobre o banco principal. Se houver dados novos após a implantação, restaurar o backup antigo os perderia; qualquer reversão precisa preservar primeiro o estado atual. Não usar downgrade automático para contornar as proteções do histórico financeiro.

## Cadastro inicial e escopo restante

O banco principal continua vazio. Para entrar, execute na raiz, em terminal interativo:

```powershell
docker compose run --rm --no-deps backend python -m app.modules.users.cli --name "Seu nome" --email "seu.email@exemplo.com"
```

A senha será solicitada duas vezes sem exibição, com 12 a 128 caracteres. Nenhuma conta padrão foi criada.

Pix real, mensagens reais, emissão automática de novas mensalidades, portal do aluno e publicação na internet continuam fora desta etapa. O Compose segue sendo de desenvolvimento local. Os ambientes descartáveis desta rodada foram parados, com volumes preservados. Mudanças anteriores foram preservadas, sem commit ou reset.
