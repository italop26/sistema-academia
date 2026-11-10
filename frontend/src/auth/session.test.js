import assert from 'node:assert/strict';
import test from 'node:test';
import { createSession } from './session.js';

function fixture(overrides = {}) {
  let time = 1000;
  let timer;
  const api = {
    login: async () => ({ access_token: 'secret-test-token', token_type: 'bearer', expires_in: 60 }),
    admin: async () => ({ id: 'test-user', role: 'admin', is_active: true }),
    logout: async () => {},
    ...overrides,
  };
  const session = createSession(api, {
    now: () => time, schedule: (callback) => { timer = callback; return 1; }, cancel: () => { timer = null; },
  });
  return { session, api, advance: (ms) => { time += ms; session.checkExpiration(); }, fire: () => timer?.() };
}

test('somente exibe sessão autenticada depois da autorização do servidor', async () => {
  const { session } = fixture();
  await session.login('admin@example.com', 'secret-password');
  assert.equal(session.getState().status, 'authenticated');
  assert.equal(JSON.stringify(session.getState()).includes('secret'), false);
  session.dispose();
});

test('credenciais inválidas preservam o login sem usuário', async () => {
  const { session } = fixture({ login: async () => { throw new Error('E-mail ou senha inválidos.'); } });
  await session.login('admin@example.com', 'incorrect');
  assert.equal(session.getState().status, 'anonymous');
  assert.equal(session.getState().user, null);
  assert.match(session.getState().error, /inválidos/);
});

test('usuário sem permissão não entra no painel', async () => {
  const { session } = fixture({ admin: async () => ({ role: 'member', is_active: true }) });
  await session.login('member@example.com', 'test-password');
  assert.equal(session.getState().status, 'anonymous');
});

test('expiração apaga sessão pelo relógio e pelo timer', async () => {
  const { session, advance, fire } = fixture();
  await session.login('', '');
  advance(61000);
  assert.equal(session.getState().status, 'anonymous');
  assert.match(session.getState().error, /expirou/);
  await session.login('', '');
  fire();
  assert.equal(session.getState().status, 'anonymous');
});

test('logout solicita revogação e limpa usuário imediatamente', async () => {
  let revoked = false;
  const { session } = fixture({ logout: async (token) => { revoked = token === 'secret-test-token'; } });
  await session.login('', '');
  const pending = session.logout();
  assert.equal(session.getState().user, null);
  await pending;
  assert.equal(revoked, true);
  assert.equal(session.getState().status, 'anonymous');
});

test('logout informa falha remota sem manter acesso local', async () => {
  const { session } = fixture({ logout: async () => { throw new Error('offline'); } });
  await session.login('', '');
  await session.logout();
  assert.equal(session.getState().status, 'anonymous');
  assert.match(session.getState().error, /neste navegador/);
});

test('401 na revalidação encerra a sessão', async () => {
  const { session, api } = fixture();
  await session.login('', '');
  api.admin = async () => { throw Object.assign(new Error('Unauthorized'), { status: 401 }); };
  await session.validate();
  assert.equal(session.getState().status, 'anonymous');
});

test('falha de rede bloqueia o painel e permite nova validação', async () => {
  const { session, api } = fixture();
  await session.login('', '');
  api.admin = async () => { throw new Error('offline'); };
  await session.validate();
  assert.equal(session.getState().status, 'verificationError');
  assert.equal(session.getState().user, null);
  api.admin = async () => ({ role: 'admin', is_active: true });
  await session.validate();
  assert.equal(session.getState().status, 'authenticated');
  session.dispose();
});

test('resposta atrasada de login não restaura sessão após logout', async () => {
  let resolve;
  const { session } = fixture({ admin: () => new Promise((done) => { resolve = done; }) });
  const pending = session.login('', '');
  await Promise.resolve();
  await session.logout();
  resolve({ role: 'admin', is_active: true });
  await pending;
  assert.equal(session.getState().status, 'anonymous');
});
