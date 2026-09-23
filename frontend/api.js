export class ApiError extends Error {
  constructor(message, status = 0) { super(message); this.status = status; }
}
export function createApi(base, token) {
  const root = base.replace(/\/$/, '');
  async function request(path, { method = 'GET', body, key, signal } = {}) {
    const timeout = AbortSignal.timeout(15000);
    let response;
    try {
      response = await fetch(root + path, { method, signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
        headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(body ? { 'Content-Type': 'application/json' } : {}), ...(key ? { 'Idempotency-Key': key } : {}) },
        body: body === undefined ? undefined : JSON.stringify(body) });
    } catch (error) {
      if (signal?.aborted) throw error;
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
    health: () => request('/health'),
    profile: (id, signal) => request(employeePath(id), { signal }),
    recommendations: (id, signal) => request(employeePath(id) + '/recommendations', { signal }),
    complete: (id, event, attempt) => request(employeePath(id) + '/activities/' + encodeURIComponent(event) + '/complete', { method: 'POST', body: attempt.body, key: attempt.key }),
    goal: (id, body) => request(employeePath(id) + '/goal', { method: 'POST', body }),
    overview: () => request('/hr/overview'),
    importProfiles: body => request('/imports', { method: 'POST', body }),
    // Proposed endpoint. Enable UI only after the server implements docs/frontend-handoff.md.
    chat: (id, body, signal) => request(employeePath(id) + '/chat', { method: 'POST', body, signal }),
  };
}
