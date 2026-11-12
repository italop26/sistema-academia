# Relatório — Pix simulado, etapa 3

Data: 10/11/2026, referência America/Fortaleza. Etapas 2 e 3 autorizadas em conjunto, seguindo o fluxo simplificado sem nova fila ou automação.

## Resultado final

O webhook de testes foi integrado à caixa de entrada durável e ao serviço de quitação existente. A matriz adversarial verificou que falhas, eventos repetidos e eventos incompatíveis não geram uma segunda quitação. A apresentação no painel identifica explicitamente a simulação.

As evidências são de SQLite temporário, API real no ambiente isolado, Redis real no teste de navegador e contêineres sem os volumes da academia. Não houve implantação no banco principal, instalação de SDK ou dependências, seleção de provedor real ou uso de credenciais reais de pagamento.

## Testes e verificações

| Verificação | Resultado |
| --- | --- |
| Suíte básica da etapa 2, `tests/test_webhooks.py` | **10 passaram** |
| Primeira execução adversarial, antes dos casos adicionais | **47 passaram** |
| Matriz final `tests/test_webhook_adversarial.py`, incluída na suíte completa | **54 passaram**, contando parametrizações |
| Backend final, `pytest -m "not integration" -q --tb=short -p no:cacheprovider` | **194 passaram**, 2 testes legados de infraestrutura excluídos pelo marcador |
| Ruff, `check --no-cache app migrations tests` | **Passou** |
| Ruff, `format --check --no-cache app migrations tests` | **92 arquivos formatados**, passou |
| Frontend, `npm test` | **24 passaram** |
| Frontend, `npm run build` | **Passou**, 37 módulos |
| Playwright no projeto isolado `academia-business-tests` | **10 passaram**, nenhum teste pulado nesse ambiente |
| `node scripts/check-bundle.mjs` | **Passou** para os segredos configurados |
| `git diff --check` | **Passou** para os arquivos rastreados |

Os testes Python usaram a imagem local de ferramentas existente, código montado somente leitura e rede desativada. Todas as migrações da suíte foram aplicadas a bancos descartáveis. Ruff foi utilizado antes da execução final para organizar imports e formatação; nenhuma regra foi suprimida.

O ambiente de navegador utilizou segredo exclusivo e conhecido de teste apenas no backend e no processo Node do teste. O Vite/frontend não recebeu esse segredo. Não foram publicadas portas; o banco e a rede eram próprios do projeto descartável. O ambiente e seu volume foram removidos ao concluir.

Foi observado somente o aviso preexistente de depreciação do Starlette/TestClient sobre `httpx`. As dependências permaneceram como estavam.

## Matriz coberta

| Grupo | Evidência verificada |
| --- | --- |
| Autenticação | Assinatura falsa/ausente, corpo alterado depois da assinatura, timestamp inválido, antigo ou futuro |
| Parsing e contrato | JSON malformado, chaves duplicadas, UTF-8 inválido, constantes não finitas, corpo acima do limite, campos extras, versão/tipos/valores inválidos e data sem fuso |
| Referência e cliente | Cobrança desconhecida, referência divergente e tentativa de aplicar a mesma referência de pagamento a outro aluno |
| Valor e moeda | Valor diferente e moeda incompatível permanecem registrados sem quitação |
| Datas | Ocorrência anterior à criação, ocorrência futura, pagamento após expiração e entrega tardia para cobrança ainda não paga |
| Ordem dos eventos | Pendência/cancelamento depois de confirmação não desfazem pagamento; confirmação depois de cancelamento não reabre cobrança |
| Idempotência | Mesmo ID/conteúdo, mesmo conteúdo com outra formatação e novo ID para o mesmo recebimento não duplicam quitação |
| Conflitos | Mesmo ID com conteúdo diferente conserva o original e registra a divergência; outro recebimento para a mesma mensalidade é recusado |
| Concorrência | Entregas simultâneas com mesmo ID ou IDs diferentes e corrida entre baixa manual e webhook deixam um único pagamento aplicado |
| Falhas | Falha financeira/auditoria reverte os efeitos; falha na persistência inicial não aplica pagamento; falha ao registrar o próprio erro conserva evento recebido para recuperação |
| Recuperação | Interrupção entre receber/processar, nova tentativa administrativa com motivo e conservação do histórico da falha |
| Permissões | Ausência de JWT e perfil membro não consultam/reprocessam eventos; estados terminais não permitem nova tentativa |
| Segredos | Segredo exclusivo e com comprimento mínimo; conteúdo não aparece no payload persistido, respostas ou logs verificados |
| Migrações | Metadata confere com o schema; downgrade não descarta eventos existentes |

O teste `frontend/e2e/pix.spec.js` criou uma cobrança simulada por HTTP, assinou o evento com `node:crypto`, confirmou a mensalidade, repetiu a entrega, verificou uma única tentativa de processamento e mostrou **Concluída (simulação)** no painel. A ação de baixa manual deixou de ser oferecida para essa mensalidade. Os nove testes anteriores de navegador continuaram passando.

## Arquivos envolvidos nas etapas 2 e 3

**Novos:**

- `backend/app/modules/webhooks/__init__.py`, `auth.py`, `models.py`, `schemas.py`, `repositories.py`, `services.py`, `routers.py`.
- `backend/migrations/versions/20261110_04_webhook_events.py`.
- `backend/tests/test_webhooks.py` e `test_webhook_adversarial.py`.
- `frontend/e2e/pix.spec.js`.
- `docs/WEBHOOKS_PIX_SIMULADOS.md`, `RELATORIO_PIX_ETAPA_2.md` e este relatório.

**Atualizados:**

- `backend/app/core/config.py` e `.env.example`: segredo exclusivo do webhook de teste, sem editar o `.env` atual.
- `backend/app/main.py` e `backend/migrations/env.py`: rotas, política de cache e registro do model de eventos.
- `backend/app/modules/audit/routers.py`: consulta do histórico de `webhook_event`.
- `backend/app/modules/payments/schemas.py` e `services.py`: descrição da entrada interna atualizada; regras de quitação existentes reaproveitadas.
- `compose.business-tests.yaml`: habilitação e segredo apenas no ambiente de testes; o frontend não recebe a variável.
- `scripts/check-bundle.mjs`: inclui o novo segredo na verificação quando configurado.
- `README.md`, `docs/PIX_SIMULADO.md` e `MATRICULAS_MENSALIDADES.md`: contratos e situação atual.

As alterações anteriores da pasta foram preservadas. Não houve commit, reset ou limpeza de arquivos do usuário.

## Decisões e limites

1. **Simplicidade:** processamento síncrono após persistência. Sem Celery/outbox ou nova infraestrutura. Consultar eventos `received`/`failed` e repetir administrativamente é responsabilidade operacional nesta versão.
2. **Confirmação HTTP:** 200 significa processado/ignorado; 202 significa evento guardado que exige análise ou nova tentativa, não pagamento concluído. Rejeições de negócio não são editadas ou reaplicadas administrativamente como se fossem falhas técnicas.
3. **Atrasos:** o simulador não liquida automaticamente cobrança expirada/cancelada ainda não paga, mesmo que o evento seja autenticado. A evidência é guardada. Política de liquidação tardia e devolução real dependerá do futuro provedor.
4. **Garantia financeira:** existe no máximo um pagamento aplicado por mensalidade nos testes e nas restrições. Isso não pretende esconder ou descartar recebimentos adicionais de um banco real; uma integração real precisará de conciliação e tratamento desses recebimentos.
5. **Extensão:** autenticação/parsing de testes estão isolados em `webhooks/auth.py`/`schemas.py`; regras de recebimento e liquidação são separadas. Um futuro adaptador deverá traduzir o contrato real e implementar autenticação, estados, referências e regras reais. Não é uma mudança de rótulo ou simples habilitação de uma flag.
6. **Produção e banco:** o simulador permanece desativado por padrão e bloqueado em produção. As migrações não foram aplicadas ao banco principal; contêineres atuais não foram atualizados. Implantação exige autorização própria e backup.
7. **PostgreSQL:** a arquitetura existente foi mantida, mas esta validação usa SQLite. PostgreSQL real precisa de uma rodada própria antes de operação financeira.
8. **Histórico:** a API não permite apagar ou alterar eventos. O downgrade da nova revisão recusa descartar eventos existentes. Operadores com acesso SQL privilegiado ainda precisam de controle de acesso e backup.

As duas etapas autorizadas estão concluídas. Contrato de uso em [WEBHOOKS_PIX_SIMULADOS.md](WEBHOOKS_PIX_SIMULADOS.md).
