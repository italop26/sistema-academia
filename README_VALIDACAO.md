# Guia pessoal de uso e validação — Academia/Pilates

Este é o guia para entender o sistema, executar comandos e validar cada entrega. A apresentação pública fica no [README.md](README.md).

## Situação desta rodada — 12/11/2026

| Parte | Entrega | Verificação registrada |
| --- | --- | --- |
| Etapa 1 | Presença diária, histórico, última visita e suspensão/retomada | 59 testes de backend e 13 de navegador passaram |
| Etapa 2 | Detecção após 240 horas, carência inicial, lotes e recuperação | 27 testes de ausência/configuração passaram |
| Etapa 3 | Fila simples com quatro estados e retorno por check-in | 13 casos novos de backend e fluxo completo de navegador passaram |

Esses totais são das rodadas por etapa e têm sobreposição; não devem ser somados como testes distintos. A regressão final passou com **269 testes de backend + 2 de infraestrutura = 271 casos distintos**, **24 testes JavaScript** e **14 testes de navegador**, sem testes de navegador pulados. Build, Ruff, formatação e verificação dos segredos configurados no bundle passaram.

**As novas migrações ainda não foram aplicadas ao banco principal.** Até uma implantação autorizada, o endereço local pode continuar mostrando a versão anterior. Nesta rodada, todos os dados de validação ficam em SQLite descartável.

## O que cada coisa significa

- **Usuário** é a conta que entra no sistema. **Aluno** é o cadastro atendido pela academia; não precisa ter conta.
- **Plano** define o preço oferecido. **Matrícula** guarda o contrato do aluno e seu preço próprio.
- **Mensalidade** é a obrigação de uma competência, por exemplo `2026-11`. Gerar cobrança ou registrar presença não significa receber dinheiro.
- **Presença/check-in** confirma que o aluno compareceu naquele dia.
- **Ausência** é um episódio de 240 horas sem presença, durante elegibilidade contínua.
- **Acompanhamento** registra o trabalho administrativo sobre esse episódio. Não é mensagem enviada ao aluno.
- **Celery worker** executa tarefas. **Beat/scheduler** agenda as verificações. **Redis** transporta tarefas. O histórico definitivo fica no **SQLite**.

## Terminal e ambiente virtual

Abra o PowerShell na raiz do projeto. Para ativar o ambiente já existente:

```powershell
.\backend\.venv\Scripts\Activate.ps1
```

Se ainda não existir, crie uma vez e depois ative:

```powershell
python -m venv backend\.venv
.\backend\.venv\Scripts\Activate.ps1
```

Se o PowerShell bloquear a ativação, você pode executar o Python do ambiente diretamente, sem mudar políticas do Windows:

```powershell
.\backend\.venv\Scripts\python.exe --version
```

Instalação do Alembic que foi mostrada na conversa, com o ambiente ativado:

```powershell
python -m pip install "alembic>=1.16,<2"
python -m alembic --version
```

Esse comando instala somente Alembic. Para desenvolvimento local completo, a instalação das dependências do projeto é:

```powershell
Set-Location backend
python -m pip install -e ".[dev]"
```

Os comandos acima são instruções para você usar quando precisar; nenhuma dependência foi instalada nesta rodada pelo agente.

## Como validar a etapa 1

No ambiente descartável, crie um aluno, um plano e uma matrícula vigente. No painel **Frequência dos alunos**, atualize a lista se o aluno acabou de ser criado e selecione o aluno/matrícula.

1. Registre presença: total aumenta para 1 e última visita recebe o horário atual.
2. Clique novamente: continua 1 no mesmo dia de Fortaleza.
3. Abra suspensão, informe motivo e confirme: novas presenças ficam bloqueadas.
4. Retome com motivo: a presença fica disponível novamente, mas a repetição no mesmo dia ainda conserva o registro original.
5. Confira os históricos de presenças e suspensões. A suspensão não cancela nem quita mensalidades.

Uma matrícula cancelada, fora da vigência ou pertencente a outro aluno não pode registrar presença. O horário é definido pelo servidor; não há lançamento retroativo nesta versão.

## Como validar a etapa 2

O limite é de **240 horas completas**, e não apenas dez mudanças de data. Antes desse limite não deve haver detecção; no limite ou depois dele, o aluno elegível poderá aparecer na fila na próxima varredura.

- Sem qualquer check-in: a contagem usa o início elegível ou a primeira ativação do acompanhamento, o mais recente. Cadastros antigos recebem carência inicial.
- Todas as matrículas suspensas: não há detecção; a retomada reinicia a contagem.
- Uma matrícula suspensa e outra disponível: o aluno continua elegível.
- Aluno inativo, sem matrícula vigente ou com todas canceladas: não recebe nova detecção.
- Verificações repetidas conservam um único caso por episódio.

**Não altere datas do banco principal para simular dez dias.** Os testes automatizados usam relógio controlado; o probe operacional acelera datas somente no SQLite descartável e verifica essa condição antes de escrever.

## Como validar a etapa 3

Fluxo esperado: **Pendente → Em acompanhamento → Resolvido ou Encerrado**. Também é possível devolver um caso em acompanhamento para pendente.

- Assumir acompanhamento registra você como responsável e exige observação.
- Resolver ou encerrar exige observação. Casos finalizados não são reabertos automaticamente pelo mesmo episódio.
- Novo check-in resolve o caso aberto na mesma transação da presença.
- Histórico conserva as mudanças; uma tela desatualizada não pode sobrescrever o estado atual.
- Perda de elegibilidade encerra o caso na próxima varredura.

## Testar sem mexer no banco principal

Execute os comandos desta seção **a partir da raiz do projeto**. O projeto Docker `academia-attendance-tests` usa SQLite, Redis, volume e rede próprios, sem portas públicas. A palavra `tests` no nome é importante: não troque pelo projeto principal.

As imagens de ferramentas precisam existir. Se ainda não existirem, estes comandos as constroem; a construção instala as dependências definidas pelo projeto dentro das imagens:

```powershell
docker compose -p sistemadeacademia build tests
docker build -f frontend/Dockerfile.e2e -t academia-validation-e2e frontend
```

Nesta rodada as imagens existentes foram reutilizadas, sem instalar dependências.

Inicie o ambiente isolado:

```powershell
docker compose -p academia-attendance-tests -f compose.business-tests.yaml up -d redis backend worker scheduler frontend
```

Se mudou código Python desde a última execução, recarregue os processos de teste:

```powershell
docker compose -p academia-attendance-tests -f compose.business-tests.yaml up -d --force-recreate backend worker scheduler frontend
```

Não é preciso abrir um endereço no navegador: os testes Chromium acessam o frontend pela rede interna.

### Backend e infraestrutura

Regressão de backend com bancos temporários independentes:

```powershell
docker compose -p academia-attendance-tests -f compose.business-tests.yaml run --rm --no-deps automation-checks pytest -m "not integration" -q -p no:cacheprovider
```

Resultado desta entrega: **269 passaram**; os dois testes de infraestrutura ficam separados pelo marcador.

Integração com SQLite, Redis e worker reais:

```powershell
docker compose -p academia-attendance-tests -f compose.business-tests.yaml run --rm --no-deps --env RUN_INTEGRATION_TESTS=1 automation-checks pytest tests/test_integration.py -q -p no:cacheprovider
```

Resultado: **2 passaram**. O aviso Starlette/TestClient sobre `httpx` continua aparecendo; não impediu os testes.

Para executar somente as regras novas:

```powershell
docker compose -p academia-attendance-tests -f compose.business-tests.yaml run --rm --no-deps automation-checks pytest tests/test_attendance.py tests/test_absence.py tests/test_followups.py -q -p no:cacheprovider
```

Resultado da rodada por módulo: **48 passaram**, contando parametrizações. Esses casos já estão dentro dos 269 da regressão; não some de novo.

### Ausência real no worker e navegador

Prepare os três casos descartáveis e aguarde a criação pelo Beat/worker:

```powershell
docker compose -p academia-attendance-tests -f compose.business-tests.yaml run --rm --no-deps automation-checks python tests/absence_runtime_check.py
```

Resultado esperado: `PASSOU: Beat e worker reais criaram três detecções de ausência no SQLite descartável.` O probe acelera datas somente nesse banco. O Beat de teste usa um segundo; a configuração normal continua sendo cinco minutos. Nenhuma espera de dez dias reais é necessária para essa validação.

Depois execute a suíte de navegador completa:

```powershell
docker compose -p academia-attendance-tests -f compose.business-tests.yaml run --rm --no-deps --env ABSENCE_RUNTIME_TESTS=1 e2e
```

Resultado desta entrega: **14 passaram**. O teste da fila assume um caso, registra observação, consulta histórico, resolve pelo check-in e valida também encerramento e resolução manual.

**Antes de repetir essa suíte completa, execute o probe novamente.** Ele prepara novos casos porque o teste anterior já finalizou os anteriores. Sem `ABSENCE_RUNTIME_TESTS=1`, esse fluxo específico fica pulado; os outros testes continuam disponíveis.

### Frontend e análise estática

Na pasta `frontend`, com dependências já instaladas:

```powershell
npm test
npm run build
```

Na raiz, para verificar o bundle gerado:

```powershell
node scripts/check-bundle.mjs
```

Esse verificador procura somente os segredos configurados; não representa uma auditoria completa de vazamentos.

Análise estática do backend, na raiz:

```powershell
docker compose -p academia-attendance-tests -f compose.business-tests.yaml run --rm --no-deps automation-checks ruff check --no-cache app migrations tests
docker compose -p academia-attendance-tests -f compose.business-tests.yaml run --rm --no-deps automation-checks ruff format --check --no-cache app migrations tests
```

### Encerrar os testes

```powershell
docker compose -p academia-attendance-tests -f compose.business-tests.yaml stop
```

Esse comando para os serviços e preserva os volumes de teste. Não remove o banco principal nem seus contêineres. Foi o encerramento usado nesta entrega.

## Entender Alembic e os bancos

Ative o ambiente virtual e execute os comandos Python a partir de `backend`, para que a configuração encontre o `.env` da raiz.

| Comando | O que faz |
| --- | --- |
| `python -m alembic --version` | Confere se Alembic está instalado nesse Python |
| `python -m alembic history` | Lista o encadeamento das revisões |
| `python -m alembic current` | Consulta a revisão do banco selecionado pela configuração |
| `python -m alembic check` | Compara schema e models; não aplica uma revisão |
| `python -m alembic upgrade head` | Aplica as migrações pendentes; altera o banco selecionado |

As novas revisões são `20261112_01` (presença/suspensão), `20261112_02` (ausência) e `20261112_03` (acompanhamento). Elas foram testadas em SQLite descartável e em cópia temporária de um backup já existente. **Não foram aplicadas ao banco principal nesta entrega.** Esse ensaio não substitui um backup atualizado antes de uma futura implantação.

Há três contextos que você precisa distinguir:

- **Python local em `backend`**: uma URL SQLite relativa usa o arquivo em `backend/data`.
- **Docker principal**: a mesma URL relativa aponta para o arquivo no volume `sistemadeacademia_sqlite_data`.
- **Docker de testes**: usa `validation.db` no volume separado de `academia-attendance-tests`.

Esses arquivos não são sincronizados automaticamente. Consultar uma revisão no Python local não comprova a revisão do banco do Docker.

Para consultar a revisão do Docker principal, sem aplicar migrações:

```powershell
docker compose -p sistemadeacademia exec -T backend alembic current
```

Não execute `upgrade head` ou `up --build` no projeto principal durante uma simples validação: o Compose principal aplica migrações na inicialização. A implantação deve ter autorização específica e backup atualizado.

## Usar o ambiente principal depois de uma implantação autorizada

Interface: **http://localhost:5174**. Contratos da API: **http://localhost:8002/docs**.

Se ainda não houver administrador, crie pelo terminal interativo, com seus dados:

```powershell
docker compose -p sistemadeacademia run --rm --no-deps backend python -m app.modules.users.cli --name "Seu nome" --email "seu.email@exemplo.com"
```

A senha será solicitada duas vezes, sem exibição. As contas descartáveis de teste não servem para o ambiente principal.

Para conferir processos:

```powershell
docker compose -p sistemadeacademia ps -a
```

`migrate` encerrar com código zero é esperado. Redis saudável não comprova que o worker executou tarefas; a evidência de negócio está nas execuções e no histórico do painel.

Para desenvolvimento sem contêiner de backend, mantenha Redis disponível e, a partir de `backend`, execute:

```powershell
python -m uvicorn app.main:app --reload --port 8002
```

Use apenas um backend na porta 8002 de cada vez. Em outro terminal, na pasta `frontend`:

```powershell
npm run dev
```

As tabelas do banco local precisam estar migradas antes de usar os módulos. Worker e scheduler continuam sendo executados pelo Docker no fluxo Windows já adotado pelo projeto.

## Dúvidas comuns na validação

- **Recarreguei e voltei ao login:** o token fica somente em memória. Esse é o comportamento atual.
- **Coloquei início da matrícula no mês passado e não apareceu ausência:** a criação efetiva da matrícula e a carência da ativação também são consideradas. A data contratual antiga, sozinha, não gera alerta imediato.
- **O caso já foi resolvido e continua na lista:** selecione o filtro desejado; casos finalizados ficam no histórico.
- **Resolveu manualmente e não gerou outro alerta no dia seguinte:** é o mesmo episódio. Nova presença ou reinício da elegibilidade poderá iniciar outra contagem.
- **A suspensão não apagou a mensalidade:** suspensão de frequência preserva as obrigações financeiras existentes.
- **Os novos painéis não aparecem em localhost:** esta rodada atualizou os fontes e o ambiente descartável. A versão principal só muda após implantação autorizada.

## Registro desta entrega

- Etapas 1, 2 e 3 implementadas e testadas.
- Sem instalação de dependências, atualização do banco principal, commit, push ou deploy nesta rodada.
- Banco e regras financeiras anteriores preservados.
- Ambiente descartável encerrado com `stop`, volumes preservados.
- [Etapa 1](docs/RELATORIO_FREQUENCIA_ETAPA_1.md), [etapa 2](docs/RELATORIO_FREQUENCIA_ETAPA_2.md) e [etapa 3 / fechamento](docs/RELATORIO_FREQUENCIA_ETAPA_3.md).
- [Evidência do Beat/worker](docs/EVIDENCIAS/2026-11-12-frequencia-runtime.json).

A cada nova parte do desenvolvimento, este guia deve registrar o comportamento entregue, como validar, o resultado esperado e o que ainda não foi aplicado ao ambiente principal. O README público deve acompanhar o funcionamento atual dos fontes.
