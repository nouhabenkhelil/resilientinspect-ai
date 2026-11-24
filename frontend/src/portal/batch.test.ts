import { beforeEach, afterEach, expect, it, vi } from 'vitest';
const request = vi.hoisted(() => vi.fn());
vi.mock('./session', () => ({ portalRequest: request, expired: vi.fn(), authHeaders: () => ({}) }));
vi.mock('../image', () => ({ validateFile: vi.fn(), validateImage: vi.fn().mockResolvedValue({ width: 8, height: 8 }) }));
import { checkBatchFiles, submitBatch, terminalBatch } from './batch';
const limits = { max_images: 2, max_file_bytes: 100, max_batch_bytes: 150, max_pixels: 100, image_retention_hours: 24, result_retention_days: 30, storage: 'ready' };
beforeEach(() => { request.mockReset(); URL.createObjectURL = vi.fn().mockReturnValue('blob:test'); URL.revokeObjectURL = vi.fn(); });
afterEach(() => vi.restoreAllMocks());
it('rejects excess file counts and total size before submission', async () => {
  const file = new File(['x'.repeat(80)], 'x.png');
  await expect(checkBatchFiles([file, file, file], limits)).rejects.toThrow('1 à 2');
  await expect(checkBatchFiles([file, file], limits)).rejects.toThrow('totale');
  expect(request).not.toHaveBeenCalled();
});
it('sends all original files with the same submission key for an HTTP retry', async () => {
  const files = [new File(['x'], 'x.png'), new File(['y'], 'y.png')];
  await submitBatch(files, 'B0', 'bottle', 'onnxruntime', 'fixed-test-key');
  const [path, options] = request.mock.calls[0];
  expect(path).toBe('/api/batches'); expect(options.headers['Idempotency-Key']).toBe('fixed-test-key');
  expect(options.body.getAll('files')).toEqual(files); expect(options.body.get('engine')).toBe('onnxruntime');
});
it('revokes temporary preview URLs and distinguishes pending states from terminal states', async () => {
  await checkBatchFiles([new File(['x'], 'x.png')], limits);
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test');
  expect(terminalBatch('running')).toBe(false); expect(terminalBatch('cancelling')).toBe(false); expect(terminalBatch('cancelled')).toBe(true);
});
