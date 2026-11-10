import { useEffect, useRef, useState } from 'react';
import { fetchHealth } from '../api/health.js';

export default function Dashboard({ user, session, apiUrl }) {
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const pending = useRef(null);
  async function checkHealth() {
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    const timeout = setTimeout(() => controller.abort(), 12000);
    setLoading(true);
    setError('');
    try {
      const result = await fetchHealth(apiUrl, { signal: controller.signal });
      if (pending.current === controller) setHealth(result);
    } catch {
      if (pending.current === controller) { setHealth(null); setError('Não foi possível consultar a disponibilidade dos serviços.'); }
    } finally {
      clearTimeout(timeout);
      if (pending.current === controller) setLoading(false);
    }
  }
  useEffect(() => {
    checkHealth();
    return () => { pending.current?.abort(); pending.current = null; };
  }, []);
  return (
    <>
      <section className="panel-heading"><div><p className="eyebrow">ÁREA ADMINISTRATIVA</p><h1>Painel administrativo</h1><p className="description">Olá, {user.name}.</p></div><button className="secondary" onClick={() => session.logout()}>Sair</button></section>
      <section className="status-card" aria-label="Conta autenticada"><h2>Sua conta</h2><dl><div><dt>E-mail</dt><dd>{user.email}</dd></div><div><dt>Permissão</dt><dd>Administrador</dd></div></dl></section>
      <section className="status-card" aria-labelledby="status-title" aria-busy={loading}>
        <div className="status-heading"><h2 id="status-title">Status do sistema</h2><span className={`badge ${health?.status === 'ok' && !loading ? 'available' : ''}`} role="status">{loading ? 'Consultando…' : health?.status === 'ok' ? 'Sistema disponível' : 'Serviços indisponíveis'}</span></div>
        {error && <p className="error" role="alert">{error}</p>}
        <dl>
          <div><dt>API</dt><dd>{loading ? 'Consultando…' : health ? 'Conectada' : 'Indisponível'}</dd></div>
          <div><dt>Banco de dados</dt><dd>{loading ? 'Consultando…' : health?.database === 'ok' ? 'Conectado' : 'Indisponível'}</dd></div>
          <div><dt>Fila de automações</dt><dd>{loading ? 'Consultando…' : health?.redis === 'ok' ? 'Conectada' : 'Indisponível'}</dd></div>
        </dl>
        <p className="hint">A conectividade da fila não indica execução de automações.</p>
        <button onClick={checkHealth} disabled={loading}>{loading ? 'Verificando…' : 'Verificar novamente'}</button>
      </section>
    </>
  );
}
