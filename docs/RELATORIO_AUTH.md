# Relatório de usuários e autenticação

Registro da etapa anterior. O estado atual, incluindo integração React, logout e testes completos, está em [RELATORIO_FINAL.md](RELATORIO_FINAL.md).

## Escopo entregue

- Módulo `users`: model SQLAlchemy, repository, service, schemas e comando de bootstrap.
- Módulo `auth`: router, service, schemas e dependências de autenticação/autorização. O acesso aos usuários reutiliza `UserRepository`.
- Migração `20261109_01` cria a tabela `users`, e-mail único e restrição de perfil.
- Suporte configurável a SQLite ou PostgreSQL pela mesma camada de persistência. O `.env` local foi preparado para SQLite; os valores PostgreSQL anteriores foram preservados.
- Script de ambiente gera a chave JWT e segredos ausentes sem imprimir valores ou substituir senhas já configuradas. O uso posterior sem alterações preservou o arquivo.
- Volume Docker `sqlite_data` compartilhado pelos serviços do backend. Diretório de dados gravável pelo usuário sem privilégios da imagem de execução.
- Ajustes de CORS para POST e header Authorization; erros de autenticação seguem o padrão existente e não repetem dados enviados.
- README e documentação de contratos, migrações, bootstrap e permissões atualizados.

Não houve alterações funcionais no frontend, nem endpoints de cadastro público, gestão de usuários, recuperação de senha ou outras funcionalidades de negócio.

## Endpoints

| Método | Endpoint | Comportamento |
| --- | --- | --- |
| POST | `/auth/login` | Valida e-mail e senha em JSON, verifica usuário ativo e retorna JWT Bearer com expiração |
| GET | `/auth/me` | Exige JWT válido e usuário ativo; retorna apenas dados públicos |

Os endpoints de saúde existentes foram preservados. A verificação de banco agora usa a conexão configurada, incluindo SQLite.

## Controles implementados

Senhas usam Argon2id com salt aleatório. Não existe credencial padrão. A CLI solicita senha e confirmação sem eco e não aceita senha por argumento ou entrada não interativa. O cadastro inicial é transacional e bloqueia a criação de outro administrador inicial, inclusive em concorrência.

JWT usa HS256 fixo, assinatura com chave de ambiente e expiração padrão de 15 minutos. Valida emissor, destinatário, emissão, expiração, identificador e tipo de token. O perfil e o estado ativo são consultados no banco; o token não fornece permissões por conta própria. A dependência `require_admin` retorna 403 para perfil insuficiente, sem criar um endpoint administrativo extra.

Respostas 401 são genéricas para e-mail desconhecido, senha incorreta ou usuário inativo. Tokens ausentes ou rejeitados retornam 401 com `WWW-Authenticate: Bearer`. Respostas de autenticação usam `Cache-Control: no-store`. Dados inválidos retornam 422 sem repetir senha ou outros valores recebidos.

## Verificações

| Verificação | Resultado |
| --- | --- |
| Pytest, excluindo os dois testes externos de infraestrutura | **58 passaram**, 2 deselecionados |
| SQLite real com migração antes de cada cenário de autenticação | Aprovado |
| Login, credenciais inválidas e acesso sem autorização | Aprovados |
| Tokens expirados, assinatura/algoritmo incorretos, claims ausentes ou inválidas | Aprovados |
| Usuário inativo, excluído e alteração de perfil após emitir token | Aprovados |
| Hash Argon2id, salt aleatório e hash persistido inválido | Aprovados |
| E-mail único no banco | Aprovado |
| CLI, confirmação de senha e bloqueio de administrador duplicado | Aprovados |
| Dois bootstraps concorrentes | Apenas um administrador criado |
| Alembic: upgrade, downgrade, novo upgrade e comparação com metadata | Aprovados em SQLite temporário |
| Ruff: análise estática | Aprovada |
| Ruff: formatação | Aprovada, 36 arquivos |
| Compose: `config --quiet` | Aprovado |
| Build das imagens Docker de execução e testes | Aprovado |
| `pip check` na imagem final de testes | Nenhuma dependência incompatível |
| Migração no SQLite persistente, pelo usuário sem privilégios da imagem | Aplicada: `20261109_01` |
| Leitura posterior do volume por outro contêiner da API | Banco SQLite, revisão `20261109_01`, 0 usuários |
| Script de ambiente: sintaxe e execução posterior sem alterações | Aprovados |

O aviso inicial de separação de caminhos do Alembic foi corrigido com `path_separator=os` e requisito Alembic 1.16+. Resta um aviso de depreciação da Starlette sobre `httpx` no TestClient. Nenhum teste falhou na rodada final.

As verificações Python foram executadas em Docker, pois não há Python acessível no host. Nenhuma senha ou token de usuário real foi definido ou impresso; os usuários dos testes existem somente em arquivos temporários.

## Estado da execução

As imagens de execução e testes foram construídas. A migração foi aplicada ao volume Docker `sqlite_data`; uma leitura posterior por outro contêiner confirmou SQLite, revisão `20261109_01` e zero usuários. O banco está preparado, mas o administrador real ainda precisa ser criado com suas próprias credenciais:

```sh
docker compose run --rm --no-deps backend python -m app.modules.users.cli --name "Seu nome" --email "seu.email@exemplo.com"
```

Nenhum serviço contínuo da stack foi iniciado nesta etapa. As verificações usaram contêineres temporários removidos ao terminar. Os dois testes externos de saúde/worker não foram reexecutados; não houve validação desta etapa com PostgreSQL, Redis ou worker reais. A autenticação foi validada com FastAPI TestClient e SQLite real. O frontend não foi alterado nem testado novamente.

Não há falhas de implementação conhecidas nas verificações realizadas. Permanece o aviso de depreciação do TestClient, sem impacto no resultado dos testes.
