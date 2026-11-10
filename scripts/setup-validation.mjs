import { randomBytes } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';

const root = new URL('../', import.meta.url);
let content = await readFile(new URL('.env.example', root), 'utf8');
for (const name of ['POSTGRES_PASSWORD', 'REDIS_PASSWORD', 'JWT_SECRET_KEY']) {
  content = content.replace(new RegExp(`^${name}=.*$`, 'm'), `${name}=${randomBytes(32).toString('hex')}`);
}
content = content.replace(/^APP_ENV=.*$/m, 'APP_ENV=test');
content += '\nDATABASE_URL=sqlite+pysqlite:///./data/validation.db\nVALIDATION_ONLY=1\n';
try {
  await writeFile(new URL('.env.validation', root), content, { flag: 'wx', mode: 0o600 });
  console.log('Ambiente de validação criado com segredos independentes.');
} catch (error) {
  if (error.code !== 'EEXIST') throw error;
  console.log('Ambiente de validação existente preservado.');
}
