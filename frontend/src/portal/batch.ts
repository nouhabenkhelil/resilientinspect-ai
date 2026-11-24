import { expired, portalRequest, authHeaders } from './session';
import { validateFile, validateImage } from '../image';
export interface BatchLimits {
  max_images: number;
  max_file_bytes: number;
  max_batch_bytes: number;
  max_pixels: number;
  image_retention_hours: number;
  result_retention_days: number;
  storage: string;
}
export interface Batch {
  id: string;
  owner_id: string;
  model: string;
  category: string;
  engine: string;
  status: string;
  total: number;
  processed: number;
  normal_count: number;
  anomaly_count: number;
  error_count: number;
  cancelled_count: number;
  created_at: string;
  images_expires_at: string;
  results_expires_at: string;
}
export interface BatchItem {
  id: string;
  position: number;
  filename: string;
  status: string;
  attempts: number;
  decision: string | null;
  anomaly_score: number | null;
  threshold: number | null;
  engine: string | null;
  inference_time_ms: number | null;
  version: string | null;
  file_sha256: string;
  image_available: boolean;
  error: { code: string } | null;
}
export const terminalBatch = (status: string) =>
  ['completed', 'completed_with_errors', 'failed', 'cancelled'].includes(status);
export const batchStatus: Record<string, string> = {
  queued: 'En attente',
  running: 'En cours',
  retrying: 'Nouvelle tentative',
  cancelling: 'Annulation en cours',
  cancelled: 'Annulé',
  completed: 'Terminé',
  completed_with_errors: 'Terminé avec erreurs',
  failed: 'En erreur',
};
export async function checkBatchFiles(files: File[], limits: BatchLimits) {
  if (!files.length || files.length > limits.max_images)
    throw new Error(`Choisissez de 1 à ${limits.max_images} images.`);
  if (files.reduce((sum, f) => sum + f.size, 0) > limits.max_batch_bytes)
    throw new Error('La taille totale du lot dépasse la limite.');
  for (const file of files) {
    validateFile(file);
    if (file.size > limits.max_file_bytes)
      throw new Error(`${file.name} dépasse la taille autorisée.`);
    const url = URL.createObjectURL(file);
    try {
      const size = await validateImage(url);
      if (size.width * size.height > limits.max_pixels) throw new Error('Dimensions trop grandes.');
    } finally {
      URL.revokeObjectURL(url);
    }
  }
}
export function submitBatch(
  files: File[],
  model: string,
  category: string,
  engine: string,
  key: string,
) {
  const form = new FormData();
  form.set('model', model);
  form.set('category', category);
  form.set('engine', engine);
  for (const file of files) form.append('files', file);
  return portalRequest<Batch>('/api/batches', {
    method: 'POST',
    body: form,
    headers: { 'Idempotency-Key': key },
  });
}
export async function exportBatch(id: string) {
  const response = await fetch(`/api/batches/${id}/export.csv`, {
    credentials: 'same-origin',
    headers: authHeaders(),
  });
  if (response.status === 401) expired();
  if (!response.ok) throw new Error(`Export refusé (${response.status}).`);
  const blob = await response.blob(),
    url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `batch-${id}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}
