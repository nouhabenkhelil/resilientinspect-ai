import { useState } from 'react';
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
import raw from '../data/onnx-performance.json';
type Measures = { mean_ms: number; p50_ms: number; p95_ms: number; images_per_second: number };
type Row = {
  model: string;
  category: string;
  parity: string;
  decision_changes: number;
  score: { pytorch: Measures; onnxruntime: Measures; speedup_mean: number };
  sizes: { checkpoint: number; weights: number; onnx: number };
  normal_examples: number;
  synthetic_examples: number;
};
const report = raw as unknown as {
  status: string;
  environment: Record<string, unknown>;
  hardware: string;
  models: Row[];
};
export function PerformanceEngineering() {
  const [category, setCategory] = useState('bottle');
  const [metric, setMetric] = useState<'p50_ms' | 'p95_ms' | 'images_per_second'>('p50_ms');
  const rows = report.models.filter((r) => r.category === category);
  return (
    <section className="panel chart-card performance-engineering">
      <span className="eyebrow">PERFORMANCE ENGINEERING · CPU FP32</span>
      <h2>PyTorch / ONNX Runtime</h2>
      <p className="muted">
        Mesures techniques distinctes des performances de classification. Batch 1, deux threads, 20
        warm-ups et 100 mesures. Entrée préparée → score, sans Grad-CAM ni réseau HTTP.
      </p>
      {report.status !== 'measured' ? (
        <p className="empty-state">Aucun benchmark validé exporté. Aucune accélération supposée.</p>
      ) : (
        <>
          <div className="configuration">
            <label>
              Catégorie du benchmark
              <select
                aria-label="Catégorie du benchmark"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              >
                {['bottle', 'hazelnut', 'leather'].map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
            <label>
              Métrique technique
              <select
                aria-label="Métrique du benchmark"
                value={metric}
                onChange={(e) => setMetric(e.target.value as typeof metric)}
              >
                <option value="p50_ms">Latence p50 (ms)</option>
                <option value="p95_ms">Latence p95 (ms)</option>
                <option value="images_per_second">Débit séquentiel (images/s)</option>
              </select>
            </label>
          </div>
          <div
            className="chart-frame"
            role="img"
            aria-label={`Benchmark mesuré ${metric} PyTorch versus ONNX Runtime`}
          >
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={rows.map((r) => ({
                  model: r.model,
                  PyTorch: r.score.pytorch[metric],
                  ONNX: r.score.onnxruntime[metric],
                }))}
                accessibilityLayer
              >
                <CartesianGrid stroke="var(--border)" vertical={false} />
                <XAxis dataKey="model" />
                <YAxis />
                <Tooltip
                  contentStyle={{
                    background: 'var(--surface)',
                    borderColor: 'var(--border)',
                    color: 'var(--text)',
                  }}
                />
                <Legend />
                <Bar dataKey="PyTorch" fill="var(--accent)" isAnimationActive={false} />
                <Bar dataKey="ONNX" fill="var(--accent2)" isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="table-scroll">
            <table>
              <caption>Score complet · valeurs mesurées, sans explication</caption>
              <thead>
                <tr>
                  <th>Modèle</th>
                  <th>Moteur</th>
                  <th>p50 ms</th>
                  <th>p95 ms</th>
                  <th>Images/s</th>
                  <th>Facteur PT/ORT</th>
                </tr>
              </thead>
              <tbody>
                {rows.flatMap((r) =>
                  (['pytorch', 'onnxruntime'] as const).map((engine) => (
                    <tr key={`${r.model}${engine}`}>
                      <th>{r.model}</th>
                      <td>{engine}</td>
                      <td>{r.score[engine].p50_ms.toFixed(3)}</td>
                      <td>{r.score[engine].p95_ms.toFixed(3)}</td>
                      <td>{r.score[engine].images_per_second.toFixed(2)}</td>
                      <td>{r.score.speedup_mean.toFixed(2)}×</td>
                    </tr>
                  )),
                )}
              </tbody>
            </table>
          </div>
          <div className="table-scroll">
            <table>
              <caption>Parité et tailles · Mo décimaux</caption>
              <thead>
                <tr>
                  <th>Modèle</th>
                  <th>Parité</th>
                  <th>Normaux + synthétiques</th>
                  <th>Décisions limites</th>
                  <th>Checkpoint entraînement</th>
                  <th>Poids inférence</th>
                  <th>Graphe ONNX</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.model}>
                    <th>{r.model}</th>
                    <td>{r.parity}</td>
                    <td>
                      {r.normal_examples} + {r.synthetic_examples}
                    </td>
                    <td>{r.decision_changes}</td>
                    <td>{(r.sizes.checkpoint / 1e6).toFixed(2)}</td>
                    <td>{(r.sizes.weights / 1e6).toFixed(2)}</td>
                    <td>{(r.sizes.onnx / 1e6).toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="scientific-note">
            {report.hardware}. Un facteur inférieur à 1 signifie qu’ONNX est plus lent. Résultats
            propres à ce matériel et ce runtime.
          </p>
          <details>
            <summary>Environnement du benchmark</summary>
            <pre className="mono small">{JSON.stringify(report.environment, null, 2)}</pre>
          </details>
        </>
      )}
    </section>
  );
}
