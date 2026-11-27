import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import {
  Activity,
  BarChart3,
  ChevronLeft,
  Cpu,
  FlaskConical,
  History,
  LayoutDashboard,
  Menu,
  Moon,
  ScanLine,
  Sun,
  Presentation,
  RefreshCw,
  ShieldCheck,
  UserRound,
  ListChecks,
  Files,
  X,
  LogOut,
  ArrowUpRight,
} from 'lucide-react';
import SmartInspection from './SmartInspection';
import { ComparisonLab } from './components/ComparisonLab';
import { Dashboard, HistoryPage, SystemMonitor } from './components/StudioPages';
import { readHistory, type HistoryEntry } from './studio/history';
import { useSystem } from './studio/useSystem';
import { PORTAL_MODE } from './portal/session';
import { AccessDenied, PortalProfile, usePortalAuth } from './portal/Auth';
import { PortalHistory } from './portal/History';
import { PortalAdmin, PortalAudit } from './portal/Admin';
import { BatchInspection } from './portal/BatchInspection';
const Analytics = lazy(() =>
  import('./components/Analytics').then((m) => ({ default: m.Analytics })),
);
const pages = [
  {
    id: 'dashboard',
    name: 'Control Center',
    title: 'Le contrôle, en perspective.',
    description: 'Votre espace de supervision et d’inspection visuelle assistée par IA.',
    icon: LayoutDashboard,
  },
  {
    id: 'inspection',
    name: 'Smart Inspection',
    title: 'Un regard plus précis.',
    description: 'Inspectez une image et explorez les régions qui influencent la décision.',
    icon: ScanLine,
  },
  {
    id: 'comparison',
    name: 'Comparison Lab',
    title: 'Confrontez les regards.',
    description: 'Une même image, des architectures différentes. Comparez sans fusionner.',
    icon: FlaskConical,
  },
  {
    id: 'analytics',
    name: 'Model Analytics',
    title: 'La preuve par les mesures.',
    description: 'Résultats expérimentaux authentiques · protocoles et seuils figés.',
    icon: BarChart3,
  },
  {
    id: 'monitor',
    name: 'System Monitor',
    title: 'Au cœur du système.',
    description: 'Disponibilité et provenance retournées par votre API locale.',
    icon: Activity,
  },
  {
    id: 'history',
    name: 'Historique',
    title: 'Chaque inspection, documentée.',
    description: PORTAL_MODE
      ? 'Un journal persistant dans votre périmètre autorisé. Vos images ne sont pas enregistrées.'
      : 'Un journal local léger. Vos images ne sont pas enregistrées.',
    icon: History,
  },
  ...(PORTAL_MODE
    ? [
        {
          id: 'batch',
          name: 'Batch Inspection',
          title: 'La production, image par image.',
          description:
            'Analysez des lots privés, suivez leur progression et retrouvez chaque résultat.',
          icon: Files,
        },
        {
          id: 'profile',
          name: 'Mon profil',
          title: 'Votre identité professionnelle.',
          description: 'Profil et session à accès contrôlé.',
          icon: UserRound,
        },
        {
          id: 'admin',
          name: 'Administration',
          title: 'Les accès, sous contrôle.',
          description: 'Comptes provisionnés et révocation des sessions.',
          icon: ShieldCheck,
        },
        {
          id: 'audit',
          name: 'Audit',
          title: 'La trace des opérations.',
          description: 'Événements de votre périmètre autorisé.',
          icon: ListChecks,
        },
      ]
    : []),
];
const roleLabels: Record<string, string> = {
  admin: 'Administrateur', ai_engineer: 'Ingénieur IA', operator: 'Opérateur', auditor: 'Auditeur',
};
function stored(key: string, fallback: string) {
  try {
    return localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}
function pageFromHash() {
  const hash = window.location.hash.slice(1);
  return pages.some((p) => p.id === hash) ? hash : 'dashboard';
}
export default function App() {
  const auth = usePortalAuth();
  const [page, setPage] = useState(pageFromHash);
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(() => window.matchMedia?.('(max-width: 1000px)').matches ?? false);
  const sidebar = useRef<HTMLElement>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  const [theme, setTheme] = useState(() => stored('ri.theme', 'dark'));
  const [demo, setDemo] = useState(false);
  const [history, setHistory] = useState<HistoryEntry[]>(readHistory);
  const [notice, setNotice] = useState('');
  const system = useSystem();
  const current = pages.find((p) => p.id === page)!;
  useEffect(() => {
    const media = window.matchMedia?.('(max-width: 1000px)');
    if (!media) return;
    const change = () => { setIsMobile(media.matches); setMobileOpen(false); };
    media.addEventListener('change', change);
    return () => media.removeEventListener('change', change);
  }, []);
  useEffect(() => {
    if (!mobileOpen || !isMobile) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const controls = () => Array.from(sidebar.current?.querySelectorAll<HTMLElement>(':is(a[href], button:not(:disabled))') ?? [])
      .filter((element) => element.getClientRects().length > 0);
    controls()[0]?.focus();
    function keyboard(event: KeyboardEvent) {
      if (event.key === 'Escape') { event.preventDefault(); setMobileOpen(false); }
      if (event.key !== 'Tab') return;
      const list = controls(), first = list[0], last = list.at(-1);
      if (event.shiftKey && (document.activeElement === first || !sidebar.current?.contains(document.activeElement))) {
        event.preventDefault(); last?.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !sidebar.current?.contains(document.activeElement))) {
        event.preventDefault(); first?.focus();
      }
    }
    document.addEventListener('keydown', keyboard);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', keyboard);
      menuButton.current?.focus();
    };
  }, [mobileOpen, isMobile]);
  const allowed = (id: string) =>
    !PORTAL_MODE ||
    (!!auth &&
      (id === 'admin'
        ? auth.user.permissions.includes('admin')
        : id === 'audit'
          ? auth.user.permissions.includes('audit')
          : id === 'monitor'
            ? auth.user.permissions.includes('readiness')
            : ['inspection', 'comparison'].includes(id)
              ? auth.user.permissions.includes('inspect')
              : true));
  useEffect(() => {
    function navigate() {
      setPage(pageFromHash());
      setMobileOpen(false);
    }
    window.addEventListener('hashchange', navigate);
    return () => window.removeEventListener('hashchange', navigate);
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem('ri.theme', theme);
    } catch {}
  }, [theme]);
  useEffect(() => {
    const update = () => setHistory(readHistory());
    const error = () =>
      setNotice('Stockage local indisponible : cette inspection ne pourra pas être conservée.');
    window.addEventListener('ri-history', update);
    window.addEventListener('storage', update);
    window.addEventListener('ri-storage-error', error);
    return () => {
      window.removeEventListener('ri-history', update);
      window.removeEventListener('storage', update);
      window.removeEventListener('ri-storage-error', error);
    };
  }, []);
  useEffect(() => {
    document.title = `${current.name} · ResilientInspect AI`;
    // New page entries must be visible even after scrolling a long inspection.
    document.scrollingElement?.scrollTo({ top: 0, left: 0, behavior: 'instant' });
  }, [current.name]);
  const status =
    system.health?.status === 'ok'
      ? 'API opérationnelle'
      : system.health
        ? 'API dégradée'
        : system.loading
          ? 'Connexion à l’API'
          : 'API hors ligne';
  function navigate(id: string) {
    window.location.hash = id;
    setPage(id);
    setMobileOpen(false);
  }
  return (
    <div
      data-ui-revision="restore-v3"
      data-motion-revision="visible-v3"
      data-visual-revision="role-themes-v3"
      data-role={PORTAL_MODE && auth ? auth.user.role : undefined}
      className={`app-shell ${collapsed && !isMobile ? 'sidebar-collapsed' : ''} ${mobileOpen ? 'mobile-nav-open' : ''} ${demo ? 'demo-mode' : ''}`}
    >
      <a
        className="skip-link"
        href="#main-content"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById('main-content')?.focus();
        }}
      >
        Aller au contenu
      </a>
      <aside className="sidebar" id="workspace-navigation" ref={sidebar}
        role={mobileOpen && isMobile ? 'dialog' : undefined}
        aria-modal={mobileOpen && isMobile ? true : undefined}
        aria-label={mobileOpen && isMobile ? 'Navigation du studio' : undefined}
        inert={isMobile && !mobileOpen}>
        <button className="icon-button mobile-nav-close" aria-label="Fermer la navigation" onClick={() => setMobileOpen(false)}><X size={19} /></button>
        <a className="brand" href="#dashboard" onClick={() => navigate('dashboard')}>
          <img src="/logo.svg" alt="" width="44" height="44" />
          <span>
            ResilientInspect <b>AI</b>
            <small>INDUSTRIAL INTELLIGENCE</small>
          </span>
        </a>
        <span className="workspace-label">
          WORKSPACE <span>{PORTAL_MODE ? '3.0' : '2.0'}</span>
        </span>
        <nav aria-label="Navigation principale">
          {pages.filter((p) => allowed(p.id)).map((p) => (
              <a
                key={p.id}
                href={`#${p.id}`}
                aria-current={page === p.id ? 'page' : undefined}
                title={collapsed ? p.name : undefined}
                aria-label={p.name}
                onClick={() => navigate(p.id)}
              >
                <p.icon size={18} aria-hidden="true" />
                <span>{p.name}</span>
                {p.id === 'comparison' && <small>LAB</small>}
              </a>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-engine">
            <Cpu size={20} />
            <div>
              <strong>Inférence locale</strong>
              <small>CPU · données sous contrôle</small>
            </div>
          </div>
          {auth && <div className="sidebar-account">
            <a href="#profile" aria-label="Ouvrir mon profil" className="account-identity">
              <span className="user-avatar" aria-hidden="true">{auth.user.name.trim().slice(0, 2).toUpperCase()}</span>
              <span><strong>{auth.user.name}</strong><small>{roleLabels[auth.user.role] ?? auth.user.role}</small></span>
              <ArrowUpRight size={14} aria-hidden="true" />
            </a>
            <button className="icon-button sidebar-logout" aria-label="Déconnexion du portail" title="Déconnexion"
              onClick={() => void auth.logout().catch(() => setNotice('La session locale est fermée. Vérifiez votre connexion.'))}>
              <LogOut size={17} />
            </button>
          </div>}
          <button
            className="text-button collapse-button"
            onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? 'Déployer la navigation' : 'Réduire la navigation'}
          >
            <ChevronLeft size={18} />
            <span>Réduire</span>
          </button>
        </div>
      </aside>
      {mobileOpen && (
        <button
          className="nav-backdrop"
          aria-label="Fermer le panneau de navigation"
          onClick={() => setMobileOpen(false)}
        />
      )}
      <div className="main-shell" inert={mobileOpen && isMobile}>
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="icon-button mobile-menu"
              aria-label="Ouvrir la navigation"
              aria-expanded={mobileOpen}
              aria-controls="workspace-navigation"
              ref={menuButton}
              onClick={() => setMobileOpen((v) => !v)}
            >
              <Menu size={20} />
            </button>
            <span>Workspace</span>
            <span>/</span>
            <strong>{current.name}</strong>
          </div>
          <div className="toolbar">
            {auth && (
              <a className="portal-user" href="#profile">
                <strong>{auth.user.name}</strong>
                <span className="badge role-identity">{roleLabels[auth.user.role] ?? auth.user.role}</span>
              </a>
            )}
            <div
              role="status"
              className={`api-status ${system.health?.status === 'ok' ? 'online' : system.health ? 'degraded' : 'offline'}`}
            >
              <span className="status-dot" />
              {status}
            </div>
            <button
              className="icon-button"
              aria-label="Actualiser le statut API"
              disabled={system.loading}
              onClick={system.refresh}
            >
              <RefreshCw size={17} />
            </button>
            <button
              className="icon-button"
              aria-label={theme === 'dark' ? 'Activer le mode clair' : 'Activer le mode sombre'}
              onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
            >
              {theme === 'dark' ? <Sun size={19} /> : <Moon size={19} />}
            </button>
            <button
              className="icon-button demo-toggle"
              aria-label="Mode démonstration"
              aria-pressed={demo}
              title="Mode démonstration : agrandir, sans données simulées"
              onClick={() => {
                setDemo((d) => !d);
              }}
            >
              <Presentation size={19} />
            </button>
          </div>
        </header>
        <main id="main-content" tabIndex={-1}>
          <div className="page-heading" key={page}>
            <div>
              <div className="eyebrow accent">
                INDUSTRIAL INTELLIGENCE STUDIO <span className="heading-separator">/</span>{' '}
                {current.name.toUpperCase()}
              </div>
              <h1>{current.title}</h1>
              <p>
                {PORTAL_MODE && page === 'history'
                  ? 'Un historique persistant, limité à votre périmètre autorisé.'
                  : current.description}
              </p>
            </div>
            <span className="environment">
              <span className="status-dot" />
              ENVIRONNEMENT LOCAL
            </span>
          </div>
          {notice && (
            <div role="alert" className="notice warning">
              {notice}
              <button onClick={() => setNotice('')} aria-label="Fermer la notification">
                ×
              </button>
            </div>
          )}
          {!allowed(page) ? (
            <AccessDenied />
          ) : (
            <>
              {page === 'dashboard' && (
                <Dashboard system={system} history={history} navigate={navigate} canInspect={allowed('inspection')} />
              )}
              {page === 'inspection' && <SmartInspection />}
              {page === 'comparison' && <ComparisonLab metadata={system.metadata} />}
              {page === 'analytics' && (
                <Suspense
                  fallback={
                    <div className="skeleton panel" role="status">
                      Chargement des mesures officielles…
                    </div>
                  }
                >
                  <Analytics />
                </Suspense>
              )}
              {page === 'monitor' && <SystemMonitor system={system} />}
              {page === 'history' &&
                (PORTAL_MODE ? <PortalHistory /> : <HistoryPage entries={history} />)}
              {page === 'profile' && <PortalProfile />}
              {page === 'batch' && <BatchInspection />}
              {page === 'admin' && <PortalAdmin />}
              {page === 'audit' && <PortalAudit />}
            </>
          )}
          <footer className="page-footer">
            <span>
              ResilientInspect AI <span>·</span> Vision industrielle explicable
            </span>
            <span>
              CPU / FP32 <span>·</span> Validation humaine requise
            </span>
          </footer>
        </main>
      </div>
    </div>
  );
}
