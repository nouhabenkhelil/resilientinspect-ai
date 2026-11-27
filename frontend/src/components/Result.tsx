import { useId, useRef, useState } from 'react';
import { RevealSection } from './RevealSection';
import { Copy, Download, Maximize2 } from 'lucide-react';
import type { Prediction, VisualizedPrediction } from '../api/contracts';
import { Icon } from './Icon';

export const formatScore = (value: number) =>
  value !== 0 && Math.abs(value) < 0.0001
    ? value.toExponential(6)
    : value.toLocaleString('fr-FR', { minimumFractionDigits: 6, maximumFractionDigits: 6 });

function CopyValue({ value }: { value: string }) {
  const [notice, setNotice] = useState('');
  return (
    <span className="copy-control">
      <button
        className="icon-button"
        aria-label={`Copier ${value}`}
        onClick={() => {
          if (!navigator.clipboard) {
            setNotice('Copie indisponible');
            return;
          }
          void navigator.clipboard
            .writeText(value)
            .then(() => setNotice('Copié'))
            .catch(() => setNotice('Copie indisponible'));
        }}
      >
        <Copy size={14} />
      </button>
      <small role="status">{notice}</small>
    </span>
  );
}
export function ScoreGauge({ result }: { result: Prediction }) {
  const limit = Math.min(
    1,
    Math.max(result.anomaly_score, result.threshold, Number.MIN_VALUE) * 1.4,
  );
  const score = (100 * result.anomaly_score) / limit,
    threshold = (100 * result.threshold) / limit;
  return (
    <figure
      className="score-gauge"
      aria-label={`Score ${result.anomaly_score}, seuil ${result.threshold}. Échelle locale 0 à ${limit}.`}
    >
      <figcaption>
        Score / seuil de ce modèle <span>Échelle locale, pas une confiance</span>
      </figcaption>
      <div className="gauge-track">
        <div className={result.decision} style={{ width: `${score}%` }} />
        <i className="threshold-marker" style={{ left: `${threshold}%` }}>
          <span>Seuil</span>
        </i>
        <i
          className="score-marker"
          style={{ left: `${score}%` }}
          title={String(result.anomaly_score)}
        />
      </div>
      <div className="gauge-axis">
        <span>0</span>
        <span>{formatScore(limit)}</span>
      </div>
    </figure>
  );
}

export function Result({
  result,
  elapsed,
  endpoint = '/predict',
}: {
  result: Prediction;
  elapsed: number;
  endpoint?: string;
}) {
  const titleId = useId();
  const anomaly = result.decision === 'anomaly';
  return (
    <RevealSection className="panel result-panel" aria-labelledby={titleId}>
      <div className="panel-heading">
        <h2 id={titleId}>Résultat de l’inspection</h2>
        <span className="eyebrow">INFÉRENCE CPU</span>
      </div>
      <div className={`decision ${anomaly ? 'anomaly' : 'normal'}`}>
        <span className="decision-icon">
          <Icon name={anomaly ? 'alert' : 'check'} size={26} />
        </span>
        <div>
          <span className="eyebrow">DÉCISION DU MODÈLE</span>
          <h3>{anomaly ? 'Anormal' : 'Normal'}</h3>
          <p>
            {anomaly
              ? 'Le score dépasse le seuil calibré.'
              : 'Le score ne dépasse pas le seuil calibré.'}
          </p>
        </div>
      </div>
      <div className="scores">
        <div>
          <span>Score d’anomalie</span>
          <strong>{formatScore(result.anomaly_score)}</strong>
        </div>
        <div>
          <span>Seuil calibré</span>
          <strong>{formatScore(result.threshold)}</strong>
        </div>
      </div>
      <ScoreGauge result={result} />
      <details className="exact-values">
        <summary>Valeurs exactes de l’API</summary>
        <p className="mono">
          Score : {String(result.anomaly_score)}
          <br />
          Seuil : {String(result.threshold)}
        </p>
      </details>
      <p className="score-note">
        {['B0', 'A1'].includes(result.model)
          ? 'Erreur de reconstruction RGB · Ce score n’est pas une probabilité.'
          : 'Score sigmoid du logit anomalie · Ce score n’est pas une probabilité calibrée de défaut.'}{' '}
        Décision : score strictement supérieur au seuil.
      </p>
      <dl className="result-details">
        <div>
          <dt>Moteur de prédiction</dt>
          <dd>{result.engine === 'onnxruntime' ? 'ONNX Runtime' : 'PyTorch'}</dd>
        </div>
        {result.explanation_engine && (
          <div>
            <dt>Moteur d’explication</dt>
            <dd>{result.explanation_engine === 'onnxruntime' ? 'ONNX Runtime' : 'PyTorch'}</dd>
          </div>
        )}
        <div>
          <dt>Modèle</dt>
          <dd>{result.model}</dd>
        </div>
        <div>
          <dt>Catégorie</dt>
          <dd>{result.category}</dd>
        </div>
        <div>
          <dt>
            {endpoint === '/predict/visualize'
              ? 'Calcul : inférence et explication'
              : 'Latence d’inférence'}
          </dt>
          <dd>
            {result.inference_time_ms.toLocaleString('fr-FR', { maximumFractionDigits: 1 })} ms
          </dd>
        </div>
        <div>
          <dt>Aller-retour {endpoint}</dt>
          <dd>{elapsed.toLocaleString('fr-FR', { maximumFractionDigits: 0 })} ms</dd>
        </div>
        <div className="full">
          <dt>Identifiant de requête {endpoint}</dt>
          <dd className="mono">
            <span>{result.request_id}</span>
            <CopyValue value={result.request_id} />
          </dd>
        </div>
        <div className="full">
          <dt>Version du modèle · SHA256</dt>
          <dd className="mono small">
            <span>{result.version}</span>
            <CopyValue value={result.version} />
          </dd>
        </div>
      </dl>
    </RevealSection>
  );
}

export function Explanation({ result }: { result: VisualizedPrediction }) {
  const [view, setView] = useState<'overlay' | 'heatmap' | 'image' | 'side'>('overlay');
  const [zoom, setZoom] = useState(1);
  const [opacity, setOpacity] = useState(0.5);
  const dialog = useRef<HTMLDialogElement>(null);
  const visual = result.visualization;
  const gradcam = visual.kind === 'gradcam';
  const labels = {
    overlay: 'Superposition',
    heatmap: 'Carte seule',
    image: 'Image préparée',
    side: 'Côte à côte',
  };
  const png = (key: 'overlay' | 'heatmap' | 'image') =>
    `data:image/png;base64,${visual[`${key}_png_base64`]}`;
  function frame() {
    return (
      <div className={`visual-frame ${view === 'side' ? 'side-by-side' : ''}`}>
        <div className="zoom-canvas" key={view} style={{ transform: `scale(${zoom})` }}>
          {view === 'side' ? (
            <>
              <figure>
                <img src={png('image')} alt="Image préparée en coordonnées letterbox" />
                <figcaption>Image préparée</figcaption>
              </figure>
              <figure>
                <img src={png('heatmap')} alt="Carte explicative originale" />
                <figcaption>Carte originale</figcaption>
              </figure>
            </>
          ) : view === 'overlay' ? (
            <div className="opacity-composite">
              <img src={png('image')} alt="Fond préparé letterbox" />
              <img
                className="api-overlay"
                style={{ opacity: opacity * 2 }}
                src={png('overlay')}
                alt={`Superposition : ${gradcam ? 'Grad-CAM' : 'erreur de reconstruction'} pour ${result.category}`}
              />
            </div>
          ) : (
            <img
              src={png(view)}
              alt={`${labels[view]} : ${gradcam ? 'Grad-CAM' : 'erreur de reconstruction'} pour ${result.category}`}
            />
          )}
        </div>
      </div>
    );
  }
  return (
    <div className="explanation">
      <div className="explanation-toolbar">
        <div>
          <h3>{gradcam ? 'Grad-CAM' : 'Heatmap de reconstruction'}</h3>
          <p>{gradcam ? 'Attribution du logit anomalie' : 'Erreur absolue moyenne RGB'}</p>
        </div>
        <span className="tag">{result.model}</span>
      </div>
      {result.engine === 'onnxruntime' && (
        <p className="notice scientific-note">
          Prédiction ONNX Runtime · explication{' '}
          {result.explanation_engine === 'pytorch'
            ? 'PyTorch (Grad-CAM)'
            : 'ONNX Runtime (erreur de reconstruction)'}
          .
          {result.explanation_reference_score != null && (
            <>
              {' '}
              Score PyTorch associé : {String(result.explanation_reference_score)} · cohérence{' '}
              {result.explanation_score_coherent ? 'validée' : 'non validée'}.
            </>
          )}
          {result.explanation_decision_changed && (
            <> Basculement proche du seuil : inspection humaine recommandée.</>
          )}
        </p>
      )}
      <div className="segmented" aria-label="Vue de la visualisation">
        {(['overlay', 'heatmap', 'image', 'side'] as const).map((key) => (
          <button key={key} type="button" aria-pressed={view === key} onClick={() => setView(key)}>
            {labels[key]}
          </button>
        ))}
      </div>
      <div className="viewer-toolbar">
        <label>
          Zoom{' '}
          <select value={zoom} onChange={(e) => setZoom(Number(e.target.value))}>
            <option value={1}>100 %</option>
            <option value={1.5}>150 %</option>
            <option value={2}>200 %</option>
          </select>
        </label>
        {view === 'overlay' && (
          <label>
            Intensité d’exploration
            <input
              aria-label="Intensité de la superposition"
              type="range"
              min="0"
              max="0.5"
              step="0.01"
              value={opacity}
              onChange={(e) => setOpacity(Number(e.target.value))}
            />
          </label>
        )}
        <button
          className="icon-button"
          aria-label="Ouvrir le visualiseur plein écran"
          onClick={() => dialog.current?.showModal()}
        >
          <Maximize2 size={17} />
        </button>
        <a
          className="icon-button"
          aria-label="Télécharger le PNG original"
          href={png(view === 'side' ? 'heatmap' : view)}
          download={`${result.model}-${result.category}-${view}.png`}
        >
          <Download size={17} />
        </a>
      </div>
      {frame()}
      {view === 'overlay' && (
        <p className="small muted">
          À 50 %, superposition API originale. En dessous : fondu vers l’image préparée ; le PNG
          téléchargé reste inchangé.
        </p>
      )}
      <dialog ref={dialog} className="viewer-dialog">
        <div className="panel-heading">
          <h2>
            {gradcam ? 'Grad-CAM' : 'Erreur de reconstruction'} · {result.model}
          </h2>
          <button onClick={() => dialog.current?.close()} aria-label="Fermer le visualiseur">
            Fermer
          </button>
        </div>
        {frame()}
      </dialog>
      <div className="legend">
        <span>Faible</span>
        <div />
        <span>Élevée</span>
      </div>
      <p className="visual-warning">
        <Icon name="info" size={17} />
        <span>
          {gradcam
            ? 'Attribution visuelle grossière, relative à cette image. Grad-CAM n’est pas une segmentation pixel et ne délimite pas un défaut.'
            : 'Intensité de l’erreur de reconstruction sur une échelle absolue L1 [0, 1]. Le score est la moyenne du top 1 % des pixels valides. Le padding est exclu du calcul.'}
        </span>
      </p>
      <details>
        <summary>Détails de la visualisation</summary>
        <p>{visual.description}</p>
        <dl className="technical-details">
          <div>
            <dt>Coordonnées</dt>
            <dd>
              {visual.coordinate_space} · {visual.width} × {visual.height} px
            </dd>
          </div>
          <div>
            <dt>Image originale (H × L)</dt>
            <dd>{visual.original_height_width.join(' × ')} px</dd>
          </div>
          <div>
            <dt>Padding (haut, bas, gauche, droite)</dt>
            <dd>{visual.padding_top_bottom_left_right.join(', ')} px</dd>
          </div>
          <div>
            <dt>Échelle API</dt>
            <dd>{visual.scale}</dd>
          </div>
          <div>
            <dt>Requête /predict/visualize</dt>
            <dd className="mono">{result.request_id}</dd>
          </div>
          <div>
            <dt>Latence de visualisation</dt>
            <dd>{result.inference_time_ms.toFixed(1)} ms</dd>
          </div>
        </dl>
      </details>
    </div>
  );
}
