import assert from 'node:assert/strict';
import test from 'node:test';
import { createAuthApi } from './auth.js';

test('envia credenciais em JSON e token apenas no header', async () => {
  const calls = [];
  const api = createAuthApi('/api/', async (url, options) => {
    calls.push({ url, options });
    return new Response('{}');
  });
  await api.login('admin@example.com', 'test-password');
  await api.admin('test-token');
  assert.equal(calls[0].url, '/api/auth/login');
  assert.deepEqual(JSON.parse(calls[0].options.body), { email: 'admin@example.com', password: 'test-password' });
  assert.equal(calls[1].options.headers.Authorization, 'Bearer test-token');
  assert.equal(calls[1].url, '/api/auth/admin');
  assert.equal(calls[1].options.cache, 'no-store');
  assert.equal(calls[1].options.credentials, 'omit');
});

test('não expõe o corpo de erros da API', async () => {
  const api = createAuthApi('', async () => new Response('sensitive-internal-data', { status: 500 }));
  await assert.rejects(api.me('test-token'), (error) => error.status === 500 && !error.message.includes('sensitive'));
});

test('logout aceita resposta sem conteúdo', async () => {
  const api = createAuthApi('', async (url, options) => {
    assert.equal(url, '/auth/logout');
    assert.equal(options.method, 'POST');
    return new Response(null, { status: 204 });
  });
  assert.equal(await api.logout('test-token'), null);
});

test('apresenta erro de rede sem expor detalhes de transporte', async () => {
  const api = createAuthApi('', async () => { throw new Error('sensitive-url'); });
  await assert.rejects(api.me('test-token'), /Não foi possível acessar a API/);
});
