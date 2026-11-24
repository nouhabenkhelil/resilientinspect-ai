import { useEffect, useState } from 'react';
import { portalRequest, type PortalUser } from './session';

export function PortalAdmin() {
  const [users, setUsers] = useState<PortalUser[]>([]);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  async function load() {
    try {
      setUsers((await portalRequest<{ items: PortalUser[] }>('/api/admin/users')).items);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    void load();
  }, []);
  async function action(id: string, revoke: boolean, enabled: boolean) {
    try {
      await portalRequest(`/api/admin/users/${id}/${revoke ? 'revoke-sessions' : 'enabled'}`, {
        method: revoke ? 'POST' : 'PATCH',
        ...(revoke
          ? {}
          : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled }) }),
      });
      setMessage(revoke ? 'Sessions révoquées.' : 'Compte mis à jour.');
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  return (
    <section className="panel">
      <span className="eyebrow">ADMINISTRATION</span>
      <h2>Utilisateurs et sessions</h2>
      <p>
        Les comptes et rôles sont provisionnés dans le fournisseur d’identité. Ici, un
        administrateur peut suspendre un accès ou révoquer ses sessions.
      </p>
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      {message && <p role="status">{message}</p>}
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Utilisateur</th>
              <th>Rôle</th>
              <th>Accès</th>
              <th>Sessions</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>
                  {u.name}
                  <small className="muted"> {u.email}</small>
                </td>
                <td>{u.role}</td>
                <td>{u.enabled ? 'Actif' : 'Suspendu'}</td>
                <td>
                  <button
                    className="text-button"
                    onClick={() => void action(u.id, true, u.enabled)}
                  >
                    Révoquer les sessions
                  </button>
                </td>
                <td>
                  <button
                    className="secondary"
                    onClick={() => void action(u.id, false, !u.enabled)}
                  >
                    {u.enabled ? 'Suspendre' : 'Réactiver'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function PortalAudit() {
  const [events, setEvents] = useState<Record<string, string | null>[]>([]);
  const [error, setError] = useState('');
  useEffect(() => {
    void portalRequest<{ items: Record<string, string | null>[] }>('/api/audit')
      .then((r) => setEvents(r.items))
      .catch((e) => setError(e.message));
  }, []);
  return (
    <section className="panel">
      <span className="eyebrow">TRAÇABILITÉ</span>
      <h2>Événements d’audit accessibles</h2>
      <p>
        Événements limités à votre périmètre. Aucune image, aucun cookie ni token n’est enregistré
        dans ce journal.
      </p>
      {error && <p role="alert">{error}</p>}
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Date UTC</th>
              <th>Action</th>
              <th>Résultat</th>
              <th>Corrélation</th>
            </tr>
          </thead>
          <tbody>
            {events.map((e) => (
              <tr key={e.id}>
                <td>{e.created_at}</td>
                <td>{e.action}</td>
                <td>{e.outcome}</td>
                <td>
                  <code>{e.request_id}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
