import { useEffect, useState } from 'react';
import { createAuthApi } from './api/auth.js';
import { createSession } from './auth/session.js';
import Dashboard from './components/Dashboard.jsx';
import Login from './components/Login.jsx';

const apiUrl = import.meta.env.VITE_API_URL || '/api';
const session = createSession(createAuthApi(apiUrl));

export default function App() {
  const [state, setState] = useState(session.getState);

  useEffect(() => {
    const unsubscribe = session.subscribe(setState);
    const validate = () => { session.checkExpiration(); void session.validate(); };
    const onVisibility = () => { if (!document.hidden) validate(); };
    window.addEventListener('focus', validate);
    document.addEventListener('visibilitychange', onVisibility);
    const interval = setInterval(validate, 60000);
    return () => {
      unsubscribe();
      clearInterval(interval);
      window.removeEventListener('focus', validate);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, []);

  return (
    <main className="shell">
      <header className="brand"><span className="brand-mark" aria-hidden="true">A</span> Academias & Pilates</header>
      {state.status === 'authenticated' ? <Dashboard user={state.user} session={session} apiUrl={apiUrl} />
        : ['verifying', 'verificationError'].includes(state.status)
          ? <section className="status-card"><h1>Validando sessão</h1>{state.error ? <><p role="alert" className="error">{state.error}</p><button onClick={() => session.validate()}>Tentar novamente</button><button className="secondary" onClick={() => session.logout()}>Sair</button></> : <p role="status">Aguarde…</p>}</section>
          : <Login session={session} state={state} />}
      <footer>Academias e estúdios de Pilates <span>Estrutura inicial · v0.1.0</span></footer>
    </main>
  );
}
