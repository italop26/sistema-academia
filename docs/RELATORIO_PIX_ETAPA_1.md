# Relatório — Pix simulado, etapa 1

Data: 10/11/2026, referência America/Fortaleza.

## Escopo autorizado e resultado

Somente a etapa 1 foi implementada: separação entre mensalidade, cobrança e pagamento; interface independente de provedor; simulador local identificado como teste; migração que preserva as baixas; serviço comum de liquidação e testes de compatibilidade. Não foi implementado webhook, instalado SDK, selecionado provedor real ou utilizado segredo de pagamento.

## Mudanças

| Arquivos | Resultado |
| --- | --- |
| `backend/app/modules/payments/models.py` | `Charge` separado de `Payment`; pagamento aplicado único por mensalidade; origem e valores validados no banco |
| `payments/providers.py` | Contrato `PixProvider` e adaptador `SimulatedPixProvider`, sem rede e sem código Pix pagável |
| `payments/{schemas,repositories,services,routers}.py` | Criação e leitura administrativas, chave idempotente e serviço de liquidação comum |
| `backend/app/modules/billing/{models,schemas,repositories,services}.py` e novo `presenters.py` | Reutilização da liquidação, compatibilidade do fluxo manual e identificação das simulações |
| `backend/app/modules/audit/{models,repositories,routers}.py` | Autoria de sistema distinta de administrador e histórico consultável de cobranças/pagamentos |
| `backend/app/core/config.py` e `.env.example` | Simulador desativado por padrão e bloqueado em produção |
| `backend/app/main.py` e `backend/migrations/env.py` | Registro das rotas e dos models novos |
| `backend/migrations/versions/20261110_03_pix_foundation.py` | Transfere baixas antigas sem mudar IDs ou dados históricos; preserva revisões anteriores |
| `backend/tests/test_pix_foundation.py` | 25 casos, contando parametrizações |
| `backend/tests/test_business.py` | Adaptação dos pontos de relógio/auditoria movidos, mantendo as verificações financeiras anteriores |
| `frontend/src/api/business.js`, `business.test.js` e `frontend/src/components/Management.jsx` | Rótulo explícito de conclusão simulada e exibição de autoria de sistema |
| `README.md`, `docs/MATRICULAS_MENSALIDADES.md`, `docs/PIX_SIMULADO.md` | Documentação atualizada; este relatório registra a entrega |

`ManualPayment` permanece apenas como alias Python para compatibilidade. Há uma única tabela de pagamentos aplicada aos canais. As referências históricas aos IDs antigos continuam válidas.

## Garantias verificadas

- Criar cobrança não quita mensalidade nem registra recebimento.
- Respostas do simulador incluem `is_simulated=true`, aviso de teste, referência `TEST-PIX-` e `payment_code=null`.
- Cliente não define valor, provedor ou indicador de simulação na criação da cobrança.
- Repetição de chave conserva cobrança e expiração; reuso incompatível é recusado.
- Baixa manual mantém campos, observação e responsável do contrato anterior.
- Valor, moeda, origem, estado e validade da cobrança são conferidos no serviço comum.
- Uma corrida entre baixa manual e liquidação simulada aplica somente um pagamento e gera apenas um evento de quitação.
- Pagamento simulado é identificado na resposta da mensalidade e no histórico, com autor `system`, sem usuário fictício.
- Falhas no histórico revertem cobrança ou liquidação inteira, incluindo pagamento e estado.
- Migração preserva dados antigos; downgrade recusa descartar cobranças ou registros automáticos.
- Não existe endpoint de webhook ou pagamento simulado nesta etapa. A entrada de liquidação simulada é interna, para testes da arquitetura comum.

## Testes e verificações executados

| Verificação | Resultado |
| --- | --- |
| `pytest tests/test_business.py -q -x --tb=short -p no:cacheprovider` | **42 passaram** — regressão financeira após a separação |
| Primeira suíte Pix, antes do caso adicional de rollback | **24 passaram** |
| Suíte final `pytest -m "not integration" -q --tb=short -p no:cacheprovider` | **130 passaram**, incluindo os **25 casos Pix**; 2 testes existentes de infraestrutura excluídos pelo marcador |
| Ruff `check --no-cache app migrations tests` | **Passou** |
| Ruff `format` | Aplicado aos arquivos Python |
| `npm test` | **24 passaram**, incluindo o rótulo de simulação |
| `npm run build` | **Passou** — 37 módulos, JS ~245,38 kB (~76,39 kB gzip) |
| `node scripts/check-bundle.mjs` | **Passou** — segredos configurados não encontrados no bundle |
| Playwright no ambiente `academia-business-tests` | **9 passaram** — autenticação, cadastro/matrícula, pagamento manual, histórico, isolamento por aluno e largura móvel |
| `git diff --check` | **Passou** para as alterações rastreadas |

O backend foi testado em contêiner com ferramentas já disponíveis, sem rede e com bancos temporários. O código foi montado somente leitura nas execuções de testes. As migrações foram exercitadas em SQLite temporário, incluindo downgrade/upgrade com recebimento anterior e comparação dos dados do histórico.

O navegador usou API real, SQLite e Redis próprios do ambiente descartável, sem portas públicas e sem volumes da academia. O simulador ficou desligado nessa regressão de navegador; o fluxo Pix desta etapa foi validado pelos testes Python, não por uma tela de cobrança Pix. O ambiente descartável foi encerrado e seu volume removido ao concluir.

Foi observado apenas o aviso já existente de depreciação Starlette/TestClient referente a `httpx`; dependências não foram alteradas. Na preparação do lint, imports e formatação foram ajustados e duas linhas SQL longas foram divididas; a execução final passou.

## Limites, riscos e pendências

1. **Banco principal e implantação:** não alterados. É necessária autorização específica para backup, migração e atualização dos contêineres do servidor atual.
2. **Etapa 2:** webhook autenticado de teste, armazenamento durável de eventos e reprocessamento ainda dependem de aprovação. Não há garantia de ingestão de eventos externos nesta etapa.
3. **Etapa 3:** matriz completa de eventos falsos, repetidos, atrasados e fora de ordem ainda depende de aprovação.
4. **Integração real:** inexistente. O protocolo atual é um ponto de extensão; segurança, referências, reconciliação e transporte reais dependerão do futuro provedor e de autorização própria.
5. **PostgreSQL:** models e bloqueios preservam o caminho existente, mas a validação desta etapa usou SQLite. É necessária validação com PostgreSQL real antes de uso financeiro nesse banco.
6. **Rollback:** a migração impede downgrade quando houver dados novos que o schema antigo não representa. Qualquer reversão após uso exige um plano que preserve esses dados. SQLite exige cuidado adicional com DDL e backup.
7. **Histórico:** proteção pela API, transações e FKs; não é inviolável contra operador com privilégios SQL diretos.
8. **Estado da pasta:** havia alterações anteriores, inclusive arquivos ainda não rastreados pelo Git. Foram preservadas; nenhum commit, reset ou limpeza dessas alterações foi feito.

Contrato e limites detalhados em [PIX_SIMULADO.md](PIX_SIMULADO.md). A etapa 1 está concluída; nenhuma etapa posterior foi iniciada.
