import { createHmac, randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';

const credentials = JSON.parse(readFileSync(process.env.E2E_CREDENTIALS, 'utf8'));
const secret = process.env.PIX_WEBHOOK_TEST_SECRET;

test('webhook assinado conclui somente uma vez e o painel identifica a simulação', async ({ page, request }) => {
  test.skip(!secret, 'Exige ambiente isolado com segredo exclusivo do webhook de testes.');
  const auth = await request.post('/api/auth/login', { data: { email: credentials.email, password: credentials.password } });
  expect(auth.ok()).toBe(true);
  const token = (await auth.json()).access_token;
  const headers = { Authorization: `Bearer ${token}` };
  async function post(path, data) {
    const response = await request.post(`/api${path}`, { headers, data });
    expect(response.ok()).toBe(true);
    return response.json();
  }
  const today = new Intl.DateTimeFormat('sv-SE', { timeZone: 'America/Fortaleza' }).format(new Date());
  const name = `Aluno Pix ${randomUUID().slice(0, 8)}`;
  const student = await post('/admin/students', { name });
  const plan = await post('/admin/plans', { name: 'Plano Pix de teste', monthly_amount_cents: 15000 });
  const enrollment = await post('/admin/enrollments', {
    student_id: student.id, plan_id: plan.id, starts_on: `${today.slice(0, 7)}-01`, due_day: 31,
  });
  const fee = await post('/admin/monthly-fees/generate', { enrollment_id: enrollment.id, competence: today.slice(0, 7) });
  const charge = await post('/admin/pix/charges', { monthly_fee_id: fee.id, idempotency_key: randomUUID() });
  expect(charge.is_simulated).toBe(true);
  expect(charge.payment_code).toBe(null);
  const payload = JSON.stringify({
    schema_version: 1, event_id: randomUUID(), event_type: 'payment.confirmed', is_simulated: true,
    charge_id: charge.id, reference: charge.reference, amount_cents: fee.amount_cents,
    currency: 'BRL', external_payment_id: `TEST-PAY-${randomUUID()}`, occurred_at: charge.created_at,
  });
  const timestamp = String(Math.floor(Date.now() / 1000));
  const signature = createHmac('sha256', secret).update(`${timestamp}.${payload}`).digest('hex');
  const webhookHeaders = { 'Content-Type': 'application/json', 'X-Pix-Test-Timestamp': timestamp,
    'X-Pix-Test-Signature': `sha256=${signature}` };
  const first = await request.post('/api/webhooks/pix/simulated', { headers: webhookHeaders, data: payload });
  expect(first.status()).toBe(200);
  const original = await first.json();
  expect(original.status).toBe('processed');
  const repeat = await request.post('/api/webhooks/pix/simulated', { headers: webhookHeaders, data: payload });
  expect(repeat.status()).toBe(200);
  expect((await repeat.json()).duplicate).toBe(true);
  const event = await request.get(`/api/admin/pix/events/${original.id}`, { headers });
  const saved = await event.json();
  expect(saved.delivery_count).toBe(2);
  expect(saved.attempt_count).toBe(1);
  await page.goto('/');
  await page.getByLabel('E-mail', { exact: true }).fill(credentials.email);
  await page.getByLabel('Senha', { exact: true }).fill(credentials.password);
  await page.getByRole('button', { name: 'Entrar', exact: true }).click();
  await expect(page.getByLabel('Aluno em atendimento')).toBeEnabled();
  await page.getByLabel('Aluno em atendimento').selectOption({ label: name });
  await expect(page.getByText('Concluída (simulação)', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Registrar pagamento', exact: true })).toHaveCount(0);
});
