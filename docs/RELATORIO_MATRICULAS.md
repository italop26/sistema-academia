# Relatório — base de matrículas e mensalidades

Data: 10/11/2026, referência de calendário America/Fortaleza.

## Entrega

As três etapas autorizadas foram implementadas preservando FastAPI, SQLAlchemy, SQLite/PostgreSQL, Alembic e a arquitetura modular. A conta de autenticação não foi substituída pelo cadastro de aluno. O preço é copiado do plano para o contrato da matrícula; a mensalidade mantém seu próprio valor em centavos.

1. **Cadastros e matrículas:** alunos com conta opcional, planos, matrícula com relacionamentos, vigência e dia de vencimento, validações, permissão administrativa, desativação/cancelamento e migração `20261110_01`.
2. **Mensalidades:** geração por competência, vencimentos em meses curtos, estados, unicidade no banco, baixa manual integral e migração `20261110_02`.
3. **API e interface:** rotas administrativas, formulários no painel, seleção do aluno e competência, geração, baixa, cancelamento e consulta de histórico. O transporte HTTP e a sessão existentes foram reaproveitados.

## Histórico e proteção das transações

- `audit_events` guarda entidade, ação, responsável, data UTC, motivo e snapshots anterior/posterior.
- `manual_payments` guarda cada recebimento com valor, data, administrador e observação, com vínculo único à mensalidade.
- Histórico e alterações são gravados na mesma transação. Falha na gravação do histórico reverte o pagamento e a alteração de estado.
- Os endpoints não permitem exclusão física nem alteração de eventos de histórico. Referências no banco usam `RESTRICT`; as conexões SQLite da aplicação habilitam chaves estrangeiras.
- SQLite serializa escritores com `BEGIN IMMEDIATE`; PostgreSQL utiliza bloqueios de linha. Autenticação e operações de negócio usam sessões distintas para evitar transações aninhadas involuntárias.
- O backend valida o valor integral e bloqueia transições inválidas. Uma corrida entre pagamento e cancelamento deixa apenas um estado terminal; a outra operação é recusada.
- Ao confirmar a baixa, o backend devolve `paga` e `completed=true`; o frontend apresenta **Concluída** apenas para aquela mensalidade do aluno selecionado.
- Repetições de geração, baixa e cancelamento não duplicam os registros correspondentes nem seus eventos.

O histórico é protegido pela API e pelas referências de banco, mas não é inviolável contra um administrador com acesso SQL direto. É necessário proteger o acesso e realizar backups.

## Arquivos

**Criados:**

- `backend/app/core/domain.py` e `dependencies.py`.
- `backend/app/modules/students/`, `plans/` e `enrollments/`: models, schemas, repositories, services, routers e inicializadores.
- `backend/app/modules/billing/`: modelos de mensalidade/recebimento, schemas, repository, service e router.
- `backend/app/modules/audit/`: modelo, gravação comum e consulta administrativa do histórico.
- `backend/migrations/versions/20261110_01_enrollments.py` e `20261110_02_monthly_fees.py`.
- `backend/tests/test_business.py`.
- `frontend/src/api/http.js`, `business.js`, `business.test.js` e `frontend/src/components/Management.jsx`.
- `frontend/e2e/business.spec.js` e `compose.business-tests.yaml`.
- `docs/MATRICULAS_MENSALIDADES.md` e este relatório.

**Alterados:**

- `backend/app/core/database.py`: fiscalização de FKs, sessão de negócio e transações.
- `backend/app/main.py`: registro das novas rotas e respostas administrativas sem cache.
- `backend/migrations/env.py`: imports dos novos models.
- `frontend/src/api/auth.js`: reutilização do transporte HTTP compartilhado.
- `frontend/src/auth/session.js` e `session.test.js`: requisições autenticadas com token privado, expiração e descarte de respostas após logout.
- `frontend/src/components/Dashboard.jsx` e `frontend/src/styles.css`: integração visual.
- `README.md`: descrição e links atualizados.
- `frontend/dist/`: bundle regenerado pelo build; não foi editado manualmente.

A revisão original de usuários foi preservada. Não houve alteração de segredos, seleção de provedor Pix, instalação de dependências ou mudança de configuração Celery/Redis da aplicação nesta implementação.

## Validação executada

| Verificação | Resultado |
| --- | --- |
| Backend, `pytest -m "not integration" -q --tb=short -p no:cacheprovider` | **105 passaram**, 2 testes existentes de infraestrutura excluídos pelo marcador |
| Casos de negócio incluídos no total | **42 passaram**, contando parametrizações |
| Ruff, `ruff check --no-cache app migrations tests` | **Passou** |
| Formatação com Ruff | Aplicada; arquivos Python formatados |
| Frontend, `npm test` | **24 passaram** |
| Frontend, `npm run build` | **Passou**, 37 módulos; JS ~245,30 kB (~76,35 kB gzip) |
| `node scripts/check-bundle.mjs`, executado na raiz | **Passou**, segredos configurados ausentes do bundle |
| Playwright, ambiente `academia-business-tests` | **9 passaram**: 8 de autenticação e 1 fluxo completo de negócio |

Os testes Python rodaram usando a imagem local existente `sistemadeacademia-tests`, com o código montado e sem rede. Os bancos das fixtures foram criados em diretórios temporários. Não foram instalados pacotes. A verificação de formatação utilizou a mesma ferramenta já presente nessa imagem.

O ambiente de navegador usou API real, SQLite próprio, Redis real e frontend com o código novo, em rede interna sem portas publicadas. O volume era exclusivo de `academia-business-tests`; não era o volume da aplicação. As credenciais descartáveis não foram exibidas. O ambiente foi encerrado e seu volume de teste removido ao concluir.

O build local inicialmente foi bloqueado pela restrição de leitura do sandbox; foi repetido com a permissão da ferramenta e passou. A primeira execução dos testes novos revelou que as identidades da fixture precisavam ser UUIDs, como exige a autenticação existente; a fixture foi corrigida e a suíte final passou integralmente.

Houve um aviso de depreciação do adaptador Starlette/TestClient sobre `httpx`, oriundo das dependências já instaladas. Nenhuma dependência foi atualizada nesta entrega.

## Cobertura relevante

- Permissões: sem token recebe 401; membro recebe 403 nas rotas de negócio.
- Valores inválidos, datas inconsistentes, cadastros inativos, conta opcional única e matrícula ativa duplicada.
- Valores contratados preservados após alteração do plano.
- Competências inválidas e fora da vigência, fevereiro, ano bissexto e meses de 30 dias.
- Valores fracionados impedidos diretamente no SQLite e restrições únicas/FKs verificadas com gravações reais.
- Geração repetida e concorrente, baixa repetida e concorrente, corrida entre pagamento e cancelamento.
- Pagamento de uma mensalidade não conclui a mensalidade de outro aluno.
- Falha simulada de histórico desfaz a baixa e o registro de pagamento.
- Estados terminais bloqueados, cancelamentos preservados e ausência de exclusão física via API.
- Migrações novas, equivalência de metadata e preservação dos usuários após downgrade/upgrade em banco descartável.
- Conversão de reais em centavos, paginação, mensagens seguras, token privado e respostas atrasadas após logout.
- Navegador: cadastro de dois alunos, plano, matrícula, emissão, valor incorreto recusado, recebimento correto, histórico, outro aluno pendente e largura móvel sem transbordamento da página.

## Pendências e limites

1. **Implantação no servidor atual:** não aplicada. Falta autorização específica para backup, migrações no banco principal e recriação dos contêineres. O endereço atual continua usando as imagens anteriores até essa implantação.
2. **PostgreSQL real:** os novos módulos precisam de validação nesse banco antes de uso financeiro. SQLite foi o banco testado nesta entrega. Os dois testes legados de saúde/worker não foram reexecutados; os testes de navegador verificaram API/SQLite/Redis reais, sem worker.
3. **Escopo futuro:** Pix, webhooks, conciliação externa, lembretes, emissão automática, proporcionalidade, descontos, juros, devoluções, edição de contratos e portal do aluno não fazem parte desta entrega.
4. **Estados e regras:** `vencida` é calculada pela data de Fortaleza; não há job de atualização diária. Cancelar matrícula não cancela obrigações já emitidas. Desativar aluno/plano não encerra contratos existentes. Competências com sobreposição parcial são integrais; um primeiro vencimento pode anteceder o dia de início dentro do mesmo mês.
5. **Operação:** SQLite possui um escritor por vez; sob carga maior poderá retornar 503. Listagens administrativas são paginadas na API e carregadas por páginas no frontend; pesquisa e paginação visual para cadastros grandes são melhorias futuras.
6. **Versionamento:** a pasta atual não possui metadados Git. Não foi possível produzir um diff ou commit Git; o inventário acima identifica o escopo da entrega.

Regras e contratos completos em [MATRICULAS_MENSALIDADES.md](MATRICULAS_MENSALIDADES.md).
