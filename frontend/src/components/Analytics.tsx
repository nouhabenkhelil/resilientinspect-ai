import { useState } from 'react';
import { useReducedMotion } from 'motion/react';
import { PerformanceEngineering } from './PerformanceEngineering';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import experiments from '../data/experiments.json';

const categories = { bottle: 'Bouteille', hazelnut: 'Noisette', leather: 'Cuir' };
const colors = { B0: 'var(--chart-b0)', A1: 'var(--chart-a1)', T0: 'var(--chart-t0)', T1: 'var(--chart-t1)', T2: 'var(--chart-t2)' };
const metrics = {
  auroc: {
    label: 'AUROC image',
    help: 'Capacité de classement normal/anormal sur les scores continus. 0,5 correspond à un classement aléatoire.',
  },
  ap: {
    label: 'Average Precision',
    help: 'Moyenne de précision non interpolée sur la courbe précision-rappel ; dépend de la prévalence des anomalies.',
  },
  f1: {
    label: 'F1 image',
    help: 'Moyenne harmonique précision/rappel au seuil de validation original.',
  },
  precision: {
    label: 'Précision',
    help: 'TP / (TP + FP). Proportion des alertes correspondant à une anomalie connue.',
  },
  recall: {
    label: 'Rappel',
    help: 'TP / (TP + FN). Proportion des anomalies détectées au seuil figé.',
  },
  fpr: {
    label: 'Faux positifs',
    help: 'FP / (FP + TN). Proportion des images normales signalées anormales ; plus faible est préférable.',
  },
};
type Metric = keyof typeof metrics;
type Model = keyof typeof colors;
const percent = (n: number | null | undefined) =>
  n == null
    ? 'Non disponible'
    : `${(n * 100).toLocaleString('fr-FR', { maximumFractionDigits: 2 })} %`;
const score = (n: number) => n.toLocaleString('fr-FR', { maximumSignificantDigits: 10 });
const tooltipStyle = {
  background: 'var(--surface, #111827)',
  color: 'var(--text, #f1f5f9)',
  border: '1px solid var(--border, #253449)',
  borderRadius: 10,
};

export function Analytics() {
  const reducedMotion = useReducedMotion();
  const [category, setCategory] = useState('all');
  const [architecture, setArchitecture] = useState('all');
  const [metric, setMetric] = useState<Metric>('auroc');
  const [selected, setSelected] = useState('T2/bottle');
  const modelNames = experiments.models.filter(
    (m) =>
      architecture === 'all' ||
      (architecture === 'ae' ? ['B0', 'A1'].includes(m) : m.startsWith('T')),
  );
  const records = experiments.records.filter(
    (r) => modelNames.includes(r.model) && (category === 'all' || r.category === category),
  );
  const chartRows = (category === 'all' ? experiments.categories : [category]).map((c) => ({
    category: categories[c as keyof typeof categories],
    ...Object.fromEntries(
      records.filter((r) => r.category === c).map((r) => [r.model, r.image[metric]]),
    ),
  }));
  const selectedRecord = records.find((r) => `${r.model}/${r.category}` === selected) || records[0];
  const params = modelNames
    .map((model) =>
      experiments.records.find(
        (r) => r.model === model && r.category === (category === 'all' ? 'bottle' : category),
      )!,
    )
    .map((r) => ({ model: r.model, total: r.parameters.total, trainable: r.parameters.trainable }));
  const transferRows = records.filter((r) => r.synthetic_validation !== null);

  return (
    <div className="analytics-page page-stack">
      <PerformanceEngineering/>
      <div className="analytics-filters toolbar">
        <label>
          Architecture
          <select
            aria-label="Architecture analytique"
            value={architecture}
            onChange={(e) => setArchitecture(e.target.value)}
          >
            <option value="all">Les cinq variantes</option>
            <option value="ae">Autoencodeurs B0 / A1</option>
            <option value="transfer">EfficientNet T0 / T1 / T2</option>
          </select>
        </label>
        <label>
          Catégorie
          <select
            aria-label="Catégorie analytique"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            <option value="all">Les trois catégories</option>
            {Object.entries(categories).map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Métrique
          <select
            aria-label="Métrique scientifique"
            value={metric}
            onChange={(e) => setMetric(e.target.value as Metric)}
          >
            {Object.entries(metrics).map(([v, info]) => (
              <option key={v} value={v}>
                {info.label}
              </option>
            ))}
          </select>
        </label>
        <span className="badge">Archives officielles · seed 42</span>
      </div>

      <section className="panel chart-card" aria-labelledby="performance-chart-title">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">TEST RÉEL · MVTEC</span>
            <h2 id="performance-chart-title">{metrics[metric].label} par catégorie</h2>
          </div>
          <span title={metrics[metric].help} tabIndex={0} className="badge">
            À propos de la métrique
          </span>
        </div>
        <p className="muted">
          {metrics[metric].help} Les valeurs comparent une métrique commune, jamais l’amplitude des
          scores AE et sigmoid.
        </p>
        <div
          className="chart-frame"
          style={{ height: 300, minWidth: 0 }}
          role="img"
          aria-label={`Comparaison ${metrics[metric].label} des modèles sur le test réel. Valeurs exactes dans le tableau suivant.`}
        >
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={chartRows}
              margin={{ top: 18, right: 12, left: 0, bottom: 4 }}
              accessibilityLayer
            >
              <CartesianGrid
                vertical={false}
                stroke="var(--border, #253449)"
                strokeDasharray="3 5"
              />
              <XAxis
                dataKey="category"
                tick={{ fill: 'var(--muted, #94a3b8)', fontSize: 14 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                domain={[0, 1]}
                tickFormatter={(n) => `${Math.round(n * 100)}%`}
                tick={{ fill: 'var(--muted, #94a3b8)', fontSize: 13 }}
                axisLine={false}
                tickLine={false}
                width={50}
              />
              <Tooltip
                contentStyle={tooltipStyle}
                formatter={(value) => percent(Number(value))}
                cursor={{ fill: 'rgba(148,163,184,.06)' }}
              />
              <Legend />
              {modelNames.map((model) => (
                <Bar
                  key={model}
                  dataKey={model}
                  fill={colors[model as Model]}
                  radius={[4, 4, 0, 0]}
                  maxBarSize={42}
                  isAnimationActive={!reducedMotion} animationDuration={380} animationEasing="ease-out"
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="table-scroll">
          <table className="metric-table">
            <caption>Valeurs archivées et dérivées des comptages officiels</caption>
            <thead>
              <tr>
                <th>Modèle</th>
                <th>Catégorie</th>
                <th>AUROC</th>
                <th>AP</th>
                <th>F1</th>
                <th>Précision</th>
                <th>Rappel</th>
                <th>FPR</th>
              </tr>
            </thead>
            <tbody>
              {records.map((r) => (
                <tr key={`${r.model}/${r.category}`}>
                  <th>{r.model}</th>
                  <td>{categories[r.category as keyof typeof categories]}</td>
                  {(['auroc', 'ap', 'f1', 'precision', 'recall', 'fpr'] as Metric[]).map((m) => (
                    <td key={m}>{percent(r.image[m])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="analytics-grid">
        <section className="panel chart-card" aria-labelledby="macro-title">
          <span className="eyebrow">MOYENNE NON PONDÉRÉE</span>
          <h2 id="macro-title">Synthèse macro</h2>
          <p className="muted">
            Moyenne des trois catégories, sans mélange des scores. Indépendante du filtre de
            catégorie.
          </p>
          <div className="macro-list">
            {experiments.macro
              .filter((r) => modelNames.includes(r.model))
              .map((r) => (
                <div className="macro-row" key={r.model}>
                  <strong style={{ color: colors[r.model as Model] }}>{r.model}</strong>
                  <span>{metrics[metric].label}</span>
                  <strong className="mono">{percent(r.image[metric])}</strong>
                </div>
              ))}
          </div>
        </section>
        <section className="panel chart-card" aria-labelledby="confusion-title">
          <span className="eyebrow">SEUIL DE VALIDATION FIGÉ</span>
          <h2 id="confusion-title">Matrice de confusion</h2>
          <label>
            Rapport
            <select
              aria-label="Rapport de matrice de confusion"
              value={`${selectedRecord.model}/${selectedRecord.category}`}
              onChange={(e) => setSelected(e.target.value)}
            >
              {records.map((r) => (
                <option key={`${r.model}/${r.category}`} value={`${r.model}/${r.category}`}>
                  {r.model} · {categories[r.category as keyof typeof categories]}
                </option>
              ))}
            </select>
          </label>
          <p className="muted">
            {selectedRecord.images} images test · seuil{' '}
            <span className="mono">{score(selectedRecord.threshold)}</span>
          </p>
          <table className="confusion-grid">
            <caption>Vérité terrain en lignes · décision en colonnes</caption>
            <thead>
              <tr>
                <th scope="col">Réel / prédit</th>
                <th scope="col">Normal</th>
                <th scope="col">Anormal</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th scope="row">Normal</th>
                <td className="correct">
                  <strong>{selectedRecord.confusion.tn}</strong>
                  <span>TN</span>
                </td>
                <td>
                  <strong>{selectedRecord.confusion.fp}</strong>
                  <span>FP</span>
                </td>
              </tr>
              <tr>
                <th scope="row">Anormal</th>
                <td>
                  <strong>{selectedRecord.confusion.fn}</strong>
                  <span>FN</span>
                </td>
                <td className="correct">
                  <strong>{selectedRecord.confusion.tp}</strong>
                  <span>TP</span>
                </td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>

      <section className="panel chart-card">
        <span className="eyebrow">LOCALISATION · AUTOENCODEURS UNIQUEMENT</span>
        <h2>Mesures pixel et segmentation</h2>
        <p className="muted">
          Dice et IoU micro sur toutes les images de la catégorie, normales incluses. Les trois
          modèles EfficientNet ne produisent pas de segmentation.
        </p>
        {records.some((r) => r.pixel) ? (
          <div className="table-scroll">
            <table className="metric-table">
              <thead>
                <tr>
                  <th>Modèle</th>
                  <th>Catégorie</th>
                  <th>AUROC pixel</th>
                  <th>AP pixel</th>
                  <th>Dice micro</th>
                  <th>IoU micro</th>
                </tr>
              </thead>
              <tbody>
                {records
                  .filter((r) => r.pixel)
                  .map((r) => (
                    <tr key={`${r.model}/${r.category}`}>
                      <th>{r.model}</th>
                      <td>{categories[r.category as keyof typeof categories]}</td>
                      <td>{percent(r.pixel?.auroc)}</td>
                      <td>{percent(r.pixel?.ap)}</td>
                      <td>{percent(r.pixel?.dice)}</td>
                      <td>{percent(r.pixel?.iou)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="empty-state">
            Aucune métrique pixel pour cette sélection. Grad-CAM est une attribution relative.
          </p>
        )}
      </section>

      <section className="panel chart-card">
        <span className="eyebrow">ÉCART DE DOMAINE</span>
        <h2>Validation synthétique / test réel</h2>
        <p className="muted">
          La validation synthétique sert à l’apprentissage et au contrôle de parité. Elle ne
          remplace pas la généralisation sur les anomalies réelles. Mesures calculées depuis les
          scores de validation archivés, au seuil original ; aucun nouveau seuil.
        </p>
        {transferRows.length ? (
          <>
            <div
              className="chart-frame domain-chart"
              style={{ height: 280, minWidth: 0 }}
              role="img"
              aria-label="AUROC de validation synthétique comparée au test réel, valeurs dans le tableau suivant. Graphique défilable horizontalement."
            >
              <ResponsiveContainer width="100%" height="100%" minWidth={620}>
                <BarChart
                  data={transferRows.map((r) => ({
                    name: `${r.model} · ${r.category}`,
                    validation: r.synthetic_validation!.auroc,
                    test: r.image.auroc,
                  }))}
                  accessibilityLayer
                >
                  <CartesianGrid vertical={false} stroke="var(--border, #253449)" />
                  <XAxis
                    dataKey="name"
                    tick={{ fill: 'var(--muted, #94a3b8)', fontSize: 12 }}
                    interval={0}
                    angle={-20}
                    height={65}
                    textAnchor="end"
                  />
                  <YAxis domain={[0, 1]} tick={{ fill: 'var(--muted, #94a3b8)' }} width={40} />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Legend />
                  <Bar
                    dataKey="validation"
                    name="AUROC val synthétique"
                    fill="var(--accent2)"
                    isAnimationActive={!reducedMotion} animationDuration={380} animationEasing="ease-out"
                  />
                  <Bar
                    dataKey="test"
                    name="AUROC test réel"
                    fill="var(--chart-a1)"
                    isAnimationActive={!reducedMotion} animationDuration={380} animationEasing="ease-out"
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="table-scroll">
              <table className="metric-table">
                <thead>
                  <tr>
                    <th>Modèle / catégorie</th>
                    <th>AUROC val synthétique</th>
                    <th>AUROC test réel</th>
                    <th>F1 val synthétique</th>
                    <th>F1 test réel</th>
                  </tr>
                </thead>
                <tbody>
                  {transferRows.map((r) => (
                    <tr key={`${r.model}/${r.category}`}>
                      <th>
                        {r.model} / {r.category}
                      </th>
                      <td>{percent(r.synthetic_validation?.auroc)}</td>
                      <td>{percent(r.image.auroc)}</td>
                      <td>{percent(r.synthetic_validation?.f1)}</td>
                      <td>{percent(r.image.f1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <p className="empty-state">
            Sélectionnez EfficientNet pour afficher la validation synthétique.
          </p>
        )}
      </section>

      <section className="panel chart-card">
        <span className="eyebrow">COMPLEXITÉ ARCHITECTURALE</span>
        <h2>Paramètres des modèles</h2>
        <p className="muted">
          Comptages archivés, pas une mesure de RAM ni de latence. A1 : nombre de paramètres
          entraînables non disponible dans les sources retenues.
        </p>
        <div
          className="chart-frame"
          style={{ height: 280, minWidth: 0 }}
          role="img"
          aria-label="Nombre de paramètres totaux et entraînables, valeurs exactes dans le tableau suivant."
        >
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={params} accessibilityLayer>
              <CartesianGrid vertical={false} stroke="var(--border, #253449)" />
              <XAxis dataKey="model" tick={{ fill: 'var(--muted, #94a3b8)' }} />
              <YAxis
                tickFormatter={(n) => `${n / 1e6} M`}
                tick={{ fill: 'var(--muted, #94a3b8)' }}
                width={60}
              />
              <Tooltip contentStyle={tooltipStyle} />
              <Legend />
              <Bar
                dataKey="total"
                name="Paramètres totaux"
                fill="var(--accent)"
                isAnimationActive={!reducedMotion} animationDuration={380} animationEasing="ease-out"
              />
              <Bar
                dataKey="trainable"
                name="Paramètres entraînables"
                fill="var(--accent2)"
                isAnimationActive={!reducedMotion} animationDuration={380} animationEasing="ease-out"
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="table-scroll">
          <table className="metric-table">
            <thead>
              <tr>
                <th>Modèle</th>
                <th>Totaux</th>
                <th>Entraînables</th>
              </tr>
            </thead>
            <tbody>
              {params.map((p) => (
                <tr key={p.model}>
                  <th>{p.model}</th>
                  <td>{p.total?.toLocaleString('fr-FR') ?? 'Non disponible'}</td>
                  <td>{p.trainable?.toLocaleString('fr-FR') ?? 'Non disponible'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <aside className="panel scientific-limits">
        <h2>Conditions et limites scientifiques</h2>
        <ul>
          {experiments.limitations.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
        <p className="muted">
          Dates d’évaluation absentes dans les JSON : non renseignées. Les dates de modification des
          sources décrivent les fichiers, pas une date d’expérience. Aucune courbe ROC/PR ni
          intervalle inventé.
        </p>
        <details>
          <summary>Provenance des {experiments.sources.length} sources</summary>
          <ul className="source-list">
            {experiments.sources.map((source) => (
              <li key={source.path}>
                <code>{source.path}</code>
                <span className="mono">SHA256 {source.sha256}</span>
                <small>
                  Fichier modifié le {new Date(source.modified_utc).toLocaleDateString('fr-FR')} ·{' '}
                  {source.purpose}
                </small>
              </li>
            ))}
          </ul>
        </details>
      </aside>
    </div>
  );
}
