import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';

const credentials = JSON.parse(readFileSync(process.env.E2E_CREDENTIALS, 'utf8'));

test('mensalidade vencida gera lembrete simulado pelo worker e aparece no painel', async ({ page, request }) => {
  test.skip(process.env.AUTOMATION_RUNTIME_TESTS !== '1', 'Exige worker no ambiente descartável.');
  const login = await request.post('/api/auth/login', { data: { email: credentials.email, password: credentials.password } });
  const headers = { Authorization: `Bearer ${(await login.json()).access_token}` };
  const name = `Aluno lembrete ${randomUUID().slice(0, 8)}`;
  async function post(path, data) {
    const response = await request.post(`/api${path}`, { headers, data });
    expect(response.ok()).toBe(true);
    return response.json();
  }
  const today = new Intl.DateTimeFormat('sv-SE', { timeZone: 'America/Fortaleza' }).format(new Date());
  const previous = new Date(`${today.slice(0, 7)}-01T12:00:00Z`);
  previous.setUTCDate(0);
  const competence = previous.toISOString().slice(0, 7);
  const student = await post('/admin/students', { name });
  const plan = await post('/admin/plans', { name: 'Plano de lembrete teste', monthly_amount_cents: 12000 });
  const enrollment = await post('/admin/enrollments', { student_id: student.id, plan_id: plan.id,
    starts_on: `${competence}-01`, due_day: 1 });
  await post('/admin/monthly-fees/generate', { enrollment_id: enrollment.id, competence });
  await page.goto('/');
  await page.getByLabel('E-mail', { exact: true }).fill(credentials.email);
  await page.getByLabel('Senha', { exact: true }).fill(credentials.password);
  await page.getByRole('button', { name: 'Entrar', exact: true }).click();
  const panel = page.getByRole('region', { name: 'Lembretes simulados', exact: true });
  await expect(panel.getByRole('button', { name: 'Verificar mensalidades vencidas' })).toBeEnabled();
  await panel.getByRole('button', { name: 'Verificar mensalidades vencidas' }).click();
  const row = panel.getByRole('listitem').filter({ hasText: name });
  await expect(row).toContainText('Simulados', { timeout: 15000 });
  await expect(row).toContainText('1 tentativa(s)');
  await row.getByRole('button', { name: 'Histórico do lembrete' }).click();
  const history = panel.getByRole('region', { name: 'Histórico do lembrete', exact: true });
  await expect(history).toContainText('Simulação registrada');
  await expect(history).toContainText('Envio simulado');
  await panel.getByRole('button', { name: 'Verificar mensalidades vencidas' }).click();
  await expect(row).toContainText('1 tentativa(s)');
});

test('painel de lembretes pagina, filtra e apresenta nomes longos no celular', async ({ page, request }) => {
  test.setTimeout(120000);
  test.skip(process.env.AUTOMATION_RUNTIME_TESTS !== '1', 'Exige worker no ambiente descartável.');
  const login = await request.post('/api/auth/login', { data: { email: credentials.email, password: credentials.password } });
  const headers = { Authorization: `Bearer ${(await login.json()).access_token}` };
  async function post(path, data) {
    const response = await request.post(`/api${path}`, { headers, data });
    expect(response.ok()).toBe(true);
    return response.json();
  }
  const previous = new Date();
  previous.setUTCDate(0);
  const competence = previous.toISOString().slice(0, 7);
  const plan = await post('/admin/plans', { name: 'Plano paginação', monthly_amount_cents: 12000 });
  const batch = `Paginação${randomUUID().slice(0, 8)}`;
  const longName = `${batch}${'X'.repeat(83)}`;
  for (let index = 0; index < 25; index++) {
    const student = await post('/admin/students', { name: index === 24 ? longName : `${batch} ${index}` });
    const enrollment = await post('/admin/enrollments', { student_id: student.id, plan_id: plan.id,
      starts_on: `${competence}-01`, due_day: 1 });
    await post('/admin/monthly-fees/generate', { enrollment_id: enrollment.id, competence });
  }
  await post('/admin/notifications/scan');
  await expect.poll(async () => {
    const response = await request.get('/api/admin/notifications/reminders?status=sent&limit=100', { headers });
    return (await response.json()).filter(row => row.student_name.startsWith(batch)).length;
  }, { timeout: 30000 }).toBe(25);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await page.getByLabel('E-mail', { exact: true }).fill(credentials.email);
  await page.getByLabel('Senha', { exact: true }).fill(credentials.password);
  await page.getByRole('button', { name: 'Entrar', exact: true }).click();
  const panel = page.getByRole('region', { name: 'Lembretes simulados', exact: true });
  await panel.getByLabel('Situação do lembrete').selectOption('sent');
  const rows = panel.locator('ul.record-list > li');
  await expect(rows).toHaveCount(20);
  const firstPage = await rows.locator('strong').allTextContents();
  await panel.getByRole('button', { name: 'Mais lembretes', exact: true }).click();
  await expect.poll(async () => (await rows.locator('strong').allTextContents()).some(name => firstPage.includes(name))).toBe(false);
  await panel.getByRole('button', { name: 'Lembretes anteriores', exact: true }).click();
  await expect(rows.locator('strong').first()).toHaveText(firstPage[0]);
  await expect(panel.getByText(longName, { exact: true })).toBeVisible();
  const layout = await page.evaluate(() => ({
    fits: document.documentElement.scrollWidth <= window.innerWidth,
    overflow: [...document.querySelectorAll('body *')].filter(element => element.getBoundingClientRect().right > window.innerWidth)
      .map(element => ({ tag: element.tagName, className: element.className, width: element.getBoundingClientRect().width })),
  }));
  expect(layout.fits, JSON.stringify(layout.overflow)).toBe(true);
  if (process.env.E2E_ARTIFACT_DIR) {
    await panel.getByText(longName, { exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${process.env.E2E_ARTIFACT_DIR}/notifications-mobile.png` });
  }
  await panel.getByLabel('Situação do lembrete').selectOption('exhausted');
  await expect(panel.getByText('Nenhum lembrete nesta consulta.')).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Lembretes anteriores', exact: true })).toBeDisabled();
});
