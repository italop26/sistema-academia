import { useEffect, useRef, useState } from 'react';
import { money } from '../api/business.js';

const labels = { pending: 'Pendentes', retry_wait: 'Nova tentativa programada', sent: 'Simulados',
  exhausted: 'Limite de tentativas', suppressed: 'Dispensados' };
const stamp = (value) => value ? new Date(value).toLocaleString('pt-BR', { timeZone: 'America/Fortaleza' }) : '—';

export default function NotificationsPanel({ session }) {
  const [summary, setSummary] = useState(null);
  const [rows, setRows] = useState([]);
  const [offset, setOffset] = useState(0);
  const [filter, setFilter] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState(null);
  const [retry, setRetry] = useState(null);
  const [reason, setReason] = useState('');
  const active = useRef(null);
  const operation = useRef(false);
  const version = useRef(0);

  async function refresh(signal) {
    const current = ++version.current;
    const [nextSummary, nextRows] = await Promise.all([
      session.request('/admin/notifications/summary', { signal }),
      session.request(`/admin/notifications/reminders?offset=${offset}&limit=20${filter ? `&status=${filter}` : ''}`, { signal }),
    ]);
    if (!signal?.aborted && current === version.current) {
      setSummary(nextSummary); setRows(nextRows); setError('');
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    active.current = controller;
    const reload = () => {
      if (!operation.current) refresh(controller.signal).catch((failure) => {
        if (!controller.signal.aborted) setError(failure.message);
      });
    };
    reload();
    const timer = setInterval(reload, 5000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [session, filter, offset]);

  async function act(work, message) {
    if (operation.current) return;
    operation.current = true; setBusy(true); setError(''); setNotice('');
    try {
      await work();
      await refresh(active.current?.signal);
      setNotice(message);
    } catch (failure) { setError(failure.message); }
    finally { operation.current = false; setBusy(false); }
  }

  function showHistory(row) {
    void act(async () => {
      const [attempts, events] = await Promise.all([
        session.request(`/admin/notifications/reminders/${row.id}/attempts`),
        session.request(`/admin/history?entity_type=reminder&entity_id=${row.id}`),
      ]);
      setHistory({ row, attempts, events }); setRetry(null);
    }, 'Histórico consultado.');
  }

  return <section className="management status-card" aria-label="Lembretes simulados" aria-busy={busy}>
    <h2>Lembretes simulados</h2>
    <p className="hint">Nenhuma mensagem real é enviada. Cada mensalidade vencida gera no máximo um lembrete nesta regra.</p>
    {error && <p className="error" role="alert">{error}</p>}
    {notice && <p className="success" role="status">{notice}</p>}
    {summary && <>
      <div className="notification-summary">{Object.entries(labels).map(([status, label]) =>
        <div key={status}><strong>{summary.counts[status]}</strong><span>{label}</span></div>)}</div>
      {!summary.enabled && <p>Automação desativada na configuração.</p>}
    </>}
    <fieldset disabled={busy}>
      <legend className="sr-only">Acompanhamento dos lembretes</legend>
      <div className="actions">
        <button type="button" disabled={!summary?.enabled} onClick={() => act(async () => {
          await session.request('/admin/notifications/scan', { method: 'POST' });
        }, 'Verificação concluída. Acompanhe as pendências e simulações abaixo.')}>Verificar mensalidades vencidas</button>
        <button type="button" className="secondary" onClick={() => act(async () => {}, 'Lembretes atualizados.')}>Atualizar lembretes</button>
      </div>
      <label htmlFor="reminder-filter">Situação do lembrete</label>
      <select id="reminder-filter" value={filter} onChange={(event) => { setFilter(event.target.value); setOffset(0); }}>
        <option value="">Todas</option>
        {Object.entries(labels).map(([status, label]) => <option key={status} value={status}>{label}</option>)}
      </select>
      {!rows.length && <p>Nenhum lembrete nesta consulta.</p>}
      <ul className="record-list">{rows.map((row) => <li key={row.id}>
        <div><strong>{row.student_name || 'Aluno'}</strong><p>{labels[row.status]} · {row.attempt_count} tentativa(s)</p>
          <p className="hint">Competência {row.competence} · {money(row.amount_cents)}<br />
            {row.sent_at ? `Simulação registrada em ${stamp(row.sent_at)}` : row.next_attempt_at ? `Próxima tentativa a partir de ${stamp(row.next_attempt_at)}` : ''}
            {row.suppression_reason && ` · ${row.suppression_reason === 'paid' ? 'Mensalidade quitada' : row.suppression_reason === 'cancelled' ? 'Mensalidade cancelada' : 'Sem atraso atual'}`}
          </p>
        </div>
        <div className="actions"><button type="button" className="secondary" onClick={() => showHistory(row)}>Histórico do lembrete</button>
          {row.status === 'exhausted' && row.retry_cycles < 3 && <button type="button" disabled={!summary?.enabled} onClick={() => { setRetry(row); setReason(''); setHistory(null); }}>Reabrir tentativas</button>}
        </div>
      </li>)}</ul>
      <div className="actions"><button type="button" className="secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>Lembretes anteriores</button>
        <button type="button" className="secondary" disabled={rows.length < 20} onClick={() => setOffset(offset + 20)}>Mais lembretes</button></div>
      {retry && <form onSubmit={(event) => {
        event.preventDefault();
        void act(async () => { await session.request(`/admin/notifications/reminders/${retry.id}/retry`, { method: 'POST', body: { reason } }); setRetry(null); }, 'Nova tentativa registrada com histórico.');
      }}><h3>Reabrir tentativas de {retry.student_name}</h3>
        <label htmlFor="reminder-retry-reason">Motivo da nova tentativa</label>
        <textarea id="reminder-retry-reason" value={reason} onChange={(event) => setReason(event.target.value)} required minLength={3} maxLength={500} />
        <div className="actions"><button>Confirmar nova tentativa</button><button type="button" className="secondary" onClick={() => setRetry(null)}>Voltar aos lembretes</button></div>
      </form>}
      {history && <section aria-label="Histórico do lembrete"><h3>Histórico de {history.row.student_name}</h3>
        <ol>{history.attempts.map((attempt) => <li key={attempt.id}>Tentativa {attempt.number}: {attempt.outcome === 'sent' ? 'Simulação registrada' : 'Falhou'} · {stamp(attempt.created_at)}</li>)}</ol>
        {!history.attempts.length && <p>Nenhuma tentativa de envio; o lembrete pode estar pendente ou ter sido dispensado.</p>}
        <ul>{history.events.map((event) => <li key={event.id}>{stamp(event.created_at)} · {event.actor_type === 'system' ? 'Sistema' : 'Administrador'} · {event.reason || ({ planned: 'Pendência registrada', simulated_sent: 'Envio simulado', suppressed: 'Lembrete dispensado', send_failed: 'Falha na simulação', publication_failed: 'Agendamento pendente', retry_requested: 'Nova tentativa solicitada' }[event.action] || 'Alteração registrada')}</li>)}</ul>
        <button type="button" className="secondary" onClick={() => setHistory(null)}>Fechar histórico do lembrete</button>
      </section>}
    </fieldset>
  </section>;
}
