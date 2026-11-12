# Alunos, planos, matrículas e mensalidades

Implementação de 10/11/2026. Todos os endpoints desta base exigem JWT de administrador ativo, validado pelo mecanismo existente. Não existe acesso público a cadastros, valores ou históricos. `member` continua sendo um perfil de autenticação; aluno é um cadastro separado com vínculo opcional e único a uma conta.

## Organização

- `backend/app/modules/students/`: alunos, e-mail opcional, conta opcional e desativação.
- `backend/app/modules/plans/`: planos com mensalidade positiva e desativação.
- `backend/app/modules/enrollments/`: matrícula vinculada ao aluno e ao plano, vigência, vencimento e valor contratado.
- `backend/app/modules/billing/`: mensalidades por competência, baixa manual e cancelamento.
- `backend/app/modules/audit/`: histórico comum gravado na transação da alteração.
- `backend/app/core/domain.py`: validações comuns, relógio local e normalização de timestamps UTC.
- `backend/app/core/dependencies.py`: dependências de administrador e sessão de negócio.

Routers recebem/validam HTTP e exigem permissões; services coordenam regras e transações; repositories concentram consultas. Não foram criados outro login, outra conexão Redis ou outra instância Celery. O frontend compartilha o transporte em `frontend/src/api/http.js`, mantendo o token privado na sessão existente.

## Regras

1. Valores são inteiros em centavos, maiores que zero, limitados a 2.000.000.000 centavos. JSON com float, booleano ou string no lugar de centavos é rejeitado. Restrições de integridade também impedem valores negativos, nulos e fracionados no banco.
2. Uma matrícula copia o preço vigente do plano. Alterações posteriores no plano não recalculam o contrato nem as mensalidades. Esta base não oferece edição de preços contratados.
3. Aluno e plano devem estar ativos ao matricular. Não é permitido duplicar matrícula com estado `ativa` para o mesmo aluno/plano. Planos distintos são permitidos. A vigência por datas é verificada ao emitir a mensalidade; terminar a vigência não muda automaticamente o estado administrativo da matrícula. Para renovar o mesmo plano, cancele a matrícula anterior.
4. Competência usa `AAAA-MM` na API e uma data no primeiro dia do mês no banco. Restrição única `(enrollment_id, competence)` impede duplicação. Repetir a emissão devolve a mensalidade existente sem recalcular valores ou duplicar histórico, inclusive se já paga ou cancelada.
5. A competência deve ter ao menos um dia em comum com a vigência de uma matrícula ativa. Não há proporcionalidade: o valor mensal contratado é integral. No primeiro mês o dia de vencimento pode anteceder o início da matrícula. Essa regra deve ser revista antes de adotar proporcionalidade ou política diferente para o primeiro vencimento.
6. O vencimento usa o dia contratado de 1 a 31, limitado ao último dia do mês. Fevereiro e anos bissextos são tratados.
7. Estados persistidos: `pendente`, `paga` e `cancelada`. A API apresenta `vencida` quando uma pendente tem vencimento anterior ao dia atual em `America/Fortaleza`. O dia do vencimento ainda é pendente. Esse estado temporal não exige escrita diária nem tarefa Celery e não cria um evento de histórico.
8. Pagamento manual exige o valor integral exato e uma observação de 3 a 500 caracteres. Não há pagamento parcial, juros, multa, desconto ou devolução. O backend registra horário UTC da confirmação e administrador responsável.
9. Ao pagar, a resposta retorna `status=paga` e `completed=true`; a interface mostra **Concluída** apenas para aquela mensalidade e aluno. Repetir a baixa com o valor correto devolve o registro existente; não altera a observação original nem cria outro pagamento.
10. Mensalidade cancelada não pode ser paga; mensalidade paga não pode ser cancelada diretamente. Cancelamento exige motivo. Repetir o cancelamento não duplica histórico. Não há reabertura nesta etapa.
11. Cancelar matrícula impede novas emissões, mas preserva mensalidades já emitidas. Desativar aluno/plano impede novas matrículas e preserva as matrículas e obrigações existentes. Não há endpoints de exclusão física.

## Transações e histórico

A autenticação usa sua sessão original; uma dependência distinta abre a sessão de negócio. Isso evita iniciar uma transação de escrita dentro da transação já aberta pela consulta do usuário.

Os serviços abrem a transação antes da primeira leitura de estado. SQLite usa `BEGIN IMMEDIATE`, serializando escritores; PostgreSQL usa `SELECT ... FOR UPDATE` nos registros relevantes. Restrições únicas permanecem como defesa adicional. Se o SQLite continuar ocupado após o timeout, a API responde 503 para nova tentativa; conflitos de integridade retornam 409 com mensagem genérica.

`PRAGMA foreign_keys=ON` é habilitado em cada conexão SQLite da aplicação. Os relacionamentos usam `ON DELETE RESTRICT`, preservando referências históricas.

Cada cadastro, desativação, cancelamento, emissão e baixa adiciona um `audit_events` com entidade, identificador, ação, autoria, data, motivo e snapshots anterior/posterior. A partir da revisão `20261110_03`, a baixa cria `payments` com vínculo único à mensalidade; os registros da antiga `manual_payments` são migrados preservando IDs, valores, responsáveis, observações e datas. `actor_type` distingue administrador de sistema, sem atribuir um usuário fictício à simulação. Mudança de estado, pagamento e evento são confirmados ou revertidos juntos. Uma falha ao gravar histórico desfaz a baixa.

O histórico é de acréscimo pela API, sem endpoints de atualização/exclusão. Ele não é um armazenamento inviolável: um operador com privilégios diretos de banco ainda pode alterá-lo. Backups, controle de acesso ao banco e política de retenção continuam necessários. Snapshots de alunos podem conter nome/e-mail; o histórico exige permissão administrativa e não deve ser exportado publicamente.

## Endpoints

Prefixo comum: `/admin`. Listagens aceitam `offset` e `limit` (máximo 200); o frontend percorre as páginas.

| Método | Caminho | Uso |
| --- | --- | --- |
| POST / GET | `/students` | Cadastrar/listar alunos |
| GET | `/students/{id}` | Consultar aluno |
| POST | `/students/{id}/deactivate` | Desativar com `reason` |
| POST / GET | `/plans` | Cadastrar/listar planos |
| POST | `/plans/{id}/deactivate` | Desativar com `reason` |
| POST / GET | `/enrollments` | Matricular/listar; filtro opcional `student_id` |
| GET | `/enrollments/{id}` | Consultar matrícula |
| POST | `/enrollments/{id}/cancel` | Cancelar com `reason` |
| POST | `/monthly-fees/generate` | Emitir com `enrollment_id` e `competence` |
| GET | `/monthly-fees` | Listar; filtros `student_id` e `competence` |
| GET | `/monthly-fees/{id}` | Consultar mensalidade e estado calculado |
| POST | `/monthly-fees/{id}/pay` | Baixa com `amount_cents` e `note` |
| POST | `/monthly-fees/{id}/cancel` | Cancelar com `reason` |
| GET | `/monthly-fees/{id}/payment` | Consultar recebimento manual |
| GET | `/history` | Histórico com `entity_type` e `entity_id` obrigatórios |

Tipos aceitos no histórico: `student`, `plan`, `enrollment`, `monthly_fee`. A API usa identificadores UUID. Leituras administrativas e respostas de autenticação recebem `Cache-Control: no-store`.

## Migrações e ativação

- `20261109_01`: revisão original de usuários, preservada.
- `20261110_01`: alunos, planos, matrículas e histórico.
- `20261110_02`: mensalidades e recebimentos manuais.
- `20261110_03`: cobranças, pagamentos comuns e autoria automática; veja [PIX_SIMULADO.md](PIX_SIMULADO.md). O downgrade dessa revisão é bloqueado se existirem cobranças ou registros automáticos para evitar descarte silencioso de histórico.
- `20261110_04`: eventos de webhook de teste persistidos; veja [WEBHOOKS_PIX_SIMULADOS.md](WEBHOOKS_PIX_SIMULADOS.md). O downgrade é bloqueado quando existirem eventos.
- `20261110_05`: intenções duráveis e tentativas de lembretes simulados; veja [AUTOMACAO_FINANCEIRA.md](AUTOMACAO_FINANCEIRA.md). O downgrade recusa descartar lembretes existentes.

As novas revisões criam tabelas e restrições sem remover usuários. Foram aplicadas somente em bancos temporários e no ambiente isolado de navegador, nunca no banco atual da academia durante esta entrega.

Para atualizar o ambiente atual, ainda é necessário autorizar a implantação, realizar backup, aplicar as novas revisões e recriar os serviços com o código novo. Não execute downgrade com dados financeiros: ele remove as novas tabelas e o histórico. Os testes de downgrade usam exclusivamente bancos descartáveis.

## Validação reproduzível

Backend: executar a suíte com `pytest -m "not integration" -q` em ambiente isolado com as dependências existentes. As fixtures migram somente arquivos SQLite temporários. `test_business.py` cobre regras, permissões, concorrência, integridade e atomicidade do histórico; a suíte anterior continua cobrindo autenticação e configuração.

Frontend: `npm test`, `npm run build` e, da raiz, `node scripts/check-bundle.mjs`.

Para navegador, `compose.business-tests.yaml` usa imagens locais existentes, rede interna sem portas publicadas e volume próprio. Não usa `.env` nem volumes da academia. Com as imagens locais `sistemadeacademia-tests` e `academia-validation-e2e` disponíveis:

```sh
docker compose -p academia-business-tests -f compose.business-tests.yaml up -d redis backend frontend
docker compose -p academia-business-tests -f compose.business-tests.yaml run --rm e2e
docker compose -p academia-business-tests -f compose.business-tests.yaml down --volumes
```

O último comando remove somente os dados descartáveis desse projeto de testes. Não reutilize seu nome com outra composição. Imagens não são reconstruídas automaticamente por essa composição; se as dependências mudarem no futuro, as imagens de teste deverão ser atualizadas primeiro.

## Limites desta entrega

Existe Pix somente simulado, detalhado em [PIX_SIMULADO.md](PIX_SIMULADO.md), webhook de teste com eventos persistidos e [lembretes exclusivamente simulados](AUTOMACAO_FINANCEIRA.md). Sem integração Pix real, mensagens reais, emissão automática de novas mensalidades, devoluções, edição financeira, portal do aluno ou isolamento de múltiplas academias. Celery e Redis existentes executam as tarefas financeiras; a validação em PostgreSQL real permanece pendente.
