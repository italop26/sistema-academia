// O token fica somente nesta instância em memória, fora do estado serializável do React.
export function createSession(api, {
  now = Date.now,
  schedule = setTimeout,
  cancel = clearTimeout,
} = {}) {
  let token = null;
  let deadline = 0;
  let timer = null;
  let pending = null;
  let generation = 0;
  let state = { status: 'anonymous', user: null, error: '' };
  const listeners = new Set();
  const emit = (next) => {
    state = next;
    for (const listener of listeners) listener(state);
  };
  const clear = () => {
    generation += 1;
    pending?.abort();
    pending = null;
    cancel(timer);
    timer = null;
    token = null;
    deadline = 0;
  };
  const expire = () => {
    clear();
    emit({ status: 'anonymous', user: null, error: 'Sua sessão expirou. Entre novamente.' });
  };

  return {
    getState: () => state,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    dispose() { clear(); listeners.clear(); },
    checkExpiration() { if (token && now() >= deadline) expire(); },
    async login(email, password) {
      clear();
      const attempt = generation;
      pending = new AbortController();
      const signal = pending.signal;
      emit({ status: 'authenticating', user: null, error: '' });
      try {
        const started = now();
        const result = await api.login(email, password, signal);
        if (attempt !== generation) return;
        if (!result || typeof result.access_token !== 'string' || !result.access_token
          || result.token_type !== 'bearer' || !Number.isFinite(result.expires_in)
          || result.expires_in <= 0 || result.expires_in > 3600) {
          throw new Error('A API retornou uma sessão inválida.');
        }
        const user = await api.admin(result.access_token, signal);
        if (attempt !== generation) return;
        if (!user || user.role !== 'admin' || user.is_active !== true) {
          throw new Error('Este acesso exige uma conta de administrador.');
        }
        token = result.access_token;
        deadline = started + result.expires_in * 1000;
        if (now() >= deadline) { expire(); return; }
        timer = schedule(expire, deadline - now());
        pending = null;
        emit({ status: 'authenticated', user, error: '' });
      } catch (error) {
        if (attempt !== generation) return;
        clear();
        emit({ status: 'anonymous', user: null, error: error.message || 'Não foi possível entrar.' });
      }
    },
    async validate() {
      if (!token || !['authenticated', 'verificationError'].includes(state.status)) return;
      if (now() >= deadline) { expire(); return; }
      const attempt = generation;
      emit({ status: 'verifying', user: null, error: '' });
      try {
        const user = await api.admin(token);
        if (attempt !== generation) return;
        if (user?.role !== 'admin' || !user.is_active) { expire(); return; }
        emit({ status: 'authenticated', user, error: '' });
      } catch (error) {
        if (attempt !== generation) return;
        if (error.status === 401 || error.status === 403) { expire(); return; }
        emit({ status: 'verificationError', user: null, error: 'Não foi possível validar a sessão. Tente novamente.' });
      }
    },
    async logout() {
      const current = token;
      clear();
      const attempt = generation;
      emit({ status: 'signingOut', user: null, error: '' });
      let error = '';
      if (current) {
        try { await api.logout(current); } catch (failure) {
          if (failure.status !== 401) {
            error = 'A sessão foi encerrada neste navegador. Não foi possível confirmar a saída no servidor.';
          }
        }
      }
      if (attempt === generation) emit({ status: 'anonymous', user: null, error });
    },
  };
}
