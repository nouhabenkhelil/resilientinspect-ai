import type {
  Health,
  InspectionInput,
  Metadata,
  Prediction,
  VisualizedPrediction,
} from './contracts';

export class ApiError extends Error {
  constructor(
    message: string,
    public status = 0,
    public code = 'network_error',
    public requestId?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/+$/, '');

async function request<T>(
  path: string,
  options: RequestInit = {},
  degradedHealth = false,
): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  const callerSignal = options.signal;
  if (callerSignal?.aborted) controller.abort();
  callerSignal?.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(abort, path.startsWith('/predict') ? 120_000 : 10_000);
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      signal: controller.signal,
    });
    const body = await response.json().catch(() => null);
    // /health documente une réponse HealthResponse en HTTP 503.
    const isDegraded = degradedHealth && response.status === 503 && body?.status === 'degraded';
    if (!response.ok && !isDegraded) {
      throw new ApiError(
        body?.message || `Le serveur a renvoyé une erreur HTTP ${response.status}.`,
        response.status,
        body?.code || 'http_error',
        body?.request_id || response.headers.get('X-Request-ID') || undefined,
      );
    }
    if (!body || typeof body !== 'object')
      throw new ApiError('Réponse JSON du serveur illisible.', response.status, 'invalid_response');
    return body as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (callerSignal?.aborted) throw new DOMException('Requête annulée', 'AbortError');
    if (controller.signal.aborted)
      throw new ApiError('Le délai de réponse du serveur est dépassé. Réessayez.', 0, 'timeout');
    throw new ApiError(
      'Serveur injoignable. Vérifiez que FastAPI est démarré et que l’URL API est correcte.',
    );
  } finally {
    clearTimeout(timer);
    callerSignal?.removeEventListener('abort', abort);
  }
}

function multipart(input: InspectionInput): FormData {
  const body = new FormData();
  body.append('file', input.file);
  body.append('category', input.category);
  body.append('model', input.model);
  if (input.engine) body.append('engine', input.engine);
  return body;
}

export const api = {
  health: (signal?: AbortSignal) => request<Health>('/health', { signal }, true),
  metadata: (signal?: AbortSignal) => request<Metadata>('/model/metadata', { signal }),
  predict: (input: InspectionInput, signal?: AbortSignal) =>
    request<Prediction>('/predict', {
      method: 'POST',
      body: multipart(input),
      signal,
    }),
  visualize: (input: InspectionInput, signal?: AbortSignal) =>
    request<VisualizedPrediction>('/predict/visualize', {
      method: 'POST',
      body: multipart(input),
      signal,
    }),
};

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Une erreur inattendue est survenue.';
}
