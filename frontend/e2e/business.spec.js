import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';

const credentials = JSON.parse(readFileSync(process.env.E2E_CREDENTIALS, 'utf8'));
const today = new Intl.DateTimeFormat('sv-SE', { timeZone: 'America/Fortaleza' }).format(new Date());

test('matrícula, mensalidade, pagamento e histórico ficam vinculados ao aluno certo', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('E-mail', { exact: true }).fill(credentials.email);
  await page.getByLabel('Senha', { exact: true }).fill(credentials.password);
  await page.getByRole('button', { name: 'Entrar', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Matrículas e mensalidades', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Cadastrar aluno' })).toBeEnabled();
  const suffix = Date.now();
  const names = [`Aluno A ${suffix}`, `Aluno B ${suffix}`];
  const plan = `Pilates teste ${suffix}`;
  await page.getByLabel('Nome do plano', { exact: true }).fill(plan);
  await page.getByLabel('Mensalidade do plano (R$)').fill('199,90');
  await page.getByRole('button', { name: 'Cadastrar plano', exact: true }).click();
  await expect(page.getByText('Cadastro registrado com histórico.', { exact: true })).toBeVisible();

  for (const name of names) {
    await page.getByLabel('Nome do aluno', { exact: true }).fill(name);
    await page.getByRole('button', { name: 'Cadastrar aluno', exact: true }).click();
    await expect(page.getByLabel('Aluno em atendimento')).toBeEnabled();
    await page.getByLabel('Aluno em atendimento').selectOption({ label: name });
    await expect(page.getByLabel('Plano da matrícula')).toBeEnabled();
    await page.getByLabel('Plano da matrícula').selectOption({ label: `${plan} · R$ 199,90` });
    await page.getByLabel('Início da matrícula').fill(`${today.slice(0, 7)}-01`);
    await page.getByLabel('Dia do vencimento').fill('31');
    await page.getByRole('button', { name: 'Matricular aluno', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Gerar mensalidade', exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Gerar mensalidade', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Registrar pagamento', exact: true })).toBeVisible();
  }
  await page.getByLabel('Aluno em atendimento').selectOption({ label: names[0] });
  await expect(page.getByRole('button', { name: 'Registrar pagamento', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Registrar pagamento', exact: true }).click();
  await page.getByLabel('Valor recebido (R$)').fill('1,00');
  await page.getByLabel('Observação do recebimento').fill('Recebimento confirmado no teste');
  await page.getByRole('button', { name: 'Confirmar registro', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('valor');
  await expect(page.getByText('Concluída', { exact: true })).toHaveCount(0);
  await page.getByLabel('Valor recebido (R$)').fill('199,90');
  await page.getByRole('button', { name: 'Confirmar registro', exact: true }).click();
  await expect(page.getByText('Concluída', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Registrar pagamento', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Histórico', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Histórico de alterações' })).toContainText('Pagamento concluído');
  await expect(page.getByRole('region', { name: 'Histórico de alterações' })).toContainText('Recebimento confirmado no teste');
  await page.getByLabel('Aluno em atendimento').selectOption({ label: names[1] });
  await expect(page.getByRole('button', { name: 'Registrar pagamento', exact: true })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Gestão de matrículas e mensalidades', exact: true }).getByText('Pendente', { exact: true })).toBeVisible();
  await expect(page.getByText('Concluída', { exact: true })).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
