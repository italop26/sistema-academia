import { readFileSync } from 'node:fs';
import { spawn } from 'node:child_process';

const credentials = JSON.parse(readFileSync(process.env.E2E_CREDENTIALS, 'utf8'));
const child = spawn(process.execPath, ['node_modules/@playwright/test/cli.js', 'test'], { stdio: ['ignore', 'pipe', 'pipe'] });
let output = '';
child.stdout.on('data', (chunk) => { output += chunk; });
child.stderr.on('data', (chunk) => { output += chunk; });
child.on('error', () => { console.error('Não foi possível iniciar os testes de navegador.'); process.exitCode = 1; });
child.on('close', (code) => {
  for (const secret of [credentials.password, credentials.expired]) output = output.replaceAll(secret, '[REDACTED]');
  output = output.replace(/eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g, '[REDACTED_JWT]');
  console.log(output);
  process.exitCode = code ?? 1;
});
