export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

export function createAuthApi(baseUrl = '/api', fetcher = fetch) {
  async function request(path, { token, body, signal, method = 'GET' } = {}) {
    const timeout = AbortSignal.timeout(10000);
    let response;
    try {
      response = await fetcher(`${baseUrl.replace(/\/$/, '')}${path}`, {
        method,
        signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
        headers: {
          ...(body ? { 'Content-Type': 'application/json' } : {}),
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        ...(body ? { body: JSON.stringify(body) } : {}),
        cache: 'no-store',
        credentials: 'omit',
      });
    } catch (error) {
      if (signal?.aborted) throw error;
      throw new ApiError(0, 'Não foi possível acessar a API. Tente novamente.');
    }
    if (!response.ok) {
      const message = response.status === 401 ? 'E-mail ou senha inválidos.'
        : response.status === 403 ? 'Este acesso exige uma conta de administrador.'
          : response.status === 422 ? 'Confira os dados informados.'
            : 'Serviço indisponível. Tente novamente.';
      // Não repetimos corpos de erro, que podem conter dados internos de um proxy.
      throw new ApiError(response.status, message);
    }
    if (response.status === 204) return null;
    try {
      return await response.json();
    } catch {
      throw new ApiError(502, 'A API retornou uma resposta inválida.');
    }
  }

  return {
    login: (email, password, signal) => request('/auth/login', { method: 'POST', body: { email, password }, signal }),
    admin: (token, signal) => request('/auth/admin', { token, signal }),
    me: (token, signal) => request('/auth/me', { token, signal }),
    logout: (token, signal) => request('/auth/logout', { method: 'POST', token, signal }),
  };
}
