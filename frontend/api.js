export class ApiError extends Error {
  constructor(message, status = 0) { super(message); this.status = status; }
}
export function createApi(base, token) {
  const root = base.replace(/\/$/, '');
  const session = new AbortController();
  async function request(path, { method = 'GET', body, key, signal } = {}) {
    const timeout = AbortSignal.timeout(15000);
    let response;
    try {
      response = await fetch(root + path, { method, credentials:'same-origin', signal: AbortSignal.any([session.signal, timeout, ...(signal ? [signal] : [])]),
        headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(body ? { 'Content-Type': 'application/json' } : {}), ...(key ? { 'Idempotency-Key': key } : {}) },
        body: body === undefined ? undefined : JSON.stringify(body) });
    } catch (error) {
      if (signal?.aborted || session.signal.aborted) throw error;
      throw new ApiError('Сервер недоступен или время ожидания истекло. Проверьте адрес и подключение.');
    }
    let data;
    try { data = await response.json(); } catch { throw new ApiError('Сервер вернул некорректный ответ.', response.status); }
    if (!response.ok) {
      const detail = data.detail;
      const message = Array.isArray(detail) ? detail.map(x => `${x.loc.join('.')}: ${x.msg}`).join('; ') : detail?.message || (typeof detail === 'string' ? detail : 'Ошибка запроса.');
      throw new ApiError(`${response.status}: ${message}`, response.status);
    }
    return data;
  }
  const employeePath = id => '/employees/' + encodeURIComponent(id);
  return {
    abort: () => session.abort(),
    authConfig: () => request('/auth/config'),
    me: () => request('/auth/me'),
    login: () => request('/auth/login', {method:'POST'}),
    demoLogin: body => request('/auth/demo', {method:'POST',body}),
    logout: () => request('/auth/logout', {method:'POST'}),
    health: () => request('/health'),
    profile: (id, signal) => request(employeePath(id), { signal }),
    recommendations: (id, signal) => request(employeePath(id) + '/recommendations', { signal }),
    complete: (id, event, attempt) => request(employeePath(id) + '/activities/' + encodeURIComponent(event) + '/complete', { method: 'POST', body: attempt.body, key: attempt.key }),
    goal: (id, body) => request(employeePath(id) + '/goal', { method: 'POST', body }),
    overview: () => request('/hr/overview'),
    importProfiles: body => request('/imports', { method: 'POST', body }),
    // Employee identity is in the authorized URL; provider keys stay on the server.
    chat: (id, body, signal) => request(employeePath(id) + '/chat', { method: 'POST', body, signal }),
  };
}
