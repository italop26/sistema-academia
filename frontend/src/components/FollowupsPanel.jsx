import { useEffect, useRef, useState } from 'react';
import { loadCollection } from '../api/business.js';

const labels = { pendente: 'Pendente', em_acompanhamento: 'Em acompanhamento', resolvido: 'Resolvido', encerrado: 'Encerrado' };
const stamp = value => value ? new Date(value).toLocaleString('pt-BR', { timeZone: 'America/Fortaleza' }) : 'Ainda não realizada';

export default function FollowupsPanel({ session, userId }) {
  const [rows, setRows] = useState([]);
  const [filter, setFilter] = useState('pendente');
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState(null);
  const [runs, setRuns] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [operation, setOperation] = useState(null);
  const [note, setNote] = useState('');
  const [history, setHistory] = useState(null);
  const query = useRef(null);
  const pending = useRef(false);
  const version = useRef(0);

  async function refresh(signal) {
    const current = ++version.current;
    const [items, nextStatus, nextRuns] = await Promise.all([
      session.request(`/admin/absence/detections?offset=${offset}&limit=20${filter ? `&status=${filter}` : ''}`, { signal }),
      session.request('/admin/absence/status', { signal }),
      session.request('/admin/absence/runs?limit=3', { signal }),
    ]);
    if (!signal?.aborted && current === version.current) { setRows(items); setStatus(nextStatus); setRuns(nextRuns); setError(''); }
  }
  useEffect(() => {
    const controller = new AbortController();
    query.current = controller;
    setOperation(null); setHistory(null); setNotice(''); setRows([]);
    const reload = () => { if (!pending.current) refresh(controller.signal).catch(failure => { if (!controller.signal.aborted) setError(failure.message); }); };
    reload();
    const timer = setInterval(reload, 5000);
    return () => { controller.abort(); clearInterval(timer); };
  }, [session, filter, offset]);

  async function act(work, message) {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError(''); setNotice('');
    const signal = query.current?.signal;
    try {
      await work(signal);
      if (!signal?.aborted) { await refresh(signal); setNotice(message); }
    } catch (failure) { if (!signal?.aborted) setError(failure.message); }
    finally { pending.current = false; if (!signal?.aborted) setBusy(false); }
  }
  function open(row, target) { setOperation({ row, target }); setNote(''); setHistory(null); }
  return <section className="management status-card" aria-label="Acompanhamento de ausências" aria-busy={busy}>
    <h2>Acompanhamento de ausências</h2>
    <p className="hint">Alunos elegíveis com 10 dias completos sem presença. Um novo check-in resolve o caso aberto. Nenhuma mensagem é enviada.</p>
    {error && <p className="error" role="alert">{error}</p>}
    {notice && <p className="success" role="status">{notice}</p>}
    {status && <>
      {!status.enabled && <p>Detecção de ausências desativada na configuração.</p>}
      <p>Última verificação: {stamp(status.last_success_at)}</p>
      {status.enabled && !status.activated_at && <p>A primeira verificação inicia a carência de 10 dias para os cadastros existentes.</p>}
      {status.last_error_code && <p className="error">A última verificação falhou. Próxima tentativa a partir de {stamp(status.next_attempt_at)}.</p>}
    </>}
    <fieldset disabled={busy}><legend className="sr-only">Fila de acompanhamento</legend>
      <div className="actions"><button type="button" disabled={!status?.enabled} onClick={() => act(signal => session.request('/admin/absence/scan', { method: 'POST', signal }), 'Verificação solicitada. Acompanhe a lista e as execuções abaixo.')}>Verificar ausências</button>
        <button type="button" className="secondary" onClick={() => act(async () => {}, 'Acompanhamentos atualizados.')}>Atualizar acompanhamentos</button></div>
      <label htmlFor="followup-status">Situação do acompanhamento</label>
      <select id="followup-status" value={filter} onChange={event => { setFilter(event.target.value); setOffset(0); }}>
        <option value="">Todas</option>{Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
      {!rows.length && <p>Nenhum acompanhamento nesta consulta.</p>}
      <ul className="record-list">{rows.map(row => <li key={row.id}><div><strong>{row.student_name}</strong><p>{labels[row.status]}</p>
        <p className="hint">Contagem iniciada em {stamp(row.baseline_at)}<br />Identificado em {stamp(row.detected_at)}</p>
        {row.assigned_to && <p>Responsável: {row.assigned_to === userId ? 'você' : 'outro administrador'}</p>}
        {row.last_note && <p>{row.last_note}</p>}
        <div className="actions">
          {['pendente', 'em_acompanhamento'].includes(row.status) && <>
            {row.status === 'pendente' ? <button type="button" onClick={() => open(row, 'em_acompanhamento')}>Assumir acompanhamento</button>
              : <button type="button" className="secondary" onClick={() => open(row, 'pendente')}>Devolver à fila</button>}
            <button type="button" className="secondary" onClick={() => open(row, 'resolvido')}>Resolver acompanhamento</button>
            <button type="button" className="secondary" onClick={() => open(row, 'encerrado')}>Encerrar acompanhamento</button>
          </>}
          <button type="button" className="secondary" onClick={() => act(async signal => {
            const events = await loadCollection(session, `/admin/history?entity_type=absence_detection&entity_id=${row.id}`, signal);
            if (!signal?.aborted) { setHistory({ row, events }); setOperation(null); }
          }, 'Histórico consultado.')}>Histórico do acompanhamento</button>
        </div></div></li>)}</ul>
      <div className="actions"><button type="button" className="secondary" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 20))}>Acompanhamentos anteriores</button>
        <button type="button" className="secondary" disabled={rows.length < 20} onClick={() => setOffset(offset + 20)}>Mais acompanhamentos</button></div>
      {operation && <form onSubmit={event => {
        event.preventDefault();
        void act(async signal => {
          await session.request(`/admin/absence/detections/${operation.row.id}/status`, { method: 'POST', signal,
            body: { status: operation.target, expected_version: operation.row.version, note } });
          if (!signal?.aborted) setOperation(null);
        }, 'Acompanhamento atualizado com histórico.');
      }}><h3>{labels[operation.target]}: {operation.row.student_name}</h3>
        <label htmlFor="followup-note">Observação do acompanhamento</label>
        <textarea id="followup-note" required minLength={3} maxLength={500} value={note} onChange={event => setNote(event.target.value)} />
        <div className="actions"><button>Confirmar acompanhamento</button><button type="button" className="secondary" onClick={() => setOperation(null)}>Voltar aos acompanhamentos</button></div>
      </form>}
      {history && <section aria-label="Histórico do acompanhamento"><h3>Histórico de {history.row.student_name}</h3>
        <ol>{history.events.map(event => <li key={event.id}>{stamp(event.created_at)} · {event.actor_type === 'system' ? 'Sistema' : 'Administrador'} · {event.reason || 'Ausência identificada'}</li>)}</ol>
        <button type="button" className="secondary" onClick={() => setHistory(null)}>Fechar histórico do acompanhamento</button></section>}
      <details><summary>Últimas verificações</summary><ul>{runs.map(run => <li key={run.id}>{stamp(run.started_at)} · {{ running: 'Em execução', completed: 'Concluída', failed: 'Falhou', interrupted: 'Interrompida' }[run.status]} · {run.processed} aluno(s), {run.detected} ausência(s)</li>)}</ul></details>
    </fieldset>
  </section>;
}
