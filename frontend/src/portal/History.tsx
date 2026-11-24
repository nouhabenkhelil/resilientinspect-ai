import { useEffect, useState } from 'react';
import { portalRequest, type PortalUser } from './session';
import { usePortalAuth } from './Auth';

interface Inspection {
  id: string;
  owner_id: string;
  model: string;
  category: string;
  engine: string;
  status: string;
  created_at: string;
  anomaly_score: number | null;
  threshold: number | null;
  inference_time_ms: number | null;
  version: string | null;
  calibration_sha256: string | null;
  request_id: string;
}
export function PortalHistory() {
  const auth = usePortalAuth();
  const [items, setItems] = useState<Inspection[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [model, setModel] = useState('');
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<Inspection | null>(null);
  const [users, setUsers] = useState<PortalUser[]>([]);
  const [grantUser, setGrantUser] = useState('');
  const [notice, setNotice] = useState('');
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    const query = new URLSearchParams({
      limit: '20',
      offset: String(offset),
      ...(model ? { model } : {}),
      ...(status ? { status } : {}),
    });
    void portalRequest<{ items: Inspection[]; total: number }>(`/api/inspections?${query}`)
      .then((data) => {
        if (active) {
          setItems(data.items);
          setTotal(data.total);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [offset, model, status]);
  useEffect(() => {
    if (auth?.user.role === 'admin')
      void portalRequest<{ items: PortalUser[] }>('/api/admin/users')
        .then((r) => setUsers(r.items))
        .catch(() => {});
  }, [auth?.user.role]);
  async function details(id: string) {
    try {
      setSelected(await portalRequest<Inspection>(`/api/inspections/${id}`));
      setNotice('');
    } catch (e) {
      setError((e as Error).message);
    }
  }
  return (
    <div className="page-stack portal-history">
      <section className="panel">
        <div className="toolbar">
          <label>
            Modèle
            <select
              aria-label="Modèle historique persistant"
              value={model}
              onChange={(e) => {
                setModel(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">Tous</option>
              {['B0', 'A1', 'T0', 'T1', 'T2'].map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
          </label>
          <label>
            Statut
            <select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">Tous</option>
              <option value="completed">Terminée</option>
              <option value="processing">En cours</option>
              <option value="failed">Refusée / échec</option>
            </select>
          </label>
          <span className="badge">{total} inspections accessibles</span>
        </div>
        <p className="scientific-note">
          Historique persistant PostgreSQL, limité à votre périmètre autorisé. Aucune image
          originale ni heatmap enregistrée. Les durées d’inférence proviennent du moteur réellement
          utilisé.
        </p>
        {error && (
          <div className="notice error" role="alert">
            {error}
          </div>
        )}
        {loading ? (
          <p role="status">Chargement du journal…</p>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Date UTC</th>
                  <th>Modèle / catégorie</th>
                  <th>Moteur</th>
                  <th>Statut</th>
                  <th>Score / seuil</th>
                  <th>Inférence</th>
                  <th>Détails</th>
                </tr>
              </thead>
              <tbody>
                {items.map((r) => (
                  <tr key={r.id}>
                    <td>{new Date(r.created_at).toLocaleString('fr-FR', { timeZone: 'UTC' })}</td>
                    <td>
                      {r.model} / {r.category}
                    </td>
                    <td>{r.engine}</td>
                    <td>{r.status}</td>
                    <td>
                      {r.anomaly_score === null
                        ? '—'
                        : `${r.anomaly_score.toPrecision(6)} / ${r.threshold?.toPrecision(6)}`}
                    </td>
                    <td>
                      {r.inference_time_ms === null ? '—' : `${r.inference_time_ms.toFixed(1)} ms`}
                    </td>
                    <td>
                      <button className="text-button" onClick={() => void details(r.id)}>
                        Détails
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!items.length && (
              <p className="empty-state">Aucune inspection accessible pour ces filtres.</p>
            )}
          </div>
        )}
        <div className="toolbar">
          <button
            className="secondary"
            disabled={offset === 0 || loading}
            onClick={() => setOffset((o) => Math.max(0, o - 20))}
          >
            Précédent
          </button>
          <span>
            {total ? offset + 1 : 0}–{Math.min(offset + 20, total)} / {total}
          </span>
          <button
            className="secondary"
            disabled={offset + 20 >= total || loading}
            onClick={() => setOffset((o) => o + 20)}
          >
            Suivant
          </button>
        </div>
      </section>
      {selected && (
        <section className="panel">
          <h2>Détails de l’inspection</h2>
          <dl className="technical-details">
            {Object.entries(selected).map(([key, value]) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd>
                  <code>{String(value ?? '—')}</code>
                </dd>
              </div>
            ))}
          </dl>
          {auth?.user.role === 'admin' && (
            <div className="toolbar">
              <label>
                Accorder la lecture
                <select value={grantUser} onChange={(e) => setGrantUser(e.target.value)}>
                  <option value="">Choisir un utilisateur</option>
                  {users.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.name} · {u.role}
                    </option>
                  ))}
                </select>
              </label>
              <button
                className="secondary"
                disabled={!grantUser}
                onClick={() =>
                  void portalRequest(`/api/admin/inspections/${selected.id}/grants/${grantUser}`, {
                    method: 'POST',
                  })
                    .then(() => setNotice('Accès de lecture accordé.'))
                    .catch((e) => setError(e.message))
                }
              >
                Accorder
              </button>
            </div>
          )}
          {notice && <p role="status">{notice}</p>}
          <button className="text-button" onClick={() => setSelected(null)}>
            Fermer les détails
          </button>
        </section>
      )}
    </div>
  );
}
