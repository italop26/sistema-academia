import { useEffect, useRef, useState } from 'react';
import { loadCollection, money, parseCents, statusLabel } from '../api/business.js';

const localDate = () => new Intl.DateTimeFormat('sv-SE', { timeZone: 'America/Fortaleza' }).format(new Date());
const dateLabel = (date) => date?.slice(0, 10).split('-').reverse().join('/') || '—';

export default function Management({ session }) {
  const [students, setStudents] = useState([]);
  const [plans, setPlans] = useState([]);
  const [enrollments, setEnrollments] = useState([]);
  const [fees, setFees] = useState([]);
  const [studentId, setStudentId] = useState('');
  const [competence, setCompetence] = useState(localDate().slice(0, 7));
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [history, setHistory] = useState(null);
  const [operation, setOperation] = useState(null);
  const [reason, setReason] = useState('');
  const [amount, setAmount] = useState('');
  const query = useRef(null);
  const actionPending = useRef(false);
  const selected = students.find((student) => student.id === studentId);

  async function refresh(signal) {
    const [allStudents, allPlans, allEnrollments, allFees] = await Promise.all([
      loadCollection(session, '/admin/students', signal),
      loadCollection(session, '/admin/plans', signal),
      studentId ? loadCollection(session, `/admin/enrollments?student_id=${studentId}`, signal) : [],
      studentId ? loadCollection(session, `/admin/monthly-fees?student_id=${studentId}&competence=${competence}`, signal) : [],
    ]);
    if (signal?.aborted) return;
    setStudents(allStudents); setPlans(allPlans); setEnrollments(allEnrollments); setFees(allFees);
  }

  useEffect(() => {
    const controller = new AbortController();
    query.current = controller;
    setLoading(true); setError(''); setHistory(null); setOperation(null); setNotice('');
    setEnrollments([]); setFees([]);
    refresh(controller.signal).catch((failure) => {
      if (!controller.signal.aborted) setError(failure.message);
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [studentId, competence, session]);

  async function act(work, message, { reload = true } = {}) {
    if (actionPending.current) return;
    actionPending.current = true;
    setBusy(true); setError(''); setNotice('');
    try {
      await work();
      if (reload) { setOperation(null); setHistory(null); setReason(''); await refresh(query.current?.signal); }
      setNotice(message);
    } catch (failure) { setError(failure.message); }
    finally { actionPending.current = false; setBusy(false); }
  }

  function submitCreate(event, kind) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form));
    void act(async () => {
      if (kind === 'students') {
        await session.request('/admin/students', {
          method: 'POST', body: { name: data.name, ...(data.email ? { email: data.email } : {}) },
        });
      } else if (kind === 'plans') {
        await session.request('/admin/plans', { method: 'POST', body: {
          name: data.name, monthly_amount_cents: parseCents(data.price),
        } });
      } else {
        await session.request('/admin/enrollments', { method: 'POST', body: {
          student_id: studentId, plan_id: data.plan_id, starts_on: data.starts_on,
          ends_on: data.ends_on || null, due_day: Number(data.due_day),
        } });
      }
      form.reset();
    }, 'Cadastro registrado com histórico.');
  }

  function openOperation(kind, item) {
    setOperation({ kind, item }); setHistory(null); setReason('');
    setAmount(item.amount_cents ? (item.amount_cents / 100).toFixed(2) : '');
  }

  function showHistory(kind, item) {
    void act(async () => {
      const events = await loadCollection(session, `/admin/history?entity_type=${kind}&entity_id=${item.id}`);
      setHistory({ kind, events }); setOperation(null);
    }, '', { reload: false });
  }

  function confirmOperation(event) {
    event.preventDefault();
    const { kind, item } = operation;
    const path = kind === 'pay' ? `/admin/monthly-fees/${item.id}/pay`
      : kind === 'cancel-fee' ? `/admin/monthly-fees/${item.id}/cancel`
        : kind === 'cancel-enrollment' ? `/admin/enrollments/${item.id}/cancel`
          : `/admin/${kind}/${item.id}/deactivate`;
    void act(() => session.request(path, { method: 'POST', body: kind === 'pay'
      ? { amount_cents: parseCents(amount), note: reason } : { reason } }),
    kind === 'pay' ? `Mensalidade de ${selected?.name} concluída. Pagamento e histórico registrados.`
      : 'Alteração registrada com histórico.');
  }

  return (
    <section className="management" aria-label="Gestão de matrículas e mensalidades" aria-busy={busy || loading}>
      <h2>Matrículas e mensalidades</h2>
      <p className="description">Cadastre alunos e planos, acompanhe as matrículas e registre os recebimentos.</p>
      {error && <p role="alert" className="error">{error}</p>}
      {notice && <p role="status" className="success">{notice}</p>}
      {loading && <p role="status">Carregando cadastros…</p>}
      <fieldset disabled={busy || loading}>
        <legend className="sr-only">Cadastros e cobranças</legend>
        <div className="management-grid">
          <form className="status-card" onSubmit={(event) => submitCreate(event, 'students')}>
            <h3>Novo aluno</h3>
            <label htmlFor="student-name">Nome do aluno</label><input id="student-name" name="name" required maxLength={100} />
            <label htmlFor="student-email">E-mail do aluno (opcional)</label><input id="student-email" name="email" type="email" maxLength={254} />
            <button>Cadastrar aluno</button>
          </form>
          <form className="status-card" onSubmit={(event) => submitCreate(event, 'plans')}>
            <h3>Novo plano</h3>
            <label htmlFor="plan-name">Nome do plano</label><input id="plan-name" name="name" required maxLength={100} />
            <label htmlFor="plan-price">Mensalidade do plano (R$)</label><input id="plan-price" name="price" inputMode="decimal" placeholder="199,90" required />
            <button>Cadastrar plano</button>
          </form>
        </div>
        <div className="filters">
          <div><label htmlFor="selected-student">Aluno em atendimento</label>
            <select id="selected-student" value={studentId} onChange={(event) => setStudentId(event.target.value)}>
              <option value="">Selecione um aluno</option>
              {students.map((student) => <option key={student.id} value={student.id}>{student.name}{student.email ? ` · ${student.email}` : ''}{!student.is_active ? ' (inativo)' : ''}</option>)}
            </select>
          </div>
          <div><label htmlFor="competence">Competência</label><input id="competence" type="month" value={competence} required onChange={(event) => { if (event.target.value) setCompetence(event.target.value); }} /></div>
        </div>
        {!students.length && !loading && <p>Nenhum aluno cadastrado.</p>}
        <details className="status-card"><summary>Planos cadastrados ({plans.length})</summary>
          <ul className="record-list">{plans.map((plan) => <li key={plan.id}>
            <span>{plan.name} · {money(plan.monthly_amount_cents)} · {plan.is_active ? 'Ativo' : 'Inativo'}</span>
            <div className="actions"><button type="button" className="secondary" onClick={() => showHistory('plan', plan)}>Histórico do plano</button>
              {plan.is_active && <button type="button" className="secondary" onClick={() => openOperation('plans', plan)}>Desativar plano</button>}</div>
          </li>)}</ul>
        </details>
        {selected && <>
          <div className="status-heading"><h3>Atendimento: {selected.name}</h3><div className="actions">
            <button type="button" className="secondary" onClick={() => showHistory('student', selected)}>Histórico do aluno</button>
            {selected.is_active && <button type="button" className="secondary" onClick={() => openOperation('students', selected)}>Desativar aluno</button>}
          </div></div>
          <form className="status-card" onSubmit={(event) => submitCreate(event, 'enrollments')}>
            <h3>Nova matrícula</h3>
            <label htmlFor="enrollment-plan">Plano da matrícula</label>
            <select id="enrollment-plan" name="plan_id" required defaultValue=""><option value="" disabled>Selecione um plano ativo</option>
              {plans.filter((plan) => plan.is_active).map((plan) => <option key={plan.id} value={plan.id}>{plan.name} · {money(plan.monthly_amount_cents)}</option>)}
            </select>
            <div className="management-grid">
              <div><label htmlFor="starts-on">Início da matrícula</label><input id="starts-on" name="starts_on" type="date" defaultValue={localDate()} required /></div>
              <div><label htmlFor="ends-on">Fim da matrícula (opcional)</label><input id="ends-on" name="ends_on" type="date" /></div>
              <div><label htmlFor="due-day">Dia do vencimento</label><input id="due-day" name="due_day" type="number" min="1" max="31" step="1" defaultValue="10" required /></div>
            </div>
            <p className="hint">O valor é preservado na matrícula. Meses curtos usam o último dia disponível; não há cobrança proporcional.</p>
            <button disabled={!selected.is_active || !plans.some((plan) => plan.is_active)}>Matricular aluno</button>
          </form>
          <h3>Matrículas do aluno</h3>
          {!enrollments.length && <p>Nenhuma matrícula para este aluno.</p>}
          <ul className="record-list">{enrollments.map((enrollment) => <li key={enrollment.id}>
            <span>{plans.find((plan) => plan.id === enrollment.plan_id)?.name || 'Plano'} · {money(enrollment.amount_cents)} · {enrollment.status === 'ativa' ? 'Ativa' : 'Cancelada'}<br />Início em {dateLabel(enrollment.starts_on)} · Vencimento dia {enrollment.due_day}</span>
            <div className="actions"><button type="button" className="secondary" onClick={() => showHistory('enrollment', enrollment)}>Histórico da matrícula</button>
              {enrollment.status === 'ativa' && <><button type="button" onClick={() => act(() => session.request('/admin/monthly-fees/generate', { method: 'POST', body: { enrollment_id: enrollment.id, competence } }), 'Mensalidade disponível. Competências já geradas são preservadas.')}>Gerar mensalidade</button>
                <button type="button" className="secondary" onClick={() => openOperation('cancel-enrollment', enrollment)}>Cancelar matrícula</button></>}
            </div>
          </li>)}</ul>
          <h3>Mensalidades de {selected.name} · {competence}</h3>
          {!fees.length && <p>Nenhuma mensalidade nesta competência.</p>}
          <div className="table-scroll"><table><caption className="sr-only">Mensalidades do aluno selecionado</caption>
            <thead><tr><th>Competência</th><th>Vencimento</th><th>Valor</th><th>Situação</th><th>Ações</th></tr></thead>
            <tbody>{fees.map((fee) => <tr key={fee.id}>
              <td>{fee.competence}</td><td>{dateLabel(fee.due_on)}</td><td>{money(fee.amount_cents)}</td>
              <td><span className={`badge ${fee.completed ? 'available' : fee.status === 'vencida' ? 'overdue' : ''}`}>{statusLabel(fee)}</span></td>
              <td><div className="actions"><button type="button" className="secondary" onClick={() => showHistory('monthly_fee', fee)}>Histórico</button>
                {['pendente', 'vencida'].includes(fee.status) && <><button type="button" onClick={() => openOperation('pay', fee)}>Registrar pagamento</button><button type="button" className="secondary" onClick={() => openOperation('cancel-fee', fee)}>Cancelar mensalidade</button></>}
              </div></td>
            </tr>)}</tbody>
          </table></div>
        </>}
        {operation && <form className="status-card operation" onSubmit={confirmOperation} aria-label="Confirmar alteração">
          <h3>{operation.kind === 'pay' ? 'Confirmar pagamento manual' : 'Confirmar alteração'}</h3>
          <p>{operation.kind === 'pay' || operation.kind === 'cancel-fee'
            ? `${operation.item.student_name} · ${operation.item.competence} · ${money(operation.item.amount_cents)}`
            : operation.item.name || selected?.name}</p>
          {operation.kind === 'pay' && <><label htmlFor="paid-amount">Valor recebido (R$)</label><input id="paid-amount" inputMode="decimal" value={amount} onChange={(event) => setAmount(event.target.value)} required /></>}
          <label htmlFor="operation-reason">{operation.kind === 'pay' ? 'Observação do recebimento' : 'Motivo da alteração'}</label>
          <textarea id="operation-reason" minLength={3} maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} required />
          <p className="hint">{operation.kind === 'pay' ? 'Confirme somente após verificar o recebimento. Esta ação conclui apenas esta mensalidade e não permite cancelamento direto posterior.' : 'O histórico será preservado. Cancelar uma matrícula não cancela mensalidades já emitidas.'}</p>
          <div className="actions"><button>Confirmar registro</button><button type="button" className="secondary" onClick={() => setOperation(null)}>Voltar</button></div>
        </form>}
        {history && <section className="status-card" aria-label="Histórico de alterações"><h3>Histórico de alterações</h3>
          {!history.events.length && <p>Nenhuma alteração registrada.</p>}
          <ol>{history.events.map((entry) => <li key={entry.id}>
            <strong>{{ created: 'Cadastro', deactivated: 'Desativação', cancelled: 'Cancelamento', issued: 'Emissão', paid: 'Pagamento concluído' }[entry.action] || entry.action}</strong>
            {' · '}{new Date(entry.created_at.endsWith('Z') || /[+-]\d\d:\d\d$/.test(entry.created_at) ? entry.created_at : `${entry.created_at}Z`).toLocaleString('pt-BR', { timeZone: 'America/Fortaleza' })}
            <p>Responsável: {entry.actor_type === 'system' ? 'Sistema' : entry.actor_id}{entry.reason ? ` · ${entry.reason}` : ''}</p>
            {entry.after.amount_cents && <p>Valor registrado: {money(entry.after.amount_cents)}</p>}
          </li>)}</ol>
          <button type="button" className="secondary" onClick={() => setHistory(null)}>Fechar histórico</button>
        </section>}
      </fieldset>
      {error && <button type="button" disabled={busy || loading} onClick={() => act(async () => {}, 'Dados atualizados.')}>Atualizar dados</button>}
    </section>
  );
}
