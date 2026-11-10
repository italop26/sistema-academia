export async function fetchHealth(baseUrl, { signal, fetcher = fetch } = {}) {
  const response = await fetcher(`${baseUrl.replace(/\/$/, '')}/health`, { signal });
  if (!response.ok && response.status !== 503) {
    throw new Error('Não foi possível consultar o status do sistema.');
  }
  const data = await response.json();
  if (
    !['ok', 'degraded'].includes(data.status) ||
    !['ok', 'unavailable'].includes(data.database) ||
    !['ok', 'unavailable'].includes(data.redis)
  ) {
    throw new Error('A API retornou um status inválido.');
  }
  return data;
}
