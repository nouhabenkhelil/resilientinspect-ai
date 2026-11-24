import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

describe('Industrial BFF requests', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv('VITE_PORTAL_MODE', 'true');
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });
  it('uses same-origin cookies and memory-only CSRF for writes', async () => {
    const storage = vi.spyOn(Storage.prototype, 'setItem');
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'ok' })));
    vi.stubGlobal('fetch', fetch);
    const { setCsrf, authHeaders, portalRequest } = await import('./session');
    setCsrf('isolated-csrf');
    expect(authHeaders()).toEqual({});
    await portalRequest('/api/auth/logout', { method: 'POST' });
    expect(fetch).toHaveBeenCalledWith(
      '/api/auth/logout',
      expect.objectContaining({
        credentials: 'same-origin',
        headers: { 'X-CSRF-Token': 'isolated-csrf' },
      }),
    );
    expect(storage).not.toHaveBeenCalled();
    storage.mockRestore();
  });
  it('signals 401 so the authenticated view is discarded', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ message: 'Connexion requise.' }), { status: 401 }),
        ),
    );
    const invalid = vi.fn();
    window.addEventListener('ri-session-expired', invalid);
    const { portalRequest } = await import('./session');
    await expect(portalRequest('/api/inspections')).rejects.toThrow('Connexion requise.');
    expect(invalid).toHaveBeenCalledOnce();
    window.removeEventListener('ri-session-expired', invalid);
  });
  it('refuses destinations outside the BFF before fetching', async () => {
    const fetch = vi.fn();
    vi.stubGlobal('fetch', fetch);
    const { portalRequest } = await import('./session');
    for (const path of ['https://evil.invalid', '//evil.invalid', '/api/https://evil.invalid']) {
      await expect(portalRequest(path)).rejects.toThrow('Destination non autorisée.');
    }
    expect(fetch).not.toHaveBeenCalled();
  });
  it('preserves the legacy demonstrator request behavior', async () => {
    vi.stubEnv('VITE_PORTAL_MODE', 'false');
    const { authHeaders, setCsrf } = await import('./session');
    setCsrf('isolated');
    expect(authHeaders('POST')).toEqual({});
  });
  it('discards history responses that finish after logout or an account change', async () => {
    let complete!: (value: Response) => void;
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(
        () =>
          new Promise<Response>((resolve) => {
            complete = resolve;
          }),
      ),
    );
    const { clearPortalHistory, refreshPortalHistory, readHistory } =
      await import('../studio/history');
    const pending = refreshPortalHistory();
    clearPortalHistory();
    complete(
      new Response(
        JSON.stringify({ items: [{ request_id: 'old-account', created_at: '2026-01-01' }] }),
      ),
    );
    await pending;
    expect(readHistory()).toEqual([]);
  });
});
