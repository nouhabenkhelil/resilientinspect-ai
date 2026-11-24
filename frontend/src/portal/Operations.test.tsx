import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock('./session', () => ({ portalRequest: mocks.request }));
import { Operations } from './Operations';
afterEach(() => {
  cleanup();
  mocks.request.mockReset();
});
it('renders measured values and unavailable measurements without invented telemetry', async () => {
  mocks.request.mockImplementation((url: string) =>
    Promise.resolve(
      url.endsWith('/events')
        ? { items: [] }
        : {
            measured_at: '2026-11-24T22:00:00Z',
            database_up: true,
            database_ms: 2,
            science_up: true,
            gateway_up: true,
            idp_up: true,
            worker_up: null,
            queue: null,
            storage: null,
            models: { pytorch: 15, onnxruntime: 14 },
            http: {
              window_seconds: 20,
              requests: 3,
              errors_5xx: 0,
              error_ratio: 0,
              mean_ms: 10,
              p95_ms: 12,
            },
          },
    ),
  );
  render(<Operations />);
  expect(await screen.findByText('15 / 14')).toBeInTheDocument();
  expect(screen.getAllByText('Non disponible').length).toBeGreaterThan(2);
  expect(screen.getByText('3 / 0')).toBeInTheDocument();
});
it('shows access failure', async () => {
  mocks.request.mockRejectedValue(new Error('forbidden'));
  render(<Operations />);
  expect(await screen.findByRole('alert')).toHaveTextContent('ne sont pas accessibles');
});
