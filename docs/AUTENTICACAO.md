# Usuários e autenticação

Usuários, bootstrap do administrador, login, painel administrativo e logout. A arquitetura de routers, services, repositories, models e schemas foi mantida. `AuthService` reutiliza `UserRepository` e `TokenRepository` armazena revogações no Redis; não há endpoints de gerenciamento de usuários.

## Banco e migração

Na raiz:

```sh
node scripts/setup-env.mjs --sqlite
docker compose build backend tests
docker compose run --rm --no-deps migrate
```

`--sqlite` seleciona o arquivo `./data/academia.db` relativo à pasta de execução do backend. No Docker, corresponde a `/app/data/academia.db`, persistido em `sqlite_data`; fora do Docker, executando em `backend/`, corresponde a `backend/data/academia.db`. São arquivos separados. Execute a CLI no mesmo ambiente em que roda sua API.

O script mantém senhas existentes e gera `JWT_SECRET_KEY` quando ausente. Sem `--sqlite`, mantém a seleção de banco existente. Sem `DATABASE_URL`, a aplicação continua usando as variáveis `POSTGRES_*`. A troca de URL não copia dados entre bancos. Para uma URL SQLite personalizada, crie previamente a pasta de destino e garanta acesso de escrita ao usuário da aplicação.

A revisão Alembic `20261109_01` cria `users`: ID UUID, nome, e-mail único, hash da senha, perfil (`admin` ou `member`), estado ativo e criação em UTC. O perfil `member` está reservado para uso futuro; não existe fluxo público de cadastro.

## Administrador inicial

Em terminal interativo, na raiz:

```sh
docker compose run --rm --no-deps backend python -m app.modules.users.cli --name "Seu nome" --email "seu.email@exemplo.com"
```

Em execução local, depois de ativar o virtualenv e entrar em `backend/`:

```sh
python -m app.modules.users.cli --name "Seu nome" --email "seu.email@exemplo.com"
```

A senha tem de 12 a 128 caracteres e é digitada duas vezes sem eco. Prefira uma frase longa e exclusiva. O comando não aceita senha por argumento, não imprime senha ou hash e recusa entrada não interativa. Não use `-T` no Compose nem encaminhe a senha por pipe.

O bootstrap usa transação e bloqueio para evitar dois administradores iniciais em execuções simultâneas. Recusa uma nova execução se já existir qualquer administrador, inclusive inativo. Não cria tabelas: aplique a migração antes. Nenhum administrador ou senha padrão é criado automaticamente.

## Contratos HTTP

### `POST /auth/login`

Envie JSON com `email` e `password`. O e-mail é validado, tem espaços externos removidos e é normalizado para minúsculas. Campos extras, inclusive `role`, são rejeitados. A senha não é normalizada nem tem espaços removidos.

Resposta 200:

```json
{
  "access_token": "<JWT>",
  "token_type": "bearer",
  "expires_in": 900
}
```

E-mail desconhecido, senha incorreta e usuário inativo retornam 401 com a mesma mensagem. A verificação executa um hash de comparação também quando o e-mail não existe. Entradas inválidas retornam 422 sem repetir o conteúdo recebido.

### `GET /auth/me`

Envie `Authorization: Bearer <JWT>`. Retorna somente `id`, `name`, `email`, `role`, `is_active` e `created_at`. Nunca retorna senha ou hash.

Token ausente, malformado, expirado, assinado com outra chave ou pertencente a usuário inexistente/inativo retorna 401 com `WWW-Authenticate: Bearer`. O estado do usuário é consultado no banco em cada acesso; desativar o usuário bloqueia o token já emitido.

Erros seguem o formato existente:

```json
{
  "error": {
    "code": "unauthorized",
    "message": "Autenticação necessária ou token inválido.",
    "request_id": "<identificador>"
  }
}
```

Respostas de autenticação usam `Cache-Control: no-store`. O esquema Bearer está disponível no botão **Authorize** da documentação `/docs`; o login recebe JSON, não formulário OAuth2.

## Segurança e permissões

`GET /auth/admin` retorna o perfil público do administrador autenticado e recusa outros perfis com 403. `POST /auth/logout`, autenticado, retorna 204 e grava `auth:revoked:<jti>` no Redis com expiração absoluta igual à do JWT. Tokens revogados são recusados por `/auth/me` e `/auth/admin`. Falhas ao consultar ou gravar revogações retornam 503; não são tratadas como autenticação válida ou logout confirmado.

No React, o token existe somente em memória, sem localStorage, sessionStorage, cookies ou URLs. Recarregar exige novo login. A sessão expira por timer e também é conferida ao voltar à aba. A autorização é revalidada no servidor a cada minuto; falhas de comunicação ocultam o painel e permitem tentar novamente. O logout limpa a memória imediatamente; se o servidor não confirmar a revogação, isso é informado na tela.

- Senhas usam Argon2id, por `pwdlib`, com salt aleatório.
- JWT usa HS256 fixo e exige assinatura válida, `sub`, `iat`, `exp`, `iss`, `aud`, `jti` e `token_type=access`. O ID do usuário é validado como UUID. Perfis não são obtidos de declarações do token.
- `JWT_SECRET_KEY` é obrigatório, sem valor padrão, com mínimo de 32 caracteres. O script gera um segredo aleatório. Trocar a chave invalida todos os tokens anteriores; não exponha essa chave em variáveis `VITE_*`.
- `JWT_ACCESS_TOKEN_MINUTES` aceita de 1 a 60, com padrão 15. `JWT_ISSUER` e `JWT_AUDIENCE` têm os padrões `academia-api` e `academia-client`.
- `get_current_user` exige identidade ativa e token não revogado. `require_admin` exige perfil atual `admin` e retorna 403 para outro perfil; está aplicado em `/auth/admin`.
- Não há cadastro público, refresh token, recuperação de senha, MFA, bloqueio por tentativas ou gestão de usuários nesta etapa. Antes de exposição pública, defina a política de proteção contra tentativas de login e use HTTPS.

Implementação baseada nas referências oficiais de [segurança do FastAPI](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/), [validação JWT](https://pyjwt.readthedocs.io/en/stable/api.html) e [SQLite no SQLAlchemy](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html).

## Verificação

```sh
docker compose build tests
docker compose run --rm --no-deps tests pytest -m "not integration" -q
docker compose run --rm --no-deps tests ruff check app migrations tests
docker compose run --rm --no-deps tests ruff format --check app migrations tests
docker compose run --rm --no-deps tests pip check
```

Os testes de autenticação usam SQLite real em arquivos temporários, aplicando a migração Alembic antes de cada cenário. Incluem login, credenciais inválidas, tokens rejeitados, permissões, usuário desativado/excluído, hash, bootstrap e concorrência, além de upgrade, downgrade e comparação entre migração e metadata.
