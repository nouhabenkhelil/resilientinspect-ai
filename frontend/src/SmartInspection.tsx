import { useEffect, useRef, useState } from 'react';
import { api, ApiError, errorMessage } from './api/client';
import {
  CATEGORIES,
  type Engine,
  MODEL_NAMES,
  type Category,
  type Health,
  type Metadata,
  type Prediction,
  type VisualizedPrediction,
} from './api/contracts';
import { validateFile, validateImage } from './image';
import { recordInspection } from './studio/history';
import { CategoryCards, ModelCards, Pipeline } from './components/InspectionTools';
import { Webcam } from './components/Webcam';
import { EngineSelector } from './components/EngineSelector';
import { Icon } from './components/Icon';
import { Explanation, formatScore, Result } from './components/Result';

type Upload = { file: File; url: string; width: number; height: number };
type Stage = 'idle' | 'predict' | 'visualize';
const categoryLabels = { bottle: 'Bouteille', hazelnut: 'Noisette', leather: 'Cuir' };

function ErrorNotice({ error, title }: { error: unknown; title: string }) {
  return (
    <div className="notice error" role="alert">
      <Icon name="alert" />
      <div>
        <strong>{title}</strong>
        <p>{errorMessage(error)}</p>
        {error instanceof ApiError && error.requestId && (
          <p className="mono small">Requête : {error.requestId}</p>
        )}
      </div>
    </div>
  );
}

export default function SmartInspection() {
  const [health, setHealth] = useState<Health | null>(null);
  const [metadata, setMetadata] = useState<Metadata | null>(null);
  const [connectionError, setConnectionError] = useState<unknown>(null);
  const [refreshing, setRefreshing] = useState(true);
  const [category, setCategory] = useState<Category>(() => {
    try {
      const value = sessionStorage.getItem('ri.next-category');
      sessionStorage.removeItem('ri.next-category');
      return CATEGORIES.includes(value as Category) ? (value as Category) : 'bottle';
    } catch {
      return 'bottle';
    }
  });
  const [preferredModel, setPreferredModel] = useState('B0');
  const [engine, setEngine] = useState<Engine>('pytorch');
  const [upload, setUpload] = useState<Upload | null>(null);
  const [validating, setValidating] = useState(false);
  const [fileError, setFileError] = useState<unknown>(null);
  const [analysisError, setAnalysisError] = useState<unknown>(null);
  const [visualError, setVisualError] = useState<unknown>(null);
  const [prediction, setPrediction] = useState<Prediction | null>(null);
  const [visualized, setVisualized] = useState<VisualizedPrediction | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [stage, setStage] = useState<Stage>('idle');
  const [dragging, setDragging] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const fileInput = useRef<HTMLInputElement>(null);
  const uploadRevision = useRef(0);
  const analysisController = useRef<AbortController | null>(null);
  const dragDepth = useRef(0);
  const busy = stage !== 'idle';
  const available = (metadata?.models || [])
    .filter((item) => item.category === category)
    .sort((a, b) => MODEL_NAMES.indexOf(a.model) - MODEL_NAMES.indexOf(b.model));
  const selected = available.find((item) => item.model === preferredModel) || available[0];
  const unavailable = (metadata?.unavailable || []).filter((item) => item.category === category);

  useEffect(() => {
    const controller = new AbortController();
    let inFlight = false;
    async function refresh() {
      if (inFlight) return;
      inFlight = true;
      setRefreshing(true);
      const [healthResult, metadataResult] = await Promise.allSettled([
        api.health(controller.signal),
        api.metadata(controller.signal),
      ]);
      if (controller.signal.aborted) return;
      setHealth(healthResult.status === 'fulfilled' ? healthResult.value : null);
      setMetadata(metadataResult.status === 'fulfilled' ? metadataResult.value : null);
      setConnectionError(
        healthResult.status === 'rejected'
          ? healthResult.reason
          : metadataResult.status === 'rejected'
            ? metadataResult.reason
            : null,
      );
      setRefreshing(false);
      inFlight = false;
    }
    void refresh();
    const timer = setInterval(() => void refresh(), 30_000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [refreshKey]);

  useEffect(
    () => () => {
      if (upload) URL.revokeObjectURL(upload.url);
    },
    [upload],
  );
  useEffect(
    () => () => {
      analysisController.current?.abort();
      uploadRevision.current++;
    },
    [],
  );

  function clearResults() {
    setPrediction(null);
    setVisualized(null);
    setAnalysisError(null);
    setVisualError(null);
  }

  function removeUpload() {
    uploadRevision.current++;
    setUpload(null);
    setFileError(null);
    setValidating(false);
    clearResults();
    if (fileInput.current) fileInput.current.value = '';
  }

  async function importFiles(files: File[]) {
    if (busy || files.length === 0) return;
    const revision = ++uploadRevision.current;
    setUpload(null);
    setFileError(null);
    clearResults();
    setValidating(true);
    let url: string | undefined;
    try {
      if (files.length !== 1) throw new Error('Importez une seule image à la fois.');
      const file = files[0];
      validateFile(file);
      url = URL.createObjectURL(file);
      const size = await validateImage(url);
      if (revision !== uploadRevision.current) {
        URL.revokeObjectURL(url);
        return;
      }
      setUpload({ file, url, ...size });
    } catch (error) {
      if (url) URL.revokeObjectURL(url);
      if (revision === uploadRevision.current) setFileError(error);
    } finally {
      if (revision === uploadRevision.current) setValidating(false);
      if (fileInput.current) fileInput.current.value = '';
    }
  }

  async function analyze(visualOnly = false) {
    if (!upload || !selected || !health || busy) return;
    if (!(selected.available_engines || ['pytorch']).includes(engine)) return;
    const input = { file: upload.file, category, model: selected.model, engine };
    const controller = new AbortController();
    analysisController.current = controller;
    setAnalysisError(null);
    setVisualError(null);
    setVisualized(null);
    setStage(visualOnly ? 'visualize' : 'predict');
    try {
      if (!visualOnly) {
        setPrediction(null);
        const started = performance.now();
        const result = await api.predict(input, controller.signal);
        if (controller.signal.aborted) return;
        setPrediction(result);
        const roundTrip = performance.now() - started;
        setElapsed(roundTrip);
        recordInspection(result, roundTrip);
        setStage('visualize');
      }
      try {
        const result = await api.visualize(input, controller.signal);
        if (!controller.signal.aborted) setVisualized(result);
      } catch (error) {
        if (!controller.signal.aborted) setVisualError(error);
      }
    } catch (error) {
      if (!controller.signal.aborted) setAnalysisError(error);
    } finally {
      if (analysisController.current === controller) {
        setStage('idle');
        analysisController.current = null;
      }
    }
  }

  const status = !health
    ? refreshing
      ? 'Connexion à l’API'
      : 'API hors ligne'
    : health.status === 'degraded'
      ? 'API dégradée'
      : 'API opérationnelle';

  return (
    <div className="inspection-workspace">
      <div className="workspace-status" role="status">
        {status}
      </div>
      <section className="service-strip" aria-label="État du service">
        <div>
          <Icon name="layers" />
          <span>
            <strong>{health ? `${health.ready_models} / ${health.expected_models}` : '—'}</strong>{' '}
            modèles prêts
          </span>
        </div>
        <div>
          <span className="service-label">Calcul</span>
          <strong>CPU</strong>
        </div>
        <div>
          <span className="service-label">Version API</span>
          <strong>{health?.version || '—'}</strong>
        </div>
        <button
          className="text-button refresh"
          disabled={refreshing}
          onClick={() => setRefreshKey((value) => value + 1)}
          aria-label="Actualiser le statut API"
        >
          <Icon name="refresh" size={16} />
          {refreshing ? 'Vérification…' : 'Actualiser'}
        </button>
      </section>
      {connectionError != null && (
        <ErrorNotice error={connectionError} title="Connexion au service à vérifier" />
      )}
      {health?.status === 'degraded' && (
        <div className="notice warning" role="status">
          <Icon name="alert" />
          <div>
            <strong>Service partiellement disponible</strong>
            <p>
              Les modèles disponibles restent utilisables. Les autres sont signalés dans le
              sélecteur.
            </p>
          </div>
        </div>
      )}
      <Pipeline
        validating={validating}
        ready={!!upload}
        stage={stage}
        received={!!prediction}
        explained={!!visualized}
      />
      <div className="inspection-grid">
        <div className="input-column">
          <section className="panel" aria-labelledby="setup-title">
            <div className="panel-heading">
              <h2 id="setup-title">
                <span className="step-number">01</span> Configuration
              </h2>
              <span className="eyebrow">PARAMÈTRES</span>
            </div>
            <CategoryCards
              selected={category}
              disabled={busy}
              onSelect={(value) => {
                setCategory(value);
                clearResults();
              }}
            />
            <div className="configuration">
              <div className="field">
                <label htmlFor="category">Catégorie du produit</label>
                <select
                  id="category"
                  value={category}
                  disabled={busy}
                  onChange={(event) => {
                    setCategory(event.target.value as Category);
                    clearResults();
                  }}
                >
                  {CATEGORIES.map((item) => (
                    <option value={item} key={item}>
                      {categoryLabels[item]} · {item}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="model">Modèle d’inspection</label>
                <select
                  id="model"
                  value={selected?.model || ''}
                  disabled={busy || !available.length}
                  onChange={(event) => {
                    setPreferredModel(event.target.value);
                    clearResults();
                  }}
                >
                  {!available.length && (
                    <option value="">
                      {refreshing ? 'Chargement des modèles…' : 'Aucun modèle disponible'}
                    </option>
                  )}
                  {MODEL_NAMES.map((name) => {
                    const loaded = available.find((item) => item.model === name);
                    const missing = unavailable.find((item) => item.model === name);
                    return loaded || missing ? (
                      <option key={name} value={name} disabled={!loaded}>
                        {name} ·{' '}
                        {loaded
                          ? loaded.explanation === 'gradcam'
                            ? 'Transfert'
                            : 'Autoencodeur'
                          : 'Indisponible'}
                      </option>
                    ) : null;
                  })}
                </select>
              </div>
            </div>
            <EngineSelector
              model={selected}
              value={engine}
              disabled={busy}
              onChange={(value) => {
                setEngine(value);
                clearResults();
              }}
            />
            <ModelCards
              category={category}
              available={available}
              selected={selected?.model}
              disabled={busy}
              onSelect={(name) => {
                setPreferredModel(name);
                clearResults();
              }}
            />
            {selected && (
              <div className="model-info">
                <Icon name="info" size={17} />
                <span>
                  {selected.explanation === 'gradcam'
                    ? 'Attribution Grad-CAM'
                    : 'Erreur de reconstruction'}
                  <span className="info-separator">·</span>Entrée {selected.input_size.join(' × ')}{' '}
                  px<span className="info-separator">·</span>
                  Seuil {formatScore(selected.threshold)}
                </span>
              </div>
            )}
            {unavailable.length > 0 && (
              <details className="unavailable-details">
                <summary>
                  {unavailable.length} modèle(s) indisponible(s) pour {category}
                </summary>
                {unavailable.map((item) => (
                  <p key={item.model}>
                    <strong>{item.model}</strong> — {item.reason}
                  </p>
                ))}
              </details>
            )}
          </section>
          <section className="panel upload-panel" aria-labelledby="upload-title">
            <div className="panel-heading">
              <h2 id="upload-title">
                <span className="step-number">02</span> Image à inspecter
              </h2>
              <span className="eyebrow">PNG / JPEG</span>
            </div>
            <div
              className={`drop-zone ${dragging ? 'dragging' : ''} ${upload ? 'has-image' : ''}`}
              onDragEnter={(event) => {
                event.preventDefault();
                if (!busy) {
                  dragDepth.current++;
                  setDragging(true);
                }
              }}
              onDragOver={(event) => event.preventDefault()}
              onDragLeave={(event) => {
                event.preventDefault();
                dragDepth.current = Math.max(0, dragDepth.current - 1);
                if (!dragDepth.current) setDragging(false);
              }}
              onDrop={(event) => {
                event.preventDefault();
                dragDepth.current = 0;
                setDragging(false);
                void importFiles(Array.from(event.dataTransfer.files));
              }}
            >
              {upload ? (
                <>
                  <div className={`preview-grid ${busy ? 'is-analyzing' : ''}`}>
                    <img
                      className="local-preview"
                      src={upload.url}
                      alt={`Aperçu local : ${upload.file.name}`}
                    />
                  </div>
                  <div className="file-bar">
                    <Icon name="image" />
                    <div>
                      <strong title={upload.file.name}>{upload.file.name}</strong>
                      <span>
                        {upload.width} × {upload.height} px ·{' '}
                        {(upload.file.size / 1024).toLocaleString('fr-FR', {
                          maximumFractionDigits: 1,
                        })}{' '}
                        Kio
                      </span>
                    </div>
                    <button
                      className="icon-button"
                      aria-label="Retirer l’image"
                      disabled={busy}
                      onClick={removeUpload}
                    >
                      <Icon name="close" size={18} />
                    </button>
                  </div>
                </>
              ) : (
                <div className="drop-content">
                  <span className="upload-symbol">
                    <Icon name="upload" size={27} />
                  </span>
                  <h3>
                    {validating
                      ? 'Vérification de l’image…'
                      : dragging
                        ? 'Déposez votre image ici'
                        : 'Glissez votre image ici'}
                  </h3>
                  <p>ou choisissez un fichier sur votre ordinateur</p>
                  <button
                    className="secondary-button"
                    disabled={busy || validating}
                    onClick={() => fileInput.current?.click()}
                  >
                    <Icon name="image" size={17} />
                    Importer une image
                  </button>
                  <span className="file-hint">PNG, JPG ou JPEG · 10 Mio max. · 20 Mpx max.</span>
                </div>
              )}
            </div>
            <input
              ref={fileInput}
              type="file"
              accept=".png,.jpg,.jpeg,image/png,image/jpeg"
              aria-label="Fichier image à inspecter"
              className="sr-only"
              tabIndex={-1}
              disabled={busy}
              onChange={(event) => void importFiles(Array.from(event.target.files || []))}
            />
            <Webcam disabled={busy} onCapture={(file) => void importFiles([file])} />
            {upload && (
              <button
                className="text-button replace-image"
                disabled={busy}
                onClick={() => fileInput.current?.click()}
              >
                Remplacer l’image
              </button>
            )}
            {fileError != null && <ErrorNotice error={fileError} title="Fichier invalide" />}
            <div className="analysis-action">
              <p>
                <Icon name="info" size={16} />
                L’image sera envoyée à votre API locale pour analyse.
              </p>
              <button
                className="primary-button"
                disabled={
                  !upload ||
                  !selected ||
                  !health ||
                  busy ||
                  validating ||
                  !(selected.available_engines || ['pytorch']).includes(engine)
                }
                onClick={() => void analyze()}
              >
                {busy ? <span className="spinner" /> : <Icon name="scan" />}
                {stage === 'predict'
                  ? 'Analyse en cours…'
                  : stage === 'visualize'
                    ? 'Visualisation en cours…'
                    : 'Analyser l’image'}
                {!busy && <Icon name="arrow" size={18} />}
              </button>
              {busy && (
                <button
                  className="text-button cancel"
                  onClick={() => analysisController.current?.abort()}
                >
                  Annuler l’attente
                </button>
              )}
            </div>
          </section>
          {analysisError != null && (
            <ErrorNotice error={analysisError} title="L’analyse n’a pas abouti" />
          )}
          {prediction && <Result key={prediction.request_id} result={prediction} elapsed={elapsed} />}
        </div>
        <section className="panel visualization-panel" aria-labelledby="visualization-title">
          <div className="panel-heading">
            <h2 id="visualization-title">
              <span className="step-number">03</span> Visualisation
            </h2>
            <span className="tag">EXPLICABILITÉ</span>
          </div>
          {visualized ? (
            <Explanation key={visualized.request_id} result={visualized} />
          ) : (
            <div className="visual-empty">
              <div className={`scan-placeholder ${busy ? 'scanning' : ''}`}>
                <Icon name="scan" size={52} />
                <span />
              </div>
              <h3>
                {stage === 'predict'
                  ? 'Analyse de l’image'
                  : stage === 'visualize'
                    ? 'Génération de la visualisation'
                    : visualError
                      ? 'Visualisation indisponible'
                      : 'Un regard sur la décision'}
              </h3>
              <p>
                {busy
                  ? 'Requête en cours sur CPU. Le balayage est un effet d’attente, pas une représentation du CNN.'
                  : 'Après l’analyse, explorez la heatmap de reconstruction ou l’attribution Grad-CAM du modèle.'}
              </p>
              {busy && (
                <span className="processing-label" role="status">
                  <span className="spinner" />
                  {stage === 'predict' ? 'Étape 1 / 2 · Prédiction' : 'Étape 2 / 2 · Explication'}
                </span>
              )}
            </div>
          )}
          {visualError != null && (
            <div className="visual-error">
              <ErrorNotice error={visualError} title="La prédiction reste disponible" />
              <button
                className="secondary-button"
                disabled={busy || !health || !selected}
                onClick={() => void analyze(true)}
              >
                <Icon name="refresh" size={16} />
                Réessayer la visualisation
              </button>
            </div>
          )}
          {!visualized && (
            <div className="visual-footer">
              <Icon name="layers" size={18} />
              <span>
                <strong>B0 / A1</strong> · Reconstruction
                <br />
                <strong>T0 / T1 / T2</strong> · Grad-CAM
              </span>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
