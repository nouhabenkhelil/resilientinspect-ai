import { useEffect, useRef, useState } from 'react';
import { FlaskConical, Upload, CheckCheck, TriangleAlert } from 'lucide-react';
import { api, errorMessage } from '../api/client';
import {
  CATEGORIES,
  MODEL_NAMES,
  type Category,
  type ModelName,
  type VisualizedPrediction,
  type Metadata,
} from '../api/contracts';
import { validateFile, validateImage } from '../image';
import { recordInspection } from '../studio/history';
import { Result, Explanation } from './Result';
import { architectures, categoryLabels } from './InspectionTools';

export function classification(decision: string, truth: string) {
  if (truth === 'unknown') return null;
  return truth === 'anomaly'
    ? decision === 'anomaly'
      ? 'TP'
      : 'FN'
    : decision === 'anomaly'
      ? 'FP'
      : 'TN';
}
export function ComparisonLab({ metadata }: { metadata: Metadata | null }) {
  const [category, setCategory] = useState<Category>('bottle');
  const [selected, setSelected] = useState<ModelName[]>(['B0', 'T2']);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [truth, setTruth] = useState('unknown');
  const [active, setActive] = useState('');
  const [results, setResults] = useState<
    { model: ModelName; result?: VisualizedPrediction; elapsed?: number; error?: string }[]
  >([]);
  const controller = useRef<AbortController | null>(null);
  const uploadRevision = useRef(0);
  const [validating, setValidating] = useState(false);
  const available = metadata?.models.filter((m) => m.category === category) || [];
  useEffect(
    () => () => {
      controller.current?.abort();
      uploadRevision.current++;
    },
    [],
  );
  useEffect(
    () => () => {
      if (preview) URL.revokeObjectURL(preview);
    },
    [preview],
  );
  async function upload(files: File[]) {
    const revision = ++uploadRevision.current;
    setFile(null);
    setPreview('');
    setError('');
    setResults([]);
    setValidating(true);
    let url = '';
    try {
      if (files.length !== 1) throw new Error('Importez une seule image à la fois.');
      validateFile(files[0]);
      url = URL.createObjectURL(files[0]);
      await validateImage(url);
      if (revision !== uploadRevision.current) {
        URL.revokeObjectURL(url);
        return;
      }
      setFile(files[0]);
      setPreview(url);
    } catch (e) {
      if (url) URL.revokeObjectURL(url);
      if (revision === uploadRevision.current) setError(errorMessage(e));
    } finally {
      if (revision === uploadRevision.current) setValidating(false);
    }
  }
  async function compare() {
    if (!file || selected.length < 2 || busy) return;
    const abort = new AbortController();
    controller.current = abort;
    setBusy(true);
    setResults([]);
    setError('');
    try {
      for (const model of selected) {
        if (abort.signal.aborted) break;
        setActive(model);
        const started = performance.now();
        try {
          const result = await api.visualize({ file, category, model }, abort.signal);
          if (abort.signal.aborted) break;
          const elapsed = performance.now() - started;
          recordInspection(result, elapsed, '/predict/visualize');
          setResults((rows) => [...rows, { model, result, elapsed }]);
        } catch (e) {
          if (!abort.signal.aborted)
            setResults((rows) => [...rows, { model, error: errorMessage(e) }]);
        }
      }
    } finally {
      if (controller.current === abort) {
        setBusy(false);
        setActive('');
        controller.current = null;
      }
    }
  }
  const completed = results.flatMap((r) => (r.result ? [r.result] : []));
  const full = completed.length === selected.length;
  const disagreement = new Set(completed.map((r) => r.decision)).size > 1;
  return (
    <div className="comparison-page">
      <div className="notice scientific-note">
        <FlaskConical />
        <p>
          Une image, plusieurs regards. Chaque score est comparé à son <strong>propre seuil</strong>
          . Les amplitudes AE et sigmoid sont différentes et ne sont jamais fusionnées.
        </p>
      </div>
      <section className="panel comparison-setup">
        <div className="panel-heading">
          <h2>Protocole de comparaison</h2>
          <span className="tag">REQUÊTES SÉQUENTIELLES</span>
        </div>
        <div className="configuration">
          <label>
            Catégorie
            <select
              aria-label="Catégorie de comparaison"
              value={category}
              disabled={busy}
              onChange={(e) => {
                setCategory(e.target.value as Category);
                setResults([]);
              }}
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {categoryLabels[c]}
                </option>
              ))}
            </select>
          </label>
          <label>
            Vérité terrain facultative
            <select value={truth} onChange={(e) => setTruth(e.target.value)}>
              <option value="unknown">Non renseignée</option>
              <option value="normal">Normale (connue par l’utilisateur)</option>
              <option value="anomaly">Anormale (connue par l’utilisateur)</option>
            </select>
          </label>
        </div>
        <fieldset disabled={busy}>
          <legend>Choisissez au moins deux modèles disponibles</legend>
          <div className="comparison-models">
            {MODEL_NAMES.map((name) => (
              <label className={selected.includes(name) ? 'chosen' : ''} key={name}>
                <input
                  type="checkbox"
                  checked={selected.includes(name)}
                  disabled={!available.some((m) => m.model === name)}
                  onChange={(e) => {
                    setResults([]);
                    setSelected((rows) =>
                      e.target.checked ? [...rows, name] : rows.filter((n) => n !== name),
                    );
                  }}
                />
                <strong>{name}</strong>
                <span>{architectures[name].name}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <div
          className="comparison-upload"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            if (!busy) void upload(Array.from(e.dataTransfer.files));
          }}
        >
          {preview ? <img src={preview} alt="Image commune aux modèles" /> : <Upload size={32} />}
          <label className="secondary-button">
            Importer l’image commune
            <input
              aria-label="Image de comparaison"
              className="sr-only"
              disabled={busy}
              type="file"
              accept=".png,.jpg,.jpeg"
              onChange={(e) => void upload(Array.from(e.target.files || []))}
            />
          </label>
          <span>{file?.name || 'PNG/JPEG · 10 Mio max. · glisser-déposer possible'}</span>
        </div>
        {error && (
          <p role="alert" className="notice error">
            {error}
          </p>
        )}
        <div className="toolbar">
          <button
            className="primary-button"
            disabled={
              !file ||
              selected.length < 2 ||
              busy ||
              validating ||
              selected.some((n) => !available.some((m) => m.model === n))
            }
            onClick={() => void compare()}
          >
            <FlaskConical size={18} />
            {busy ? `Analyse ${active}…` : 'Comparer les modèles'}
          </button>
          {busy && (
            <button
              className="secondary-button"
              onClick={() => {
                controller.current?.abort();
                setError(
                  'Attente annulée. Une requête déjà reçue peut terminer son calcul côté serveur.',
                );
              }}
            >
              Annuler la comparaison
            </button>
          )}
        </div>
      </section>
      {completed.length >= 2 && (
        <div className={`notice ${disagreement ? 'warning' : 'success'}`} role="status">
          {disagreement ? <TriangleAlert /> : <CheckCheck />}
          <p>
            <strong>
              {disagreement
                ? 'Désaccord entre les modèles · inspection humaine recommandée'
                : full
                  ? 'Concordance des décisions'
                  : 'Concordance des résultats reçus · comparaison partielle'}
            </strong>
            <br />
            Sans vérité terrain connue, cette concordance ne mesure pas la justesse des prédictions.
          </p>
        </div>
      )}
      {!results.length && !busy && (
        <div className="panel empty-state">
          <FlaskConical size={38} />
          <h2>Le laboratoire est prêt</h2>
          <p>Comparez B0 et T2 sur votre image, puis explorez leurs explications.</p>
        </div>
      )}
      <div className="comparison-results">
        {results.map((row) => (
          <section key={row.model} className="comparison-result">
            <header>
              <h2>{row.model}</h2>
              <p>{architectures[row.model].description}</p>
            </header>
            {row.error ? (
              <div role="alert" className="notice error">
                {row.error}
              </div>
            ) : (
              row.result && (
                <>
                  <Result
                    result={row.result}
                    elapsed={row.elapsed!}
                    endpoint="/predict/visualize"
                  />
                  {classification(row.result.decision, truth) && (
                    <p className="ground-truth">
                      Vérité terrain fournie par l’utilisateur :{' '}
                      <strong>{classification(row.result.decision, truth)}</strong>
                    </p>
                  )}
                  <div className="panel">
                    <Explanation result={row.result} />
                  </div>
                </>
              )
            )}
          </section>
        ))}
      </div>
    </div>
  );
}
