import assert from 'node:assert/strict';
import test from 'node:test';
import { fetchHealth } from './health.js';

const healthy = { status: 'ok', database: 'ok', redis: 'ok' };

test('consulta a API sem duplicar a barra e repassa o sinal de cancelamento', async () => {
  const controller = new AbortController();
  const result = await fetchHealth('http://localhost:8000/', {
    signal: controller.signal,
    fetcher: async (url, options) => {
      assert.equal(url, 'http://localhost:8000/health');
      assert.equal(options.signal, controller.signal);
      return new Response(JSON.stringify(healthy));
    },
  });
  assert.deepEqual(result, healthy);
});

test('exibe o estado degradado retornado com HTTP 503', async () => {
  const degraded = { ...healthy, status: 'degraded', database: 'unavailable' };
  const result = await fetchHealth('', {
    fetcher: async () => new Response(JSON.stringify(degraded), { status: 503 }),
  });
  assert.deepEqual(result, degraded);
});

test('rejeita erros HTTP inesperados', async () => {
  await assert.rejects(fetchHealth('', {
    fetcher: async () => new Response('', { status: 500 }),
  }), /Não foi possível/);
});

test('rejeita um corpo sem o contrato de saúde', async () => {
  await assert.rejects(fetchHealth('', {
    fetcher: async () => new Response('{}'),
  }), /status inválido/);
});

test('propaga a indisponibilidade de rede', async () => {
  await assert.rejects(fetchHealth('', {
    fetcher: async () => { throw new TypeError('Failed to fetch'); },
  }), /Failed to fetch/);
});
