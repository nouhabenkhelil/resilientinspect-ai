import { fireEvent, render, screen } from '@testing-library/react';
import { EngineSelector } from './EngineSelector';
import { metadata, prediction } from '../test/fixtures';
import { api } from '../api/client';
import { readHistory, recordInspection } from '../studio/history';

test('legacy metadata keeps PyTorch and disables unvalidated ONNX', () => {
  render(
    <EngineSelector
      model={metadata.models[0]}
      value="pytorch"
      onChange={() => {}}
      disabled={false}
    />,
  );
  expect(screen.getByRole('option', { name: /ONNX Runtime/ })).toBeDisabled();
  expect(screen.getByLabelText('Moteur de prédiction')).toHaveValue('pytorch');
});
test('an admitted ONNX engine is explicitly selectable', () => {
  const onChange = vi.fn();
  render(
    <EngineSelector
      model={{ ...metadata.models[0], available_engines: ['pytorch', 'onnxruntime'] }}
      value="pytorch"
      onChange={onChange}
      disabled={false}
    />,
  );
  fireEvent.change(screen.getByLabelText('Moteur de prédiction'), {
    target: { value: 'onnxruntime' },
  });
  expect(onChange).toHaveBeenCalledWith('onnxruntime');
});
test('model changes do not silently fall back from an unavailable engine', () => {
  render(
    <EngineSelector
      model={metadata.models[0]}
      value="onnxruntime"
      onChange={() => {}}
      disabled={false}
    />,
  );
  expect(screen.getByRole('status')).toHaveTextContent('Choisissez explicitement');
});
test('optional engine travels in multipart and actual response engine is preserved', async () => {
  const fetcher = vi.fn(
    async () => new Response(JSON.stringify({ ...prediction, engine: 'onnxruntime' })),
  );
  vi.stubGlobal('fetch', fetcher);
  const result = await api.predict({
    file: new File(['unit fixture'], 'unit.png'),
    category: 'bottle',
    model: 'B0',
    engine: 'onnxruntime',
  });
  expect((fetcher.mock.calls[0] as unknown as [string, RequestInit])[1].body).toBeInstanceOf(
    FormData,
  );
  expect(
    ((fetcher.mock.calls[0] as unknown as [string, RequestInit])[1].body as FormData).get('engine'),
  ).toBe('onnxruntime');
  expect(result.engine).toBe('onnxruntime');
});
test('history stores the returned engine and reads old entries as PyTorch', () => {
  localStorage.clear();
  recordInspection({ ...prediction, engine: 'onnxruntime' }, 4);
  expect(readHistory()[0].engine).toBe('onnxruntime');
  const old = { ...readHistory()[0] };
  delete old.engine;
  localStorage.setItem('ri.inspections.v2', JSON.stringify([old]));
  expect(readHistory()[0].engine).toBe('pytorch');
  localStorage.clear();
});
