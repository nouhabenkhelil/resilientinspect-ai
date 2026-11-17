import { useState } from 'react';
import type { Prediction, VisualizedPrediction } from '../api/contracts';
import { Icon } from './Icon';

export const formatScore = (value: number) =>
  value.toLocaleString('fr-FR', { minimumFractionDigits: 6, maximumFractionDigits: 6 });

export function Result({ result, elapsed }: { result: Prediction; elapsed: number }) {
  const anomaly = result.decision === 'anomaly';
  return (
    <section className="panel result-panel" aria-labelledby="result-title">
      <div className="panel-heading">
        <h2 id="result-title">Résultat de l’inspection</h2>
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
      <p className="score-note">
        {['B0', 'A1'].includes(result.model)
          ? 'Erreur de reconstruction RGB · Ce score n’est pas une probabilité.'
          : 'Score sigmoid du logit anomalie · Ce score n’est pas une probabilité calibrée de défaut.'}{' '}
        Décision : score strictement supérieur au seuil.
      </p>
      <dl className="result-details">
        <div>
          <dt>Modèle</dt>
          <dd>{result.model}</dd>
        </div>
        <div>
          <dt>Catégorie</dt>
          <dd>{result.category}</dd>
        </div>
        <div>
          <dt>Latence d’inférence</dt>
          <dd>
            {result.inference_time_ms.toLocaleString('fr-FR', { maximumFractionDigits: 1 })} ms
          </dd>
        </div>
        <div>
          <dt>Aller-retour /predict</dt>
          <dd>{elapsed.toLocaleString('fr-FR', { maximumFractionDigits: 0 })} ms</dd>
        </div>
        <div className="full">
          <dt>Identifiant de requête /predict</dt>
          <dd className="mono">{result.request_id}</dd>
        </div>
        <div className="full">
          <dt>Version du modèle · SHA256</dt>
          <dd className="mono small">{result.version}</dd>
        </div>
      </dl>
    </section>
  );
}

export function Explanation({ result }: { result: VisualizedPrediction }) {
  const [view, setView] = useState<'overlay' | 'heatmap' | 'image'>('overlay');
  const visual = result.visualization;
  const gradcam = visual.kind === 'gradcam';
  const labels = { overlay: 'Superposition', heatmap: 'Carte seule', image: 'Image préparée' };
  return (
    <div className="explanation">
      <div className="explanation-toolbar">
        <div>
          <h3>{gradcam ? 'Grad-CAM' : 'Heatmap de reconstruction'}</h3>
          <p>{gradcam ? 'Attribution du logit anomalie' : 'Erreur absolue moyenne RGB'}</p>
        </div>
        <span className="tag">{result.model}</span>
      </div>
      <div className="segmented" aria-label="Vue de la visualisation">
        {(['overlay', 'heatmap', 'image'] as const).map((key) => (
          <button key={key} type="button" aria-pressed={view === key} onClick={() => setView(key)}>
            {labels[key]}
          </button>
        ))}
      </div>
      <div className="visual-frame">
        <img
          src={`data:image/png;base64,${visual[`${view}_png_base64`]}`}
          alt={`${labels[view]} : ${gradcam ? 'Grad-CAM' : 'erreur de reconstruction'} pour ${result.category}`}
        />
      </div>
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
            : 'Intensité de l’erreur de reconstruction sur une échelle absolue L1 [0, 1]. Le padding est exclu du calcul.'}
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
