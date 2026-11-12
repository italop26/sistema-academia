export function parseCents(value) {
  const text = String(value).trim().replace(',', '.');
  if (!/^\d{1,8}(\.\d{1,2})?$/.test(text)) throw new Error('Informe um valor com até duas casas decimais.');
  const [units, fraction = ''] = text.split('.');
  const cents = Number(units) * 100 + Number(fraction.padEnd(2, '0'));
  if (!Number.isSafeInteger(cents) || cents <= 0 || cents > 2_000_000_000) {
    throw new Error('Informe um valor positivo de até R$ 20.000.000,00.');
  }
  return cents;
}

export const money = (cents) => new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(cents / 100);

export function newRequestId() {
  // getRandomValues also works on the internal HTTP origin used by isolated browser tests.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
export const statusLabel = (fee) => fee.completed ? (fee.is_simulated ? 'Concluída (simulação)' : 'Concluída') : ({ pendente: 'Pendente', vencida: 'Vencida', cancelada: 'Cancelada' }[fee.status] || fee.status);

export async function loadCollection(session, path, signal) {
  const items = [];
  for (let offset = 0; ; offset += 200) {
    const page = await session.request(`${path}${path.includes('?') ? '&' : '?'}offset=${offset}&limit=200`, { signal });
    items.push(...page);
    if (page.length < 200) return items;
  }
}
