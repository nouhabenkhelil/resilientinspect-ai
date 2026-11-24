import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { ArrowRight, LockKeyhole, LogOut, ShieldCheck } from 'lucide-react';
import { clearPortalHistory, refreshPortalHistory } from '../studio/history';
import { portalRequest, setCsrf, type PortalUser } from './session';
import './portal.css';

interface AuthValue {
  user: PortalUser;
  logout: () => Promise<void>;
}
const AuthContext = createContext<AuthValue | null>(null);
export const usePortalAuth = () => useContext(AuthContext);

export function AccessDenied() {
  return (
    <section className="panel portal-denied" role="alert">
      <LockKeyhole size={30} />
      <span className="eyebrow">ACCÈS 403</span>
      <h2>Un espace réservé.</h2>
      <p>
        Votre rôle ne permet pas d’accéder à cette fonctionnalité. Contactez votre administrateur si
        cet accès est nécessaire.
      </p>
      <a className="secondary" href="#dashboard">
        Retour au Control Center
      </a>
    </section>
  );
}

export function IndustrialAuth({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<PortalUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [reason, setReason] = useState('');
  const channel = useRef<BroadcastChannel | null>(null);
  const generation = useRef(0);
  useEffect(() => {
    let active = true;
    async function load() {
      const attempt = ++generation.current;
      setLoading(true);
      clearPortalHistory();
      try {
        const response = await fetch('/api/auth/session', {
          credentials: 'same-origin',
          cache: 'no-store',
        });
        if (!response.ok) throw new Error('Connexion requise.');
        const data = await response.json();
        if (!active || attempt !== generation.current) return;
        setCsrf(data.csrf_token);
        setUser(data.user);
        await refreshPortalHistory();
      } catch {
        if (active && attempt === generation.current) {
          setCsrf('');
          setUser(null);
        }
      } finally {
        if (active && attempt === generation.current) setLoading(false);
      }
    }
    function invalid() {
      generation.current++;
      clearPortalHistory();
      setCsrf('');
      setUser(null);
      setLoading(false);
      setReason('Votre session a expiré ou a été révoquée. Reconnectez-vous.');
    }
    void load();
    window.addEventListener('ri-session-expired', invalid);
    const visible = () => {
      if (document.visibilityState === 'visible') void load();
    };
    document.addEventListener('visibilitychange', visible);
    if (typeof BroadcastChannel !== 'undefined') {
      channel.current = new BroadcastChannel('ri-portal-session');
      channel.current.onmessage = () => {
        void load();
      };
      channel.current.postMessage('changed');
    }
    return () => {
      active = false;
      channel.current?.close();
      window.removeEventListener('ri-session-expired', invalid);
      document.removeEventListener('visibilitychange', visible);
    };
  }, []);
  async function logout() {
    generation.current++;
    try {
      const result = await portalRequest<{ logout_url: string }>('/api/auth/logout', {
        method: 'POST',
      });
      window.location.assign(result.logout_url);
    } finally {
      clearPortalHistory();
      setCsrf('');
      setUser(null);
      setReason('Votre session a été fermée.');
      channel.current?.postMessage('changed');
    }
  }
  if (loading)
    return (
      <main className="portal-auth">
        <div className="panel" role="status">
          Vérification de votre session…
        </div>
      </main>
    );
  if (!user)
    return (
      <main className="portal-auth">
        <div className="portal-auth-art" aria-hidden="true">
          <div className="portal-orbit" />
          <span>VISION · PRÉCISION · CONFIANCE</span>
        </div>
        <section className="panel portal-login">
          <a className="brand" href="/">
            <img src="/logo.svg" alt="" width="48" height="48" />
            <span>
              ResilientInspect <b>AI</b>
              <small>INDUSTRIAL INTELLIGENCE</small>
            </span>
          </a>
          <span className="eyebrow">
            <ShieldCheck size={15} /> ESPACE PROFESSIONNEL
          </span>
          <h1>
            Votre atelier.
            <br />
            Votre accès.
          </h1>
          <p>
            Retrouvez vos inspections, vos résultats et les outils de vision industrielle dans un
            espace à accès contrôlé.
          </p>
          {reason && (
            <div className="notice warning" role="alert">
              {reason}
            </div>
          )}
          <a className="primary portal-login-button" href="/api/auth/login">
            Se connecter <ArrowRight size={18} />
          </a>
          <p className="small muted">
            Accès provisionné par votre administrateur. Aucune inscription publique.
          </p>
        </section>
      </main>
    );
  return <AuthContext.Provider value={{ user, logout }}>{children}</AuthContext.Provider>;
}

export function PortalProfile() {
  const auth = usePortalAuth();
  const [error, setError] = useState('');
  if (!auth) return null;
  return (
    <section className="panel portal-profile">
      <span className="eyebrow">VOTRE PROFIL</span>
      <h2>{auth.user.name}</h2>
      <dl className="technical-details">
        <div>
          <dt>Rôle</dt>
          <dd>{auth.user.role}</dd>
        </div>
        <div>
          <dt>Adresse vérifiée</dt>
          <dd>{auth.user.email || 'Non communiquée'}</dd>
        </div>
        <div>
          <dt>Identifiant</dt>
          <dd>
            <code>{auth.user.id}</code>
          </dd>
        </div>
      </dl>
      <p>
        Les autorisations sont vérifiées par le serveur. Les sessions expirées ou révoquées doivent
        être renouvelées auprès de votre fournisseur d’identité.
      </p>
      {error && <p role="alert">{error}</p>}
      <button
        className="secondary"
        onClick={() =>
          void auth
            .logout()
            .catch(() => setError('La session locale est fermée. Vérifiez votre connexion.'))
        }
      >
        <LogOut size={16} />
        Déconnexion
      </button>
    </section>
  );
}
