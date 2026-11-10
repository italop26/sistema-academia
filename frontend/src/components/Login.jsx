import { useState } from 'react';

export default function Login({ session, state }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const busy = ['authenticating', 'signingOut'].includes(state.status);
  function submit(event) {
    event.preventDefault();
    const secret = password;
    setPassword('');
    void session.login(email, secret);
  }
  return (
    <section className="login-layout">
      <div className="intro"><p className="eyebrow">GESTÃO EM MOVIMENTO</p><h1>Seu espaço.<br />Sua gestão.</h1><p className="description">Acesse o ambiente administrativo da sua academia ou estúdio de Pilates.</p></div>
      <section className="status-card login-card" aria-labelledby="login-title" aria-busy={busy}>
        <p className="eyebrow">ACESSO RESTRITO</p><h2 id="login-title">Entrar no sistema</h2>
        <p className="hint">Use a conta de administrador cadastrada para sua unidade.</p>
        {state.error && <p className="error" role="alert">{state.error}</p>}
        <form onSubmit={submit}>
          <label htmlFor="email">E-mail</label>
          <input id="email" type="email" autoComplete="username" required maxLength={254} value={email} onChange={(event) => setEmail(event.target.value)} disabled={busy} />
          <label htmlFor="password">Senha</label>
          <input id="password" type="password" autoComplete="current-password" required maxLength={128} value={password} onChange={(event) => setPassword(event.target.value)} disabled={busy} />
          <button type="submit" disabled={busy}>{busy ? 'Aguarde…' : 'Entrar'}</button>
          {busy && <p role="status" className="hint">{state.status === 'signingOut' ? 'Encerrando sessão…' : 'Validando acesso…'}</p>}
        </form>
      </section>
    </section>
  );
}
