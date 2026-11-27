import { act, fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ request: vi.fn(), submit: vi.fn(), export: vi.fn(), permissions: ['inspect'] as string[], running: false }));
vi.mock('./Auth', () => ({ usePortalAuth: () => ({ user: { permissions: mocks.permissions } }) }));
vi.mock('./session', () => ({ portalRequest: mocks.request }));
vi.mock('../image', () => ({ validateFile: vi.fn(), validateImage: vi.fn().mockResolvedValue({ width: 8, height: 8 }) }));
vi.mock('./batch', async (original) => ({ ...(await original<typeof import('./batch')>()), submitBatch: mocks.submit, exportBatch: mocks.export }));
import { BatchInspection } from './BatchInspection';
const pending = { id: 'batch-1', owner_id: 'owner', model: 'B0', category: 'bottle', engine: 'pytorch', status: 'queued', total: 2, processed: 0, normal_count: 0, anomaly_count: 0, error_count: 0, cancelled_count: 0, created_at: '2026-11-24T12:00:00Z' };
const done = { ...pending, status: 'completed', processed: 2, normal_count: 2 };
const item = { id: 'item-1', position: 1, filename: 'part.png', status: 'completed', attempts: 1, decision: 'normal', anomaly_score: 0.1, threshold: 0.2, engine: 'pytorch', inference_time_ms: 2, version: 'a'.repeat(64), file_sha256: 'b'.repeat(64), image_available: true, error: null };
describe('Batch Inspection', () => {
  beforeEach(() => {
    mocks.permissions = ['inspect']; mocks.running = false; mocks.request.mockReset(); mocks.submit.mockReset();
    URL.createObjectURL = vi.fn().mockReturnValue('blob:private-preview'); URL.revokeObjectURL = vi.fn();
    mocks.submit.mockResolvedValue(pending);
    mocks.export.mockReset().mockResolvedValue(undefined);
    mocks.request.mockImplementation((path: string) => {
      if (path.endsWith('/limits')) return Promise.resolve({ max_images: 50, max_file_bytes: 10485760, max_batch_bytes: 104857600, max_pixels: 20000000, image_retention_hours: 24, result_retention_days: 30, storage: 'ready' });
      if (path.includes('/metadata')) return Promise.resolve({ models: [{ model: 'B0', category: 'bottle', available_engines: ['pytorch', 'onnxruntime'] }] });
      if (path.includes('/cancel')) return Promise.resolve({ ...pending, status: 'cancelled', processed: 2, cancelled_count: 2 });
      if (path.includes('/items')) return Promise.resolve({ items: [item], total: 1 });
      if (path.includes('/progress')) return Promise.resolve(mocks.running ? pending : done);
      return Promise.resolve({ items: [pending], total: 1 });
    });
  });
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });
  it('uploads selected files and displays the real returned progress and results', async () => {
    render(<BatchInspection />);
    await waitFor(() => expect(screen.getByLabelText('Images du lot')).toBeEnabled());
    fireEvent.change(screen.getByLabelText('Images du lot'), { target: { files: [new File(['png'], 'part.png', { type: 'image/png' })] } });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Démarrer le lot' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Démarrer le lot' }));
    await waitFor(() => expect(screen.getByRole('progressbar')).toHaveAttribute('value', '2'));
    expect(mocks.submit).toHaveBeenCalledWith(expect.any(Array), 'B0', 'bottle', 'pytorch', expect.any(String));
    expect(screen.getByText('1. part.png')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Filtre des résultats du lot'), { target: { value: 'normal' } });
    await waitFor(() => expect(mocks.request).toHaveBeenCalledWith(expect.stringContaining('filter=normal'), expect.any(Object)));
  });
  it('cancels only after confirmation and uses the protected endpoint', async () => {
    mocks.running = true; vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<BatchInspection />);
    fireEvent.click(await screen.findByRole('button', { name: 'Ouvrir le lot batch-1' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Annuler le lot' }));
    await waitFor(() => expect(mocks.request).toHaveBeenCalledWith('/api/batches/batch-1/cancel', { method: 'POST' }));
  });
  it('keeps the batch view read-only for an auditor', async () => {
    mocks.permissions = [];
    render(<BatchInspection />);
    expect(screen.queryByRole('button', { name: 'Démarrer le lot' })).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole('button', { name: 'Ouvrir le lot batch-1' }));
    await screen.findByRole('progressbar');
    expect(screen.queryByRole('button', { name: 'Annuler le lot' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Expliquer' })).not.toBeInTheDocument();
  });
  it('shows CSV feedback only while the real export promise is pending', async () => {
    let finish: () => void = () => {};
    mocks.export.mockImplementation(() => new Promise<void>((resolve) => { finish = resolve; }));
    render(<BatchInspection />);
    fireEvent.click(await screen.findByRole('button', { name: 'Ouvrir le lot batch-1' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Exporter CSV' }));
    expect(screen.getByRole('button', { name: 'Préparation du CSV…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Préparation du CSV…' })).toHaveAttribute('aria-busy', 'true');
    expect(mocks.export).toHaveBeenCalledWith('batch-1');
    await act(async () => finish());
    expect(screen.getByRole('button', { name: 'Exporter CSV' })).toBeEnabled();
    expect(screen.getByText('CSV prêt : le téléchargement a été déclenché.')).toBeInTheDocument();
  });
});
