import type { Engine, ModelMetadata } from '../api/contracts';
export function EngineSelector({
  model,
  value,
  onChange,
  disabled,
}: {
  model?: ModelMetadata;
  value: Engine;
  onChange: (engine: Engine) => void;
  disabled: boolean;
}) {
  const available = model?.available_engines || ['pytorch'];
  return (
    <div className="field">
      <label htmlFor="prediction-engine">Moteur de prédiction</label>
      <select
        id="prediction-engine"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value as Engine)}
      >
        <option value="pytorch" disabled={!available.includes('pytorch')}>
          PyTorch · référence FP32
        </option>
        <option value="onnxruntime" disabled={!available.includes('onnxruntime')}>
          ONNX Runtime · {available.includes('onnxruntime') ? 'validé CPU' : 'indisponible'}
        </option>
      </select>
      {!available.includes(value) && (
        <p className="notice warning" role="status">
          Ce moteur n’est pas admis pour le modèle sélectionné. Choisissez explicitement un moteur
          disponible.
        </p>
      )}
      <p className="small muted">
        {model?.engine_unavailable_reasons?.onnxruntime ||
          'La disponibilité provient des preuves de validation retournées par l’API.'}
      </p>
    </div>
  );
}
