import { readFile, readdir } from 'node:fs/promises';
import { join } from 'node:path';

const secrets = [];
for (const path of ['.env', '.env.validation']) {
  try {
    const env = await readFile(path, 'utf8');
    for (const line of env.split(/\r?\n/)) {
      if (/^(POSTGRES_PASSWORD|REDIS_PASSWORD|JWT_SECRET_KEY)=/.test(line)) {
        const value = line.slice(line.indexOf('=') + 1);
        if (value.length >= 12) secrets.push(value);
      }
    }
  } catch (error) { if (error.code !== 'ENOENT') throw error; }
}
async function check(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) { await check(path); continue; }
    const content = await readFile(path, 'utf8');
    if (secrets.some((value) => content.includes(value))) {
      throw new Error('FALHOU: segredo encontrado no bundle; conteúdo omitido.');
    }
  }
}
if (!secrets.length) throw new Error('Configure o ambiente antes de verificar o bundle.');
await check('frontend/dist');
console.log('PASSOU: nenhum dos segredos configurados foi encontrado no bundle do frontend.');
