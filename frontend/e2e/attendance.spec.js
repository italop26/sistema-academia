import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';

const credentials = JSON.parse(readFileSync(process.env.E2E_CREDENTIALS, 'utf8'));

test('check-in diário, suspensão e retomada preservam o histórico individual', async ({ page, request }) => {
  const login = await request.post('/api/auth/login', { data: { email: credentials.email, password: credentials.password } });
  const headers = { Authorization: `Bearer ${(await login.json()).access_token}` };
  async function post(path, data) {
    const response = await request.post(`/api${path}`, { headers, data });
    expect(response.ok()).toBe(true);
    return response.json();
  }
  const name = `Presença ${randomUUID()}`;
  const student = await post('/admin/students', { name });
  const plan = await post('/admin/plans', { name: 'Plano frequência', monthly_amount_cents: 10000 });
  const today = new Intl.DateTimeFormat('sv-SE', { timeZone: 'America/Fortaleza' }).format(new Date());
  const enrollment = await post('/admin/enrollments', { student_id: student.id, plan_id: plan.id, starts_on: today, due_day: 1 });
  await page.goto('/');
  await page.getByLabel('E-mail', { exact: true }).fill(credentials.email);
  await page.getByLabel('Senha', { exact: true }).fill(credentials.password);
  await page.getByRole('button', { name: 'Entrar', exact: true }).click();
  const panel = page.getByRole('region', { name: 'Frequência dos alunos', exact: true });
  await panel.getByLabel('Aluno da frequência').selectOption(student.id);
  await expect(panel.getByRole('button', { name: 'Registrar presença', exact: true })).toBeEnabled();
  await panel.getByRole('button', { name: 'Registrar presença', exact: true }).click();
  await expect(panel.getByText('Total de presenças: 1', { exact: true })).toBeVisible();
  await panel.getByRole('button', { name: 'Registrar presença', exact: true }).click();
  await expect(panel.getByText('Total de presenças: 1', { exact: true })).toBeVisible();
  await panel.getByRole('button', { name: 'Suspender frequência', exact: true }).click();
  await panel.getByLabel('Motivo da alteração de frequência').fill('Pausa de frequência de teste');
  await panel.getByRole('button', { name: 'Confirmar alteração de frequência', exact: true }).click();
  await expect(panel.getByRole('button', { name: 'Registrar presença', exact: true })).toBeDisabled();
  const blocked = await request.post('/api/admin/attendance/check-ins', { headers, data: {
    student_id: student.id, enrollment_id: enrollment.id, idempotency_key: randomUUID(),
  } });
  expect(blocked.status()).toBe(409);
  await panel.getByRole('button', { name: 'Retomar frequência', exact: true }).click();
  await panel.getByLabel('Motivo da alteração de frequência').fill('Retorno às atividades de teste');
  await panel.getByRole('button', { name: 'Confirmar alteração de frequência', exact: true }).click();
  await expect(panel.getByRole('button', { name: 'Registrar presença', exact: true })).toBeEnabled();
  await expect(panel.getByText('Retomada', { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
