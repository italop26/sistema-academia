import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';

const args = ['compose', '-p', 'academia-validation', '--env-file', '.env.validation', '-f', 'compose.yaml', '-f', 'compose.validation.yaml'];
function docker(command, includeStderr = false) {
  const result = spawnSync('docker', [...args, ...command], { encoding: 'utf8', maxBuffer: 20 * 1024 * 1024 });
  if (result.status !== 0) throw new Error('Não foi possível inspecionar o ambiente de validação.');
  return result.stdout + (includeStderr ? result.stderr : '');
}
const env = readFileSync('.env.validation', 'utf8');
const secrets = env.split(/\r?\n/).filter((line) => /^(POSTGRES_PASSWORD|REDIS_PASSWORD|JWT_SECRET_KEY)=/.test(line)).map((line) => line.slice(line.indexOf('=') + 1));
const credentials = JSON.parse(docker(['exec', '-T', '--user', 'root', 'backend', 'python', '-c', "from pathlib import Path; print(Path('/app/data/e2e-credentials.json').read_text())"]));
secrets.push(credentials.password, credentials.expired);
const logs = docker(['logs', '--no-color', 'backend', 'frontend', 'worker', 'scheduler'], true);
if (!logs.includes('Requisição HTTP')) throw new Error('Nenhuma requisição HTTP encontrada para validar os logs.');
if (secrets.some((secret) => secret && logs.includes(secret)) || /eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/.test(logs)) {
  console.error('FALHOU: dados sensíveis encontrados nos logs; conteúdo omitido.');
  process.exitCode = 1;
} else {
  console.log('PASSOU: logs de backend, frontend, worker e scheduler sem os segredos verificados ou JWTs completos.');
}
