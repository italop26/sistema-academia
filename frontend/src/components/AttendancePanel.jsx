import { useEffect, useRef, useState } from 'react';
import { loadCollection, newRequestId } from '../api/business.js';

const stamp = value => value ? new Date(value).toLocaleString('pt-BR', { timeZone: 'America/Fortaleza' }) : 'Nenhuma visita';

export default function AttendancePanel({ session }) {
  const [students, setStudents] = useState([]);
  const [studentId, setStudentId] = useState('');
  const [enrollments, setEnrollments] = useState([]);
  const [enrollmentId, setEnrollmentId] = useState('');
  const [summary, setSummary] = useState(null);
  const [visits, setVisits] = useState([]);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [operation, setOperation] = useState(null);
  const [reason, setReason] = useState('');
  const query = useRef(null);
  const pending = useRef(false);
  const checkInKey = useRef(null);
  const suspensionKey = useRef(null);

  async function loadStudents(signal) {
    const rows = await loadCollection(session, '/admin/students', signal);
    if (!signal?.aborted) setStudents(rows);
  }
  useEffect(() => {
    const controller = new AbortController();
    loadStudents(controller.signal).catch(failure => { if (!controller.signal.aborted) setError(failure.message); });
    return () => controller.abort();
  }, [session]);

  async function refresh(signal) {
    if (!studentId) return;
    const [nextSummary, nextVisits, contracts] = await Promise.all([
      session.request(`/admin/attendance/students/${studentId}`, { signal }),
      session.request(`/admin/attendance/students/${studentId}/check-ins?offset=${offset}&limit=20`, { signal }),
      loadCollection(session, `/admin/enrollments?student_id=${studentId}`, signal),
    ]);
    const detailed = await Promise.all(contracts.map(async contract => ({ ...contract,
      suspensions: await session.request(`/admin/enrollments/${contract.id}/suspensions`, { signal }),
    })));
    if (signal?.aborted) return;
    setSummary(nextSummary); setVisits(nextVisits); setEnrollments(detailed);
    setEnrollmentId(current => detailed.some(row => row.id === current) ? current : detailed.find(row => row.status === 'ativa')?.id || '');
  }
  useEffect(() => {
    const controller = new AbortController();
    query.current = controller;
    setError(''); setNotice(''); setSummary(null); setVisits([]); setEnrollments([]);
    setOperation(null); setLoading(Boolean(studentId));
    checkInKey.current = null; suspensionKey.current = null;
    refresh(controller.signal).catch(failure => { if (!controller.signal.aborted) setError(failure.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [studentId, offset, session]);

  async function act(work, message) {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError(''); setNotice('');
    const signal = query.current?.signal;
    try {
      await work(signal);
      if (!signal?.aborted) { await refresh(signal); setNotice(message); setOperation(null); setReason(''); }
    } catch (failure) { if (!signal?.aborted) setError(failure.message); }
    finally { pending.current = false; if (!signal?.aborted) setBusy(false); }
  }

  const selected = enrollments.find(row => row.id === enrollmentId);
  const suspension = selected?.suspensions.find(row => !row.ends_at);
  return <section className="management status-card" aria-label="Frequência dos alunos" aria-busy={busy || loading}>
    <h2>Frequência dos alunos</h2>
    <p className="hint">Uma presença por aluno por dia, no horário de Fortaleza. Suspensões afetam a frequência e preservam as cobranças existentes.</p>
    {error && <p className="error" role="alert">{error}</p>}
    {notice && <p className="success" role="status">{notice}</p>}
    <fieldset disabled={busy || loading}>
      <legend className="sr-only">Presença e suspensão</legend>
      <button type="button" className="secondary" onClick={() => act(signal => loadStudents(signal), 'Lista de alunos atualizada.')}>Atualizar alunos da frequência</button>
      <label htmlFor="attendance-student">Aluno da frequência</label>
      <select id="attendance-student" value={studentId} onChange={event => { setStudentId(event.target.value); setOffset(0); setEnrollmentId(''); }}>
        <option value="">Selecione um aluno</option>
        {students.map(student => <option key={student.id} value={student.id}>{student.name}{!student.is_active ? ' (inativo)' : ''}</option>)}
      </select>
      {summary && <>
        <p>Última visita: <strong>{stamp(summary.last_visit)}</strong></p><p>Total de presenças: {summary.total_visits}</p>
        <label htmlFor="attendance-enrollment">Matrícula da frequência</label>
        <select id="attendance-enrollment" value={enrollmentId} onChange={event => { setEnrollmentId(event.target.value); checkInKey.current = null; setOperation(null); }}>
          <option value="">Selecione uma matrícula</option>
          {enrollments.map(row => <option key={row.id} value={row.id}>{row.starts_on} · vencimento dia {row.due_day} · {row.status}{row.suspensions.some(period => !period.ends_at) ? ' · suspensa para frequência' : ''}</option>)}
        </select>
        <div className="actions">
          <button type="button" disabled={!selected || selected.status !== 'ativa' || Boolean(suspension)} onClick={() => act(async signal => {
            checkInKey.current ||= newRequestId();
            await session.request('/admin/attendance/check-ins', { method: 'POST', signal,
              body: { student_id: studentId, enrollment_id: enrollmentId, idempotency_key: checkInKey.current } });
            checkInKey.current = null;
          }, 'Presença confirmada. Repetições no mesmo dia preservam um único registro.')}>Registrar presença</button>
          {selected?.status === 'ativa' && <button type="button" className="secondary" onClick={() => { setOperation(suspension ? 'resume' : 'suspend'); setReason(''); suspensionKey.current = newRequestId(); }}>{suspension ? 'Retomar frequência' : 'Suspender frequência'}</button>}
        </div>
        {operation && <form onSubmit={event => {
          event.preventDefault();
          void act(signal => session.request(operation === 'suspend' ? `/admin/enrollments/${enrollmentId}/suspend`
            : `/admin/enrollments/${enrollmentId}/suspensions/${suspension.id}/resume`, {
            method: 'POST', signal, body: { reason, ...(operation === 'suspend' ? { request_key: suspensionKey.current } : {}) },
          }), operation === 'suspend' ? 'Frequência suspensa com histórico.' : 'Frequência retomada com histórico.');
        }}><label htmlFor="attendance-reason">Motivo da alteração de frequência</label>
          <textarea id="attendance-reason" required minLength={3} maxLength={500} value={reason} onChange={event => setReason(event.target.value)} />
          <div className="actions"><button>Confirmar alteração de frequência</button><button type="button" className="secondary" onClick={() => setOperation(null)}>Voltar à frequência</button></div>
        </form>}
        <h3>Histórico de presenças</h3>
        {!visits.length && <p>Nenhuma presença nesta consulta.</p>}
        <ul className="record-list">{visits.map(visit => <li key={visit.id}><div><strong>{stamp(visit.occurred_at)}</strong><p>Dia local: {visit.local_day}</p></div></li>)}</ul>
        <div className="actions"><button type="button" className="secondary" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 20))}>Presenças anteriores</button>
          <button type="button" className="secondary" disabled={visits.length < 20} onClick={() => setOffset(offset + 20)}>Mais presenças</button></div>
        {selected && <><h3>Histórico de suspensões</h3><ul className="record-list">{selected.suspensions.map(period => <li key={period.id}><div><strong>{period.ends_at ? 'Retomada' : 'Suspensão em andamento'}</strong><p>{stamp(period.starts_at)}{period.ends_at ? ` até ${stamp(period.ends_at)}` : ''}</p><p>{period.reason}</p></div></li>)}</ul></>}
      </>}
    </fieldset>
  </section>;
}
