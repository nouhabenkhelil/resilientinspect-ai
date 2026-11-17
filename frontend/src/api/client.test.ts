import { api, ApiError } from './client';
import { health, metadata, prediction, requestId, visualization } from '../test/fixtures';

const input = {
  file: new File(['png'], 'piece.png', { type: 'image/png' }),
  model: 'B0' as const,
  category: 'bottle' as const,
};
function reply(body: unknown, status = 200) {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status }));
  vi.stubGlobal('fetch', fetcher);
  return fetcher;
}

describe('service API FastAPI', () => {
  it('interroge /health et /model/metadata sans préfixe backend inventé', async () => {
    const fetcher = reply(health);
    expect(await api.health()).toEqual(health);
    expect(fetcher.mock.calls[0][0]).toBe('/api/health');
    fetcher.mockResolvedValue(new Response(JSON.stringify(metadata)));
    expect(await api.metadata()).toEqual(metadata);
    expect(fetcher.mock.calls[1][0]).toBe('/api/model/metadata');
  });
  it('accepte le vrai HealthResponse dégradé en HTTP 503', async () => {
    const degraded = { ...health, status: 'degraded', ready_models: 3 };
    reply(degraded, 503);
    expect(await api.health()).toEqual(degraded);
  });
  it.each(['predict', 'visualize'] as const)(
    'envoie %s avec exactement les trois champs multipart',
    async (method) => {
      const result = method === 'predict' ? prediction : visualization();
      const fetcher = reply(result);
      expect(await api[method](input)).toEqual(result);
      const [url, options] = fetcher.mock.calls[0];
      expect(url).toBe(`/api/${method === 'predict' ? 'predict' : 'predict/visualize'}`);
      expect(options.method).toBe('POST');
      expect(options.headers).toBeUndefined(); // Le navigateur génère la boundary.
      const form = options.body as FormData;
      expect(Array.from(form.keys())).toEqual(['file', 'category', 'model']);
      expect((form.get('file') as File).name).toBe('piece.png');
      expect(form.get('model')).toBe('B0');
      expect(form.get('category')).toBe('bottle');
    },
  );
  it.each([400, 413, 415, 422, 500, 503])(
    'conserve le code, message et UUID des erreurs HTTP %i',
    async (status) => {
      reply({ code: 'test_error', message: 'Erreur du backend', request_id: requestId }, status);
      await expect(api.predict(input)).rejects.toMatchObject({
        status,
        code: 'test_error',
        message: 'Erreur du backend',
        requestId,
      });
    },
  );
  it('rend une erreur lisible pour une réponse HTML du proxy', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('<html>Bad gateway</html>', { status: 502 })),
    );
    await expect(api.predict(input)).rejects.toMatchObject({ status: 502, code: 'http_error' });
  });
  it('refuse une réponse non JSON en HTTP 200', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('not json')));
    await expect(api.health()).rejects.toMatchObject({ code: 'invalid_response' });
  });
  it('explique un serveur hors ligne', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(api.metadata()).rejects.toBeInstanceOf(ApiError);
    await expect(api.health()).rejects.toThrow('Serveur injoignable');
  });
  it('limite la durée de connexion et nettoie son timer', async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url, options) =>
          new Promise((_resolve, reject) => {
            options.signal.addEventListener('abort', () =>
              reject(new DOMException('aborted', 'AbortError')),
            );
          }),
      ),
    );
    const request = api.health();
    const assertion = expect(request).rejects.toMatchObject({ code: 'timeout' });
    await vi.advanceTimersByTimeAsync(10_000);
    await assertion;
    expect(vi.getTimerCount()).toBe(0);
  });
  it('respecte une annulation utilisateur', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url, options) =>
          new Promise((_resolve, reject) => {
            options.signal.addEventListener('abort', () =>
              reject(new DOMException('aborted', 'AbortError')),
            );
          }),
      ),
    );
    const controller = new AbortController();
    const request = api.predict(input, controller.signal);
    controller.abort();
    await expect(request).rejects.toMatchObject({ name: 'AbortError' });
  });
});
