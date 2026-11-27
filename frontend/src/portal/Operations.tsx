import { useEffect, useState } from 'react';
import { portalRequest } from './session';
import { Cpu, Database, Network, ShieldCheck, Workflow } from 'lucide-react';
import { StatusBadge } from '../components/StatusBadge';
interface OperationsData {
  measured_at: string;
  database_up: boolean;
  database_ms: number | null;
  science_up: boolean;
  gateway_up: boolean;
  idp_up: boolean;
  worker_up: boolean | null;
  worker_age_seconds: number | null;
  worker_starts: number | null;
  worker_failures: number | null;
  queue: null | {
    pending: number;
    running: number;
    failed: number;
    retries: number;
    mean_inference_ms: number | null;
    oldest_pending_seconds: number | null;
  };
  storage: null | { free_bytes: number; total_bytes: number };
  models: null | Record<string, number>;
  http: {
    window_seconds: number;
    requests: number;
    errors_5xx: number;
    error_ratio: number | null;
    mean_ms: number | null;
    p95_ms: number | null;
  };
}
export function Operations() {
  const [data, setData] = useState<OperationsData | null>(null),
    [error, setError] = useState('');
  const [events, setEvents] = useState<{ kind: string; error_code: string | null; at: string }[]>(
    [],
  );
  useEffect(() => {
    let active = true,
      pending = false;
    const controller = new AbortController();
    async function load() {
      if (pending) return;
      pending = true;
      try {
        const [snapshot, history] = await Promise.all([
          portalRequest<OperationsData>('/api/operations', { signal: controller.signal }),
          portalRequest<{ items: typeof events }>('/api/operations/events', {
            signal: controller.signal,
          }),
        ]);
        if (active) {
          setData(snapshot);
          setEvents(history.items);
          setError('');
        }
      } catch {
        if (active) setError('Les indicateurs opérationnels ne sont pas accessibles.');
      } finally {
        pending = false;
      }
    }
    void load();
    const timer = setInterval(() => void load(), 15000);
    return () => {
      active = false;
      controller.abort();
      clearInterval(timer);
    };
  }, []);
  const value = (n: number | null | undefined, unit = '') =>
    n == null
      ? 'Non disponible'
      : `${n.toLocaleString('fr-FR', { maximumFractionDigits: 2 })}${unit}`;
  return (
    <section className="panel operations-center" aria-label="Operations Center">
      <span className="eyebrow accent">OPERATIONS CENTER</span>
      <h2>Des mesures, au présent.</h2>
      <p>
        Mesures du portail, sondes HTTP et agrégats SQL réels. Aucune estimation de CPU ou de RAM.
      </p>
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      {!data ? (
        <p role="status">Chargement des indicateurs autorisés…</p>
      ) : (
        <>
          <div className="service-health-grid" aria-label="Santé observée des services">
                {[
                  { name: 'Gateway', up: data.gateway_up, icon: Network },
                  { name: 'PostgreSQL', up: data.database_up, icon: Database },
                  { name: 'Worker · heartbeat récent', up: data.worker_up, icon: Workflow },
                  { name: 'Backend scientifique', up: data.science_up, icon: Cpu },
                  { name: 'Keycloak', up: data.idp_up, icon: ShieldCheck },
                ].map(({name, up, icon: Glyph}) => (
                  <article className="service-health-card" key={name}>
                    <Glyph size={21} aria-hidden="true" /><strong>{name}</strong>
                    <StatusBadge tone={up == null ? 'neutral' : up ? 'positive' : 'negative'} label={up == null ? 'Non disponible' : up ? 'Disponible' : 'Indisponible'} />
                  </article>
                ))}
          </div>
          <dl className="technical-details">
            <div>
              <dt>Images en attente / en cours</dt>
              <dd>
                {value(data.queue?.pending)} / {value(data.queue?.running)}
              </dd>
            </div>
            <div>
              <dt>Durée moyenne moteur · résultats conservés</dt>
              <dd>{value(data.queue?.mean_inference_ms, ' ms')}</dd>
            </div>
            <div>
              <dt>Retries / échecs conservés</dt>
              <dd>
                {value(data.queue?.retries)} / {value(data.queue?.failed)}
              </dd>
            </div>
            <div>
              <dt>Temps SELECT 1 PostgreSQL</dt>
              <dd>{value(data.database_ms, ' ms')}</dd>
            </div>
            <div>
              <dt>Latence HTTP moyenne / p95</dt>
              <dd>
                {value(data.http.mean_ms, ' ms')} / {value(data.http.p95_ms, ' ms')}
              </dd>
            </div>
            <div>
              <dt>HTTP · requêtes / erreurs 5xx</dt>
              <dd>
                {data.http.requests} / {data.http.errors_5xx}
              </dd>
            </div>
            <div>
              <dt>Espace libre · filesystem Docker privé</dt>
              <dd>
                {data.storage
                  ? value(data.storage.free_bytes / 1073741824, ' Gio')
                  : 'Non disponible'}
              </dd>
            </div>
            <div>
              <dt>Modèles admis PyTorch / ONNX</dt>
              <dd>
                {data.models
                  ? `${data.models.pytorch} / ${data.models.onnxruntime}`
                  : 'Non disponible'}
              </dd>
            </div>
          </dl>
          <p className="scientific-note">
            Fenêtre HTTP observée : {data.http.window_seconds} s, au plus 4 096 requêtes récentes.
            Historique Prometheus commencé au déploiement ; les compteurs SQL décrivent les données
            encore conservées. Mesure UTC : {data.measured_at}.
          </p>
          <h3>Événements techniques récents</h3>
          {events.length ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Date UTC</th>
                    <th>Événement</th>
                    <th>Code</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((event, index) => (
                    <tr key={index}>
                      <td>{event.at}</td>
                      <td>{event.kind}</td>
                      <td>{event.error_code || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p>Aucun événement technique correspondant aux critères.</p>
          )}
        </>
      )}
    </section>
  );
}
