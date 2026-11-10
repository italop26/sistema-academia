# Relatório da revisão e integração

Data: 09/11/2026. Escopo: concluir a base local existente, integrar autenticação no React, verificar Docker e bancos e corrigir problemas encontrados. Não foram adicionados cadastros, agenda, pagamentos ou outros módulos de negócio.

## O que funciona e foi validado

- React acessa FastAPI por `/api`, encaminhado pelo proxy Vite para `backend:8000` no Docker. Consultas pelo proxy e pela API direta retornaram `status=ok`, banco `ok` e Redis `ok`.
- A tela de login valida os campos básicos, envia JSON à API, apresenta erros e impede envio duplicado durante carregamento. A senha é removida do campo ao enviar.
- O painel mostra somente identificação do administrador e conectividade técnica. O servidor exige usuário ativo e perfil `admin`; a conta `member` foi recusada com 403.
- O token fica em memória, sem localStorage, sessionStorage, cookies ou parâmetros de URL. Recarregar volta ao login. Os testes verificaram a ausência do token nos storages do navegador.
- A expiração encerra a sessão no React; o backend também recusou JWT expirado. O teste de expiração da interface usou relógio controlado do Chromium; o teste da API usou JWT com expiração passada real.
- Logout limpa a sessão local e revoga o identificador do JWT no Redis até sua expiração. O reaproveitamento desse token retornou 401 em HTTP real e no teste de navegador.
- Redis indisponível não libera autenticação por omissão: consultas autenticadas retornam 503. Se o logout remoto falhar, a interface permanece desconectada e informa que não houve confirmação do servidor.
- A sessão é revalidada ao voltar à aba e a cada minuto. Falha de comunicação oculta o painel até a nova validação, com opção de tentar novamente.
- Desktop e celular foram exercitados em Chromium; as capturas locais de login foram inspecionadas. Não houve rolagem horizontal na largura móvel testada de 390 px.

## Endpoints da autenticação

| Método | Endpoint | Regra |
| --- | --- | --- |
| POST | `/auth/login` | E-mail e senha válidos de usuário ativo |
| GET | `/auth/me` | JWT válido, não revogado, e usuário ativo |
| GET | `/auth/admin` | Mesmas verificações e perfil administrador |
| POST | `/auth/logout` | Autenticação válida; revoga o JWT e retorna 204 |

Os endpoints de saúde foram preservados. O bootstrap continua exclusivamente pela CLI interativa, sem cadastro público de administrador ou credenciais padrão.

## Resultados executados

| Verificação | Resultado observado |
| --- | --- |
| Backend: suíte completa com SQLite, Redis e worker reais | **65 passaram**, nenhum teste pulado |
| Variante PostgreSQL: saúde e execução de tarefa nativa do worker | **2 passaram**; são os mesmos dois cenários de infraestrutura, repetidos com outro banco |
| Frontend: testes do cliente HTTP e controlador de sessão | **18 passaram** |
| Chromium: fluxos completos e largura móvel | **8 passaram** |
| Smoke HTTP entre contêineres: login, me, admin, logout e replay | Aprovado |
| Health HTTP pela porta da API e pelo proxy React | Ambos retornaram banco e Redis `ok` |
| Migrações SQLite e PostgreSQL no projeto isolado | Aplicadas com sucesso |
| Alembic PostgreSQL: comparação de schema e metadata | Nenhuma operação nova detectada |
| Alembic SQLite: upgrade, downgrade e comparação nos testes | Aprovados |
| Upgrade Alembic no banco local configurado do Compose normal | Concluído com código zero |
| Imagens Docker normais: backend, frontend, migrate, worker, scheduler e tests | Construídas com sucesso |
| Build Vite de produção | Aprovado |
| Ruff: análise e formatação | Aprovadas, 39 arquivos Python formatados |
| `pip check` na imagem final | Nenhuma dependência incompatível |
| Auditoria automática npm durante instalação | Nenhuma vulnerabilidade conhecida reportada |
| Segredos configurados no bundle gerado | Nenhum dos valores procurados foi encontrado |
| Logs de backend, frontend, worker e scheduler após os testes | Sem os valores de segredos procurados ou JWTs completos |

A observação do Docker confirmou API, PostgreSQL e Redis saudáveis; worker e scheduler permaneceram ativos, e `migrate` terminou com código zero. O worker executou uma tarefa nativa do Celery e devolveu o resultado pelo Redis. O scheduler não possui automações de negócio; sua inicialização foi verificada, não a execução de agendas inexistentes.

Os testes com navegador cobriram: acesso anônimo ao login, login válido, painel administrativo, logout e replay negado, credenciais inválidas, perfil sem permissão, recarregamento, token expirado, expiração automática, rede indisponível, carregamento e largura móvel.

## Problemas corrigidos

1. O frontend anterior só consultava saúde. Foram adicionadas as telas de login e painel, preservando o estilo e sem métricas fictícias.
2. Não existia encerramento de sessão no React nem revogação no servidor. Agora há expiração e logout completo, com falha remota informada corretamente.
3. A permissão administrativa preparada no backend não era usada por uma tela. `/auth/admin` aplica `require_admin`, consultando o perfil atual no banco.
4. A primeira rodada dos testes novos carregou a cópia instalada do backend em vez dos fontes montados; cinco cenários falharam por executar código antigo. `pythonpath=["."]` no pytest corrige o caminho. A suíte foi repetida com os fontes atuais e passou.
5. O teste de logs evidenciou a necessidade de evitar caminhos brutos e logs HTTP de bibliotecas com URLs completas. A aplicação registra o template da rota ou `[unmatched]`; HTTPX/httpcore ficaram em WARNING. O teste de regressão verifica senha e JWT ausentes nas mensagens.
6. O verificador de logs inicialmente não podia ler as credenciais descartáveis, protegidas com modo 0600. A leitura de auditoria usa root apenas no contêiner isolado; os serviços da aplicação continuam sem privilégios. A verificação foi repetida com sucesso e inclui stdout e stderr.
7. As imagens do Compose normal também foram reconstruídas, evitando que a execução local use versões antigas após esta etapa.

Nenhuma senha, token ou chave foi incluída neste relatório. Usuários de teste, segredos e volumes são independentes dos dados da aplicação. A varredura comprova somente os valores e logs examinados, não uma garantia geral de ausência de vazamentos.

## Estado final e limites

O ambiente de validação é encerrado após a execução; seus volumes são preservados para permitir repetição. Nenhum usuário real foi criado ou alterado nesta etapa. O banco normal recebeu somente o upgrade Alembic solicitado.

Para usar a aplicação, inicie o Compose normal e cadastre seu administrador pela CLI, caso ainda não exista. As contas dos testes não servem para o ambiente normal. Consulte os comandos no README.

Resta um aviso de depreciação da Starlette sobre `httpx` no TestClient; os testes passam. O npm da imagem emitiu aviso de revisão do script de instalação do esbuild, mas o Vite foi inicializado no Docker e validado no navegador. Não houve falhas remanescentes nas verificações executadas.

Não foram verificados Firefox, Safari, publicação, TLS ou operação em produção. O Compose mantém a finalidade de desenvolvimento local. O login de navegador foi validado sobre SQLite; PostgreSQL teve migração, schema, conectividade e infraestrutura verificados, sem repetir toda a matriz de autenticação em PostgreSQL.

Capturas locais geradas pelos testes, ignoradas pelo Git: [login desktop](../frontend/test-results/login.png) e [login móvel](../frontend/test-results/login-mobile.png). Procedimento de repetição: [VALIDACAO.md](VALIDACAO.md).
