// No bearer token, session identifier or credential is stored by JavaScript.
export const PORTAL_MODE = import.meta.env.VITE_PORTAL_MODE === 'true';
export type PortalRole = 'admin' | 'ai_engineer' | 'operator' | 'auditor';
export interface PortalUser {
  id: string;
  name: string;
  email: string | null;
  role: PortalRole;
  enabled: boolean;
  permissions: string[];
}
let csrfToken = '';
export function setCsrf(value: string) {
  csrfToken = value;
}
export function authHeaders(method = 'GET'): Record<string, string> {
  return PORTAL_MODE && !['GET', 'HEAD', 'OPTIONS'].includes(method.toUpperCase())
    ? { 'X-CSRF-Token': csrfToken }
    : {};
}
export function expired() {
  window.dispatchEvent(new CustomEvent('ri-session-expired'));
}
export async function portalRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  if (!path.startsWith('/api/') || path.includes('://'))
    throw new Error('Destination non autorisée.');
  const response = await fetch(path, {
    ...options,
    credentials: 'same-origin',
    headers: { ...authHeaders(options.method), ...options.headers },
  });
  if (response.status === 401) expired();
  const result = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) throw new Error(result?.message || `Opération refusée (${response.status}).`);
  return result as T;
}
