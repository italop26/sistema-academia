import { randomBytes } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';

const root = new URL('../', import.meta.url);
const path = new URL('.env', root);
let content;
let exists = true;
try {
  content = await readFile(path, 'utf8');
} catch (error) {
  if (error.code !== 'ENOENT') throw error;
  content = await readFile(new URL('.env.example', root), 'utf8');
  exists = false;
}

const original = content;
for (const name of ['POSTGRES_PASSWORD', 'REDIS_PASSWORD', 'JWT_SECRET_KEY']) {
  const pattern = new RegExp(`^${name}=(.*)$`, 'm');
  const match = content.match(pattern);
  if (match && match[1].trim()) continue;
  const line = `${name}=${randomBytes(32).toString('hex')}`;
  content = match ? content.replace(pattern, line) : `${content.trimEnd()}\n${line}\n`;
}

if (process.argv.includes('--sqlite')) {
  const line = 'DATABASE_URL=sqlite+pysqlite:///./data/academia.db';
  content = /^DATABASE_URL=.*$/m.test(content)
    ? content.replace(/^DATABASE_URL=.*$/m, line)
    : `${content.trimEnd()}\n${line}\n`;
  await mkdir(new URL('backend/data/', root), { recursive: true });
}

if (!exists || content !== original) {
  await writeFile(path, content, { flag: exists ? 'w' : 'wx', mode: 0o600 });
  console.log('.env preparado. Senhas existentes preservadas; segredos ausentes gerados.');
} else {
  console.log('.env já está configurado e foi preservado.');
}
