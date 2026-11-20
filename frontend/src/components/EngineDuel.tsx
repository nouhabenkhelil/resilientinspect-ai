import { useEffect, useRef, useState } from 'react';
import { api, errorMessage } from '../api/client';
import {
  MODEL_NAMES,
  type Category,
  type Engine,
  type Metadata,
  type ModelName,
  type Prediction,
} from '../api/contracts';
import { recordInspection } from '../studio/history';
import { Result } from './Result';

export function EngineDuel({
  file,
  category,
  metadata,
  disabled,
  onBusyChange,
}: {
  file: File | null;
  category: Category;
  metadata: Metadata | null;
  disabled: boolean;
  onBusyChange: (busy: boolean) => void;
}) {
  const [model, setModel] = useState<ModelName>('B0');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [results, setResults] = useState<{ result: Prediction; elapsed: number }[]>([]);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => {
    controller.current?.abort();
    setResults([]);
    return () => {
      controller.current?.abort();
      onBusyChange(false);
    };
  }, [file, category, onBusyChange]);
  const ready = metadata?.models
    .find((m) => m.model === model && m.category === category)
    ?.available_engines?.includes('onnxruntime');
  async function compare() {
    if (!file || !ready || disabled || busy) return;
    const abort = new AbortController();
    controller.current = abort;
    setBusy(true);
    onBusyChange(true);
    setResults([]);
    setError('');
    try {
      for (const engine of ['pytorch', 'onnxruntime'] as Engine[]) {
        if (abort.signal.aborted) break;
        const started = performance.now();
        const result = await api.predict({ file, category, model, engine }, abort.signal);
        if (abort.signal.aborted) break;
        const elapsed = performance.now() - started;
        recordInspection(result, elapsed);
        setResults((r) => [...r, { result, elapsed }]);
      }
    } catch (e) {
      if (!abort.signal.aborted) setError(errorMessage(e));
    } finally {
      setBusy(false);
      onBusyChange(false);
    }
  }
  return (
    <details className="panel">
      <summary>Comparaison technique des moteurs · même architecture</summary>
      <p className="scientific-note">
        Utilise l’image et la catégorie importées ci-dessus. Deux requêtes /predict séquentielles,
        sans Grad-CAM ; distinct du laboratoire scientifique d’architectures et du benchmark
        répétable.
      </p>
      <div className="configuration">
        <label>
          Architecture technique
          <select
            value={model}
            disabled={busy || disabled}
            onChange={(e) => {
              setModel(e.target.value as ModelName);
              setResults([]);
            }}
          >
            {MODEL_NAMES.map((m) => (
              <option key={m}>{m}</option>
            ))}
          </select>
        </label>
        <button
          className="secondary-button"
          disabled={busy || disabled || !file || !ready}
          onClick={() => void compare()}
        >
          Comparer PyTorch et ONNX
        </button>
      </div>
      {!ready && <p className="muted small">ONNX n’est pas admis pour cette sélection.</p>}
      {busy && (
        <button onClick={() => controller.current?.abort()}>
          Annuler la comparaison technique
        </button>
      )}
      {error && <p role="alert">{error}</p>}
      <div className="comparison-results">
        {results.map((r) => (
          <Result
            key={r.result.engine || r.result.request_id}
            result={r.result}
            elapsed={r.elapsed}
          />
        ))}
      </div>
    </details>
  );
}
