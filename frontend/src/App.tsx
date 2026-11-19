import { lazy, Suspense, useEffect, useState } from 'react';
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
} from 'lucide-react';
import SmartInspection from './SmartInspection';
import { ComparisonLab } from './components/ComparisonLab';
import { Dashboard, HistoryPage, SystemMonitor } from './components/StudioPages';
import { readHistory, type HistoryEntry } from './studio/history';
import { useSystem } from './studio/useSystem';
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
    description: 'Un journal local léger. Vos images ne sont pas enregistrées.',
    icon: History,
  },
];
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
  const [page, setPage] = useState(pageFromHash);
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [theme, setTheme] = useState(() => stored('ri.theme', 'dark'));
  const [demo, setDemo] = useState(false);
  const [history, setHistory] = useState<HistoryEntry[]>(readHistory);
  const [notice, setNotice] = useState('');
  const system = useSystem();
  const current = pages.find((p) => p.id === page)!;
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
      className={`app-shell ${collapsed ? 'sidebar-collapsed' : ''} ${mobileOpen ? 'mobile-nav-open' : ''} ${demo ? 'demo-mode' : ''}`}
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
      <aside className="sidebar">
        <a className="brand" href="#dashboard" onClick={() => navigate('dashboard')}>
          <img src="/logo.svg" alt="" width="44" height="44" />
          <span>
            ResilientInspect <b>AI</b>
            <small>INDUSTRIAL INTELLIGENCE</small>
          </span>
        </a>
        <span className="workspace-label">
          WORKSPACE <span>2.0</span>
        </span>
        <nav aria-label="Navigation principale">
          {pages.map((p) => (
            <a
              key={p.id}
              href={`#${p.id}`}
              aria-current={page === p.id ? 'page' : undefined}
              title={collapsed ? p.name : undefined}
              onClick={() => navigate(p.id)}
            >
              <p.icon size={19} />
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
          <p>
            Décision assistée.
            <br />
            L’expertise humaine reste centrale.
          </p>
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
          aria-label="Fermer la navigation"
          onClick={() => setMobileOpen(false)}
        />
      )}
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="icon-button mobile-menu"
              aria-label="Ouvrir la navigation"
              onClick={() => setMobileOpen((v) => !v)}
            >
              <Menu size={20} />
            </button>
            <span>Workspace</span>
            <span>/</span>
            <strong>{current.name}</strong>
          </div>
          <div className="toolbar">
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
                setCollapsed(true);
              }}
            >
              <Presentation size={19} />
            </button>
          </div>
        </header>
        <main id="main-content" tabIndex={-1}>
          <div className="page-heading">
            <div>
              <div className="eyebrow accent">
                INDUSTRIAL INTELLIGENCE STUDIO <span className="heading-separator">/</span>{' '}
                {current.name.toUpperCase()}
              </div>
              <h1>{current.title}</h1>
              <p>{current.description}</p>
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
          {page === 'dashboard' && (
            <Dashboard system={system} history={history} navigate={navigate} />
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
          {page === 'history' && <HistoryPage entries={history} />}
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
