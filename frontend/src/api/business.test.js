import assert from 'node:assert/strict';
import test from 'node:test';
import { loadCollection, parseCents, statusLabel } from './business.js';
import { createHttpClient } from './http.js';

test('converte reais em centavos sem arredondamento financeiro implícito', () => {
  assert.equal(parseCents('199,90'), 19990);
  assert.equal(parseCents('0.29'), 29);
  assert.equal(parseCents('10'), 1000);
  assert.equal(parseCents('1.1'), 110);
  for (const value of ['0', '-1', '1.001', '1e3', 'abc', '', '20000000.01']) {
    assert.throws(() => parseCents(value));
  }
});

test('conclusão usa a confirmação do backend', () => {
  assert.equal(statusLabel({ status: 'paga', completed: true }), 'Concluída');
  assert.equal(statusLabel({ status: 'pendente', completed: false }), 'Pendente');
  assert.equal(statusLabel({ status: 'paga', completed: true, is_simulated: true }), 'Concluída (simulação)');
});

test('coleções carregam todas as páginas preservando o filtro do aluno', async () => {
  const calls = [];
  const session = { request: async (url) => {
    calls.push(url);
    return calls.length === 1 ? Array.from({ length: 200 }, (_, id) => ({ id })) : [{ id: 201 }];
  } };
  const values = await loadCollection(session, '/admin/monthly-fees?student_id=student-a');
  assert.equal(values.length, 201);
  assert.equal(calls[1], '/admin/monthly-fees?student_id=student-a&offset=200&limit=200');
});

test('mostra apenas mensagens conhecidas para conflitos financeiros', async () => {
  const request = createHttpClient('/api', async () => new Response(JSON.stringify({
    error: { code: 'amount_mismatch', message: 'sensitive-provider-info' },
  }), { status: 409 }));
  await assert.rejects(request('/admin/monthly-fees/a/pay'), (failure) =>
    failure.status === 409 && failure.message.includes('valor') && !failure.message.includes('sensitive'));
});
