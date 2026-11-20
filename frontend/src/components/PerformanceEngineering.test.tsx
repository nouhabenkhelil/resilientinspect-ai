import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PerformanceEngineering } from './PerformanceEngineering';
import raw from '../data/onnx-performance.json';

test('performance engineering distinguishes measured technical results from classification', async () => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  render(<PerformanceEngineering />);
  expect(screen.getByRole('heading', { name: 'PyTorch / ONNX Runtime' })).toBeInTheDocument();
  expect(screen.getByText(/distinctes des performances de classification/)).toBeInTheDocument();
  if (raw.status !== 'measured') {
    expect(screen.getByText(/Aucun benchmark validé/)).toBeInTheDocument();
  } else {
    const table = screen.getByRole('table', { name: /Score complet/ });
    expect(within(table).getAllByRole('row').length).toBeGreaterThan(1);
    await userEvent.selectOptions(screen.getByLabelText('Métrique du benchmark'), 'p95_ms');
    expect(screen.getByRole('img', { name: /Benchmark mesuré p95_ms/ })).toBeInTheDocument();
  }
});
