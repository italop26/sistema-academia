import { createHttpClient } from './http.js';
export { ApiError } from './http.js';

export function createAuthApi(baseUrl = '/api', fetcher = fetch) {
  const request = createHttpClient(baseUrl, fetcher);

  return {
    request,
    login: (email, password, signal) => request('/auth/login', { method: 'POST', body: { email, password }, signal }),
    admin: (token, signal) => request('/auth/admin', { token, signal }),
    me: (token, signal) => request('/auth/me', { token, signal }),
    logout: (token, signal) => request('/auth/logout', { method: 'POST', token, signal }),
  };
}
