import { useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Check,
  Copy,
  Cpu,
  Download,
  FlaskConical,
  History,
  ScanLine,
  Trash2,
  ArrowUpRight,
} from 'lucide-react';
import type { SystemState } from '../studio/useSystem';
import { clearHistory, exportHistory, SESSION, type HistoryEntry } from '../studio/history';
import { CATEGORIES, MODEL_NAMES } from '../api/contracts';
import { categoryIcons, categoryLabels } from './InspectionTools';
import { Result } from './Result';
import { Operations } from '../portal/Operations';
import SpotlightCard from './reactbits/SpotlightCard';
import CountUp from './reactbits/CountUp';
import ShinyText from './reactbits/ShinyText';
import AnimatedList from './reactbits/AnimatedList';
import experiments from '../data/experiments.json';
import { PORTAL_MODE } from '../portal/session';
import { RevealSection } from './RevealSection';
import { IndustrialHero } from './IndustrialHero';

const stamp = (value: string) =>
  new Date(value).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'medium' });
const number = (value: number) => value.toLocaleString('fr-FR', { maximumSignificantDigits: 10 });
const ms = (value: number) => `${value.toLocaleString('fr-FR', { maximumFractionDigits: 1 })} ms`;

export function CopyButton({ value, label = 'Copier' }: { value: string; label?: string }) {
  const [message, setMessage] = useState('');
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setMessage('Copié');
    } catch {
      setMessage('Copie indisponible : sélectionnez le texte.');
    }
  }
  return (
    <span className="copy-control">
      <button
        type="button"
        className="text-button"
        aria-label={label}
        title={label}
        onClick={() => void copy()}
      >
        {message === 'Copié' ? <Check size={14} /> : <Copy size={14} />}
        <span>{message === 'Copié' ? 'Copié' : label}</span>
      </button>
      <span className="sr-only" role="status">
        {message}
      </span>
    </span>
  );
}

export function Dashboard({
  system,
  history,
  navigate,
  canInspect = true,
}: {
  system: SystemState;
  history: HistoryEntry[];
  navigate: (id: string) => void;
  canInspect?: boolean;
}) {
  const session = PORTAL_MODE ? history : history.filter((r) => r.session === SESSION);
  const alerts = session.filter((r) => r.decision === 'anomaly').length;
  const mean = session.length
    ? session.reduce((sum, r) => sum + r.inference_time_ms, 0) / session.length
    : null;
  const available = system.health?.ready_models ?? system.metadata?.models.length;
  const recent = history.slice(0, 4);
  const stats = [
    {
      label: 'Modèles disponibles',
      value: available,
      suffix: '/ 15',
      icon: Cpu,
      note: 'Disponibilité retournée par l’API',
    },
    {
      label: PORTAL_MODE ? 'Inspections accessibles' : 'Inspections de session',
      value: session.length,
      suffix: '',
      icon: ScanLine,
      note: PORTAL_MODE
        ? '100 dernières analyses terminées au maximum'
        : 'Analyses réellement terminées',
    },
    {
      label: PORTAL_MODE ? 'Alertes du journal' : 'Alertes de session',
      value: alerts,
      suffix: '',
      icon: AlertTriangle,
      note: 'Décisions anormales du modèle',
    },
    {
      label: 'Calcul API moyen',
      value: mean === null ? undefined : Math.round(mean),
      suffix: 'ms',
      icon: Activity,
      note: 'Inférence et explication si demandée · hors HTTP',
    },
  ];
  return (
    <div className="page-stack dashboard-page">
      <section className="hero-panel">
        <div className="hero-copy">
          <span className="eyebrow">
            <ShinyText text="LA VISION, AUGMENTÉE." speed={7} />
          </span>
          <h2>
            De l’image à<br />
            <span className="accent">la compréhension.</span>
          </h2>
          <p>
            Identifiez les anomalies. Confrontez les architectures. Explorez chaque décision avec
            une explication visuelle traçable.
          </p>
          <div className="toolbar">
            {canInspect ? <button className="primary" onClick={() => navigate('inspection')}>
              <ScanLine size={18} />
              Nouvelle inspection
              <ArrowUpRight size={16} />
            </button> : <button className="primary" onClick={() => navigate('history')}><History size={18} />Consulter mon historique</button>}
            {canInspect && <button className="secondary" onClick={() => navigate('comparison')}>
              <FlaskConical size={18} />
              Ouvrir le laboratoire
            </button>}
          </div>
          <div className="hero-footnote">
            <span>3 catégories</span>
            <span>5 variantes</span>
            <span>{system.health?.device === 'cpu' ? 'Inférence CPU' : 'Moteur à confirmer'}</span>
          </div>
        </div>
        <IndustrialHero />
      </section>

      <div className="stat-grid">
        {stats.map((stat, index) => (
          <SpotlightCard
            key={stat.label}
            reveal
            className="stat-card"
          >
            <div className="stat-label">
              <span>{stat.label}</span>
              <stat.icon size={18} />
            </div>
            <div className="stat-value">
              {stat.value === undefined ? (
                <span>—</span>
              ) : (
                <CountUp to={stat.value} duration={0.75} delay={.11 + index * .09} />
              )}
              <small>{stat.value === undefined ? '' : stat.suffix}</small>
            </div>
            <p>{stat.note}</p>
          </SpotlightCard>
        ))}
      </div>

      <div className="bento-grid">
        <section className="panel categories-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">CHAMPS D’INSPECTION</span>
              <h2>Trois matières. Un regard précis.</h2>
            </div>
            <span className="badge">MVTEC · périmètre étudié</span>
          </div>
          <div className="category-tiles">
            {CATEGORIES.map((category) => {
              const Glyph = categoryIcons[category];
              const loaded = system.metadata?.models.filter((m) => m.category === category).length;
              return (
                <button
                  className={`category-tile ${category}`}
                  disabled={!canInspect}
                  key={category}
                  onClick={() => {
                    try {
                      sessionStorage.setItem('ri.next-category', category);
                    } catch {}
                    navigate('inspection');
                  }}
                  aria-label={`Ouvrir une inspection — ${categoryLabels[category]}`}
                >
                  <span className="category-art">
                    <Glyph size={48} strokeWidth={1.15} />
                  </span>
                  <strong>{categoryLabels[category]}</strong>
                  <span>{category}</span>
                  <small>
                    {loaded === undefined
                      ? 'Disponibilité à confirmer'
                      : `${loaded}/5 modèles disponibles`}
                  </small>
                </button>
              );
            })}
          </div>
          <p className="scientific-note">
            Icônes schématiques · aucune image du dataset distribuée dans l’interface.
          </p>
        </section>
        <section className="panel activity-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">
                {PORTAL_MODE ? 'JOURNAL PERSISTANT' : 'JOURNAL DU NAVIGATEUR'}
              </span>
              <h2>Dernières inspections</h2>
            </div>
            <button className="text-button" onClick={() => navigate('history')}>
              Voir le journal
            </button>
          </div>
          {recent.length ? (
            <AnimatedList
              items={recent.map(
                (r) =>
                  `${r.model} · ${categoryLabels[r.category]} · ${r.decision === 'anomaly' ? 'Anormal' : 'Normal'} · ${stamp(r.recorded_at)}`,
              )}
              onItemSelect={() => navigate('history')}
            />
          ) : (
            <div className="empty-state compact">
              <History size={28} />
              <h3>Votre prochaine observation commence ici.</h3>
              <p>{PORTAL_MODE ? 'Aucune inspection accessible dans votre périmètre.' : 'Aucune inspection enregistrée dans ce navigateur.'}</p>
              {canInspect && <button className="text-button" onClick={() => navigate('inspection')}>
                Analyser une image
              </button>}
            </div>
          )}
        </section>
        <RevealSection className="panel official-summary">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">RÉSULTATS EXPÉRIMENTAUX OFFICIELS</span>
              <h2>Mesurer, avant de conclure.</h2>
            </div>
            <button className="text-button" onClick={() => navigate('analytics')}>
              Explorer les mesures
            </button>
          </div>
          <div className="macro-mini">
            {experiments.macro.map((r) => (
              <div key={r.model}>
                <strong>{r.model}</strong>
                <div className="metric-track">
                  <span style={{ width: `${r.image.auroc * 100}%` }} />
                </div>
                <span className="mono">
                  {r.image.auroc.toLocaleString('fr-FR', { maximumFractionDigits: 3 })}
                </span>
              </div>
            ))}
          </div>
          <p className="scientific-note">
            AUROC image macro · moyenne non pondérée de trois catégories sur test réel · seed 42.
            Distincte des statistiques de session. Test déjà consulté, sans validation indépendante
            après sélection.
          </p>
        </RevealSection>
      </div>
      {system.error && (
        <div role="alert" className="notice warning">
          {system.error}
          <button className="text-button" onClick={system.refresh}>
            Réessayer
          </button>
        </div>
      )}
    </div>
  );
}

export function SystemMonitor({ system }: { system: SystemState }) {
  const health = system.health;
  const models = system.metadata?.models || [];
  const status =
    health?.status === 'ok'
      ? 'Disponible'
      : health
        ? 'Dégradée'
        : system.loading
          ? 'Connexion en cours'
          : 'Hors ligne';
  return (
    <div className="page-stack">
      {PORTAL_MODE && <Operations />}
      <div className="toolbar">
        <span className={`badge ${health?.status === 'ok' ? 'normal' : 'warning'}`}>
          API · {status}
        </span>
        <button className="secondary" onClick={system.refresh} disabled={system.loading}>
          <Activity size={17} />
          {system.loading ? 'Actualisation…' : 'Actualiser les données'}
        </button>
        <span className="muted">Contrôle toutes les 30 secondes</span>
      </div>
      {system.error && (
        <div className="notice error" role="alert">
          {system.error}
        </div>
      )}
      <section className="panel system-metrics">
        <dl className="technical-details">
          <div>
            <dt>Version API</dt>
            <dd>{health?.version ?? 'Non disponible'}</dd>
          </div>
          <div>
            <dt>Moteur exposé</dt>
            <dd>{health?.device?.toUpperCase() ?? 'Non disponible'}</dd>
          </div>
          <div>
            <dt>Modèles chargés</dt>
            <dd>
              {health ? `${health.ready_models} / ${health.expected_models}` : 'Non disponible'}
            </dd>
          </div>
          <div>
            <dt>PyTorch / ONNX validés</dt>
            <dd>
              {health?.ready_models_by_engine
                ? `${health.ready_models_by_engine.pytorch} / ${health.ready_models_by_engine.onnxruntime}`
                : 'Non exposé par cette version API'}
            </dd>
          </div>
          <div>
            <dt>Dernier aller-retour de supervision</dt>
            <dd>{system.timings[0] ? ms(system.timings[0].ms) : 'Aucune mesure réussie'}</dd>
          </div>
        </dl>
        <p className="scientific-note">
          Temps mesuré côté navigateur pour les deux GET santé/métadonnées. Aucun indicateur RAM,
          CPU, uptime ou dérive n’est exposé par ces endpoints.
        </p>
      </section>
      <section className="panel">
        <div className="panel-heading">
          <h2>Disponibilité par catégorie</h2>
          <span className="eyebrow">GET /MODEL/METADATA</span>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Catégorie</th>
                {MODEL_NAMES.map((m) => (
                  <th key={m}>{m}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {CATEGORIES.map((c) => (
                <tr key={c}>
                  <th>{categoryLabels[c]}</th>
                  {MODEL_NAMES.map((m) => (
                    <td key={m}>
                      {models.some((row) => row.category === c && row.model === m) ? (
                        <span className="normal">Disponible</span>
                      ) : system.metadata ? (
                        <span className="warning">Indisponible</span>
                      ) : (
                        'Inconnu'
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      {!!system.metadata?.unavailable.length && (
        <section className="panel">
          <h2>Modèles indisponibles</h2>
          {system.metadata.unavailable.map((m) => (
            <div key={`${m.model}/${m.category}`} className="notice warning">
              <strong>
                {m.model} / {m.category}
              </strong>
              <p>{m.reason}</p>
            </div>
          ))}
        </section>
      )}
      <section className="panel monitor-models">
        <h2>Versions et provenance</h2>
        {models.length ? (
          models.map((model) => (
            <details key={`${model.model}/${model.category}`}>
              <summary>
                {model.model} · {categoryLabels[model.category]}{' '}
                <span className="mono">{model.version.slice(0, 12)}</span>
              </summary>
              <p className="small muted">
                Moteurs : {(model.available_engines || ['pytorch']).join(' · ')}. ONNX :{' '}
                {model.engine_validation?.onnxruntime || 'non exposé'}.
              </p>
              <dl className="technical-details">
                <div>
                  <dt>Checkpoint SHA256</dt>
                  <dd>
                    <code>{model.checkpoint_sha256}</code>
                    <CopyButton
                      value={model.checkpoint_sha256}
                      label="Copier le SHA256 du checkpoint"
                    />
                  </dd>
                </div>
                <div>
                  <dt>Calibration SHA256</dt>
                  <dd>
                    <code>{model.calibration_sha256}</code>
                    <CopyButton
                      value={model.calibration_sha256}
                      label="Copier le SHA256 de calibration"
                    />
                  </dd>
                </div>
                <div>
                  <dt>Seuil original</dt>
                  <dd className="mono">{number(model.threshold)}</dd>
                </div>
                <div>
                  <dt>Règle de décision</dt>
                  <dd>{model.decision_rule}</dd>
                </div>
                <div>
                  <dt>Normalisation</dt>
                  <dd>{model.normalization}</dd>
                </div>
              </dl>
              <h3>Environnement d’inférence retourné</h3>
              <dl className="technical-details">
                {Object.entries(model.serving_environment).map(([key, value]) => (
                  <div key={key}>
                    <dt>{key}</dt>
                    <dd>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd>
                  </div>
                ))}
              </dl>
            </details>
          ))
        ) : (
          <p className="empty-state">
            Métadonnées indisponibles. Actualisez lorsque le backend est accessible.
          </p>
        )}
      </section>
      <section className="panel">
        <h2>Mesures HTTP de cette session</h2>
        {system.timings.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Contrôle réussi</th>
                  <th>Aller-retour</th>
                </tr>
              </thead>
              <tbody>
                {system.timings.map((t) => (
                  <tr key={t.at}>
                    <td>{stamp(t.at)}</td>
                    <td className="mono">{ms(t.ms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="empty-state">Aucune mesure de réponse réussie.</p>
        )}
      </section>
    </div>
  );
}

export function HistoryPage({ entries }: { entries: HistoryEntry[] }) {
  const [search, setSearch] = useState('');
  const [model, setModel] = useState('all');
  const [decision, setDecision] = useState('all');
  const [selected, setSelected] = useState<HistoryEntry | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [error, setError] = useState('');
  const filtered = entries.filter(
    (r) =>
      (model === 'all' || r.model === model) &&
      (decision === 'all' || r.decision === decision) &&
      `${r.category} ${categoryLabels[r.category]} ${r.model} ${r.request_id} ${r.recorded_at}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  function remove() {
    try {
      clearHistory();
      setSelected(null);
      setConfirmClear(false);
    } catch {
      setError('Le navigateur ne permet pas de supprimer le stockage local.');
    }
  }
  return (
    <div className="page-stack">
      <div className="history-toolbar toolbar">
        <label>
          Rechercher
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Catégorie, modèle, request_id…"
          />
        </label>
        <label>
          Modèle
          <select value={model} onChange={(e) => setModel(e.target.value)}>
            <option value="all">Tous les modèles</option>
            {MODEL_NAMES.map((m) => (
              <option key={m}>{m}</option>
            ))}
          </select>
        </label>
        <label>
          Décision
          <select value={decision} onChange={(e) => setDecision(e.target.value)}>
            <option value="all">Toutes les décisions</option>
            <option value="normal">Normal</option>
            <option value="anomaly">Anormal</option>
          </select>
        </label>
        <button
          className="secondary"
          disabled={!filtered.length}
          onClick={() => exportHistory(filtered, 'csv')}
        >
          <Download size={16} />
          CSV
        </button>
        <button
          className="secondary"
          disabled={!filtered.length}
          onClick={() => exportHistory(filtered, 'json')}
        >
          <Download size={16} />
          JSON
        </button>
        <button
          className="text-button danger"
          disabled={!entries.length}
          onClick={() => setConfirmClear(true)}
        >
          <Trash2 size={16} />
          Effacer
        </button>
      </div>
      <p className="scientific-note">
        {entries.length} / 200 entrées au maximum · stockage local de ce navigateur · aucune image
        brute ni PNG enregistré automatiquement. Ce journal n’est pas une base industrielle
        persistante. Les exports respectent les filtres actifs.
      </p>
      {confirmClear && (
        <div className="notice warning" role="alertdialog" aria-labelledby="clear-history-title">
          <div>
            <h2 id="clear-history-title">Effacer l’historique local ?</h2>
            <p>
              Les {entries.length} inspections stockées dans ce navigateur seront supprimées. Vous
              pouvez les exporter auparavant.
            </p>
          </div>
          <button className="secondary" onClick={() => setConfirmClear(false)}>
            Conserver
          </button>
          <button className="primary danger" onClick={remove}>
            Confirmer l’effacement
          </button>
        </div>
      )}
      {error && (
        <div className="notice error" role="alert">
          {error}
        </div>
      )}
      <section className="panel">
        <div className="panel-heading">
          <h2>Inspections enregistrées</h2>
          <span className="badge">
            {filtered.length} résultat{filtered.length > 1 ? 's' : ''}
          </span>
        </div>
        {filtered.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Date et heure</th>
                  <th>Catégorie</th>
                  <th>Modèle</th>
                  <th>Moteur</th>
                  <th>Décision</th>
                  <th>Score</th>
                  <th>Seuil</th>
                  <th>Inférence</th>
                  <th>Détails</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => (
                  <tr key={r.request_id}>
                    <td>{stamp(r.recorded_at)}</td>
                    <td>{categoryLabels[r.category]}</td>
                    <td>{r.model}</td>
                    <td>{r.engine || 'pytorch'}</td>
                    <td>
                      <span className={r.decision === 'anomaly' ? 'anomaly' : 'normal'}>
                        {r.decision === 'anomaly' ? 'Anormal' : 'Normal'}
                      </span>
                    </td>
                    <td className="mono">{number(r.anomaly_score)}</td>
                    <td className="mono">{number(r.threshold)}</td>
                    <td className="mono">{ms(r.inference_time_ms)}</td>
                    <td>
                      <button
                        className="text-button"
                        onClick={() => setSelected(r)}
                        aria-label={`Voir l’inspection ${r.model} ${r.request_id}`}
                      >
                        Consulter
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-state">
            <History size={30} />
            <h3>
              {entries.length
                ? 'Aucune inspection ne correspond.'
                : 'Votre journal est encore vide.'}
            </h3>
            <p>
              {entries.length
                ? 'Ajustez les filtres ou votre recherche.'
                : 'Les analyses terminées apparaîtront ici, avec leurs scores et leur traçabilité.'}
            </p>
          </div>
        )}
      </section>
      {selected && (
        <section className="history-detail">
          <div className="toolbar">
            <h2>Détail du {stamp(selected.recorded_at)}</h2>
            <button className="text-button" onClick={() => setSelected(null)}>
              Fermer le détail
            </button>
          </div>
          <Result result={selected} elapsed={selected.round_trip_ms} endpoint={selected.endpoint} />
          <div className="toolbar">
            <CopyButton value={selected.request_id} label="Copier le request_id" />
            <CopyButton value={selected.version} label="Copier la version SHA256" />
          </div>
          <p className="scientific-note">
            Les images et cartes explicatives ne sont pas conservées dans l’historique.
          </p>
        </section>
      )}
    </div>
  );
}
