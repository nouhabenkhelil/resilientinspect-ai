import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ComparisonLab, classification } from './ComparisonLab';
import { metadata, prediction, visualization } from '../test/fixtures';
import { readHistory } from '../studio/history';
import type { ModelName } from '../api/contracts';

let fetcher: ReturnType<typeof vi.fn>;
const file = () => new File(['local-test-image'], 'compare.png', { type: 'image/png' });
function response(model: ModelName, decision: 'normal' | 'anomaly' = 'normal') {
  const result = visualization({
    ...prediction,
    model,
    decision,
    anomaly_score: decision === 'normal' ? 0.01 : 0.03,
  });
  result.request_id =
    model === 'B0'
      ? '70eb3228-7a80-40fe-8ff2-3357753c1cc7'
      : '2d875bca-61a5-43df-b64e-23fd1db4da8d';
  return new Response(JSON.stringify(result));
}

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal(
    'Image',
    class {
      naturalWidth = 173;
      naturalHeight = 89;
      onload?: () => void;
      set src(_value: string) {
        queueMicrotask(() => this.onload?.());
      }
    },
  );
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    value: vi.fn(() => 'blob:comparison'),
  });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
  fetcher = vi.fn(async (_url: string, options?: RequestInit) =>
    response((options?.body as FormData).get('model') as ModelName),
  );
  vi.stubGlobal('fetch', fetcher);
});

async function upload() {
  await userEvent.upload(screen.getByLabelText('Image de comparaison'), file());
  await screen.findByAltText('Image commune aux modèles');
}

test('B0/T2 use the real multipart endpoint sequentially, report disagreement and known ground truth', async () => {
  let release: (value: Response) => void = () => {};
  fetcher.mockImplementationOnce(
    () =>
      new Promise<Response>((resolve) => {
        release = resolve;
      }),
  );
  fetcher.mockImplementation(async (_url: string, options?: RequestInit) =>
    response((options?.body as FormData).get('model') as ModelName, 'anomaly'),
  );
  render(<ComparisonLab metadata={metadata} />);
  await upload();
  expect(screen.getByRole('checkbox', { name: /B0/ })).toBeChecked();
  expect(screen.getByRole('checkbox', { name: /T2/ })).toBeChecked();
  await userEvent.click(screen.getByRole('button', { name: 'Comparer les modèles' }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  expect(fetcher.mock.calls[0][0]).toBe('/api/predict/visualize');
  const first = fetcher.mock.calls[0][1] as RequestInit;
  expect((first.body as FormData).get('model')).toBe('B0');
  expect((first.body as FormData).get('category')).toBe('bottle');
  expect(((first.body as FormData).get('file') as File).name).toBe('compare.png');
  expect(screen.getByLabelText('Catégorie de comparaison')).toBeDisabled();
  release(response('B0'));
  await screen.findByText(/Désaccord entre les modèles/);
  expect(fetcher).toHaveBeenCalledTimes(2);
  const second = fetcher.mock.calls[1][1] as RequestInit;
  expect((second.body as FormData).get('model')).toBe('T2');
  expect(((second.body as FormData).get('file') as File).name).toBe('compare.png');
  expect(screen.queryByText(/Vérité terrain fournie par/)).not.toBeInTheDocument();
  await userEvent.selectOptions(screen.getByLabelText('Vérité terrain facultative'), 'normal');
  expect(screen.getByText('TN')).toBeInTheDocument();
  expect(screen.getByText('FP')).toBeInTheDocument();
  expect(readHistory()).toHaveLength(2);
  expect(JSON.stringify(readHistory())).not.toMatch(/base64|local-test-image|compare\.png/);
});

test('comparison cancellation aborts the in-flight request and never starts the next model', async () => {
  let signal: AbortSignal | undefined;
  fetcher.mockImplementation(
    (_url: string, options?: RequestInit) =>
      new Promise((_resolve, reject) => {
        signal = options?.signal || undefined;
        signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
      }),
  );
  const { unmount } = render(<ComparisonLab metadata={metadata} />);
  await upload();
  await userEvent.click(screen.getByRole('button', { name: 'Comparer les modèles' }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  await userEvent.click(screen.getByRole('button', { name: 'Annuler la comparaison' }));
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Comparer les modèles' })).toBeEnabled(),
  );
  expect(signal?.aborted).toBe(true);
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(readHistory()).toHaveLength(0);
  expect(screen.getByRole('alert')).toHaveTextContent('Attente annulée');
  unmount();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:comparison');
});

test('unavailable models cannot be selected or launched and one selection is insufficient', async () => {
  render(
    <ComparisonLab
      metadata={{ ...metadata, models: metadata.models.filter((m) => m.model !== 'T2') }}
    />,
  );
  await upload();
  expect(screen.getByRole('checkbox', { name: /T2/ })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Comparer les modèles' })).toBeDisabled();
  expect(fetcher).not.toHaveBeenCalled();
});

test.each([
  ['normal', 'unknown', null],
  ['anomaly', 'unknown', null],
  ['normal', 'normal', 'TN'],
  ['anomaly', 'normal', 'FP'],
  ['normal', 'anomaly', 'FN'],
  ['anomaly', 'anomaly', 'TP'],
])('classification %s against %s is %s', (decision, truth, expected) => {
  expect(classification(decision!, truth!)).toBe(expected);
});
