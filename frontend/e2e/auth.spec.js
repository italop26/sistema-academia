import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';

const credentials = JSON.parse(readFileSync(process.env.E2E_CREDENTIALS, 'utf8'));
async function login(page, email = credentials.email, password = credentials.password) {
  await page.goto('/');
  await page.getByLabel('E-mail', { exact: true }).fill(email);
  await page.getByLabel('Senha', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Entrar', exact: true }).click();
}

test('painel protegido, login real e logout revogado no Redis', async ({ page }) => {
  const consoleMessages = [];
  page.on('console', (message) => consoleMessages.push(message.text()));
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Entrar no sistema' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Painel administrativo' })).toHaveCount(0);
  await page.screenshot({ path: '/artifacts/login.png', fullPage: true });
  const response = page.waitForResponse((item) => item.url().endsWith('/api/auth/login'));
  await login(page);
  const token = (await (await response).json()).access_token;
  await expect(page.getByRole('heading', { name: 'Painel administrativo' })).toBeVisible();
  await expect(page.getByText('Sistema disponível', { exact: true })).toBeVisible();
  const storage = await page.evaluate(() => ({ local: { ...localStorage }, session: { ...sessionStorage } }));
  expect(JSON.stringify(storage).includes(token)).toBe(false);
  expect(consoleMessages.some((item) => item.includes(token) || item.includes(credentials.password))).toBe(false);
  await page.getByRole('button', { name: 'Sair', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Entrar no sistema' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Entrar', exact: true })).toBeEnabled();
  const replayStatus = await page.evaluate(async (value) => {
    const response = await fetch('/api/auth/me', { headers: { Authorization: `Bearer ${value}` } });
    return response.status;
  }, token);
  expect(replayStatus).toBe(401);
});

test('credenciais inválidas mostram mensagem sem liberar painel', async ({ page }) => {
  await login(page, credentials.email, 'invalid-password');
  await expect(page.getByRole('alert')).toContainText('E-mail ou senha inválidos.');
  await expect(page.getByRole('heading', { name: 'Painel administrativo' })).toHaveCount(0);
});

test('membro não tem acesso administrativo', async ({ page }) => {
  await login(page, credentials.member);
  await expect(page.getByRole('alert')).toContainText('conta de administrador');
  await expect(page.getByRole('heading', { name: 'Painel administrativo' })).toHaveCount(0);
});

test('recarregar não persiste sessão e token expirado é recusado pela API', async ({ page }) => {
  await login(page);
  await expect(page.getByRole('heading', { name: 'Painel administrativo' })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Entrar no sistema' })).toBeVisible();
  const status = await page.evaluate(async (value) => {
    const result = await fetch('/api/auth/me', { headers: { Authorization: `Bearer ${value}` } });
    return result.status;
  }, credentials.expired);
  expect(status).toBe(401);
});

test('expiração automática volta ao login', async ({ page }) => {
  await page.clock.install();
  await login(page);
  await expect(page.getByRole('heading', { name: 'Painel administrativo' })).toBeVisible();
  await page.clock.fastForward(16 * 60 * 1000);
  await expect(page.getByRole('heading', { name: 'Entrar no sistema' })).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('Sua sessão expirou');
});

test('erro de rede apresenta mensagem e permite tentar novamente', async ({ page }) => {
  await page.route('**/api/auth/login', (route) => route.abort());
  await login(page);
  await expect(page.getByRole('alert')).toContainText('Não foi possível acessar a API');
  await expect(page.getByRole('button', { name: 'Entrar', exact: true })).toBeEnabled();
});

test('carregamento bloqueia envio duplicado', async ({ page }) => {
  let release;
  const held = new Promise((resolve) => { release = resolve; });
  await page.route('**/api/auth/login', async (route) => { await held; await route.continue(); });
  await login(page);
  await expect(page.getByRole('button', { name: 'Aguarde…' })).toBeDisabled();
  await expect(page.getByRole('status')).toContainText('Validando acesso');
  release();
  await expect(page.getByRole('heading', { name: 'Painel administrativo' })).toBeVisible();
});

test('tela de login cabe na viewport móvel', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.getByLabel('Senha', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: '/artifacts/login-mobile.png', fullPage: true });
});
