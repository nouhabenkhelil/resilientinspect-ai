import type { Prediction } from '../api/contracts';

export type HistoryEntry = Prediction & {
  recorded_at: string;
  round_trip_ms: number;
  session: string;
  endpoint?: '/predict' | '/predict/visualize';
};
const KEY = 'ri.inspections.v2';
export const SESSION = crypto.randomUUID();
export function readHistory(): HistoryEntry[] {
  try {
    const entries: unknown = JSON.parse(localStorage.getItem(KEY) || '[]');
    if (!Array.isArray(entries)) return [];
    return entries
      .filter(
        (r): r is HistoryEntry =>
          r &&
          typeof r === 'object' &&
          typeof r.request_id === 'string' &&
          typeof r.recorded_at === 'string' &&
          ['B0', 'A1', 'T0', 'T1', 'T2'].includes(r.model) &&
          ['bottle', 'leather', 'hazelnut'].includes(r.category) &&
          ['normal', 'anomaly'].includes(r.decision) &&
          Number.isFinite(r.anomaly_score) &&
          Number.isFinite(r.threshold) &&
          Number.isFinite(r.inference_time_ms) &&
          typeof r.version === 'string' &&
          Number.isFinite(r.round_trip_ms),
      )
      .map((r) => ({ ...r, engine: r.engine || 'pytorch' }))
      .slice(0, 200);
  } catch {
    return [];
  }
}
export function recordInspection(
  result: Prediction,
  elapsed: number,
  endpoint: '/predict' | '/predict/visualize' = '/predict',
) {
  const entry: HistoryEntry = {
    ...result,
    recorded_at: new Date().toISOString(),
    round_trip_ms: elapsed,
    session: SESSION,
    endpoint,
  };
  // Store only a whitelist, never uploads, filenames or visualization base64.
  const {
    category,
    model,
    version,
    anomaly_score,
    threshold,
    decision,
    inference_time_ms,
    request_id,
    recorded_at,
    round_trip_ms,
    session,
  } = entry;
  try {
    localStorage.setItem(
      KEY,
      JSON.stringify(
        [
          {
            category,
            model,
            version,
            anomaly_score,
            threshold,
            decision,
            inference_time_ms,
            request_id,
            recorded_at,
            round_trip_ms,
            session,
            endpoint,
            engine: result.engine || 'pytorch',
          },
          ...readHistory().filter((r) => r.request_id !== request_id),
        ].slice(0, 200),
      ),
    );
  } catch {
    window.dispatchEvent(new CustomEvent('ri-storage-error'));
  }
  window.dispatchEvent(new CustomEvent('ri-history'));
}
export function clearHistory() {
  localStorage.removeItem(KEY);
  window.dispatchEvent(new CustomEvent('ri-history'));
}
export function download(data: string, name: string, mime = 'application/json') {
  const url = URL.createObjectURL(new Blob([data], { type: mime }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function exportHistory(entries: HistoryEntry[], format: 'json' | 'csv') {
  const keys: (keyof HistoryEntry)[] = [
    'recorded_at',
    'category',
    'model',
    'decision',
    'anomaly_score',
    'threshold',
    'inference_time_ms',
    'round_trip_ms',
    'endpoint',
    'engine',
    'request_id',
    'version',
  ];
  const csv = [
    keys.join(','),
    ...entries.map((r) => keys.map((k) => `"${String(r[k]).replace(/"/g, '""')}"`).join(',')),
  ].join('\n');
  download(
    format === 'json' ? JSON.stringify(entries, null, 2) : csv,
    `resilientinspect-history.${format}`,
    format === 'csv' ? 'text/csv;charset=utf-8' : 'application/json',
  );
}
