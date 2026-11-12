export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

const messages = {
  absence_disabled: 'A detecção de ausências está desativada.',
  followup_changed: 'O acompanhamento foi atualizado. Atualize a lista antes de continuar.',
  attendance_ineligible: 'Aluno sem matrícula disponível para presença. Confira a vigência e as suspensões.',
  idempotency_conflict: 'Esta operação já foi registrada com dados diferentes. Atualize a consulta.',
  automation_disabled: 'A automação financeira está desativada.',
  reminder_not_retryable: 'Este lembrete não permite reabrir tentativas.',
  record_conflict: 'Registro duplicado ou relacionamento inválido.',
  not_found: 'O registro não foi encontrado.',
  inactive_record: 'Aluno e plano devem estar ativos.',
  invalid_competence: 'A competência deve estar dentro da vigência da matrícula ativa.',
  amount_mismatch: 'O valor informado difere do valor da mensalidade.',
  invalid_transition: 'Esta alteração não é permitida para o estado atual do registro.',
  database_busy: 'O banco está ocupado. Tente novamente.',
};

export function createHttpClient(baseUrl = '/api', fetcher = fetch) {
  return async function request(path, { token, body, signal, method = 'GET' } = {}) {
    const timeout = AbortSignal.timeout(10000);
    let response;
    try {
      response = await fetcher(`${baseUrl.replace(/\/$/, '')}${path}`, {
        method, signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
        headers: { ...(body ? { 'Content-Type': 'application/json' } : {}),
          ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        ...(body ? { body: JSON.stringify(body) } : {}),
        cache: 'no-store', credentials: 'omit',
      });
    } catch (error) {
      if (signal?.aborted) throw error;
      throw new ApiError(0, 'Não foi possível acessar a API. Tente novamente.');
    }
    if (!response.ok) {
      let code;
      try { code = (await response.json())?.error?.code; } catch { /* Use a generic message. */ }
      const generic = response.status === 401 ? 'E-mail ou senha inválidos.'
        : response.status === 403 ? 'Este acesso exige uma conta de administrador.'
          : response.status === 422 ? 'Confira os dados informados.'
            : 'Serviço indisponível. Tente novamente.';
      // Whitelist local messages; never echo arbitrary proxy/provider response bodies.
      throw new ApiError(response.status, messages[code] || generic);
    }
    if (response.status === 204) return null;
    try { return await response.json(); } catch {
      throw new ApiError(502, 'A API retornou uma resposta inválida.');
    }
  };
}
