import { useEffect, useRef, useState } from 'react';
import { Download, Files, LoaderCircle, RefreshCw, UploadCloud, X } from 'lucide-react';
import { Explanation } from '../components/Result';
import type { Metadata, VisualizedPrediction } from '../api/contracts';
import { portalRequest } from './session';
import { usePortalAuth } from './Auth';
import { StatusBadge } from '../components/StatusBadge';
import {
  batchStatus,
  checkBatchFiles,
  exportBatch,
  submitBatch,
  terminalBatch,
  type Batch,
  type BatchItem,
  type BatchLimits,
} from './batch';
import './batch.css';

export function BatchInspection() {
  const auth = usePortalAuth();
  const canInspect = !!auth?.user.permissions.includes('inspect');
  const [limits, setLimits] = useState<BatchLimits | null>(null);
  const [dragging, setDragging] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [feedback, setFeedback] = useState('');
  const dragDepth = useRef(0);
  const [metadata, setMetadata] = useState<Metadata | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [previews, setPreviews] = useState<string[]>([]);
  const [model, setModel] = useState('B0'),
    [category, setCategory] = useState('bottle'),
    [engine, setEngine] = useState('pytorch');
  const [batches, setBatches] = useState<Batch[]>([]),
    [total, setTotal] = useState(0),
    [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Batch | null>(null),
    [items, setItems] = useState<BatchItem[]>([]);
  const [itemTotal, setItemTotal] = useState(0),
    [itemOffset, setItemOffset] = useState(0),
    [filter, setFilter] = useState('all');
  const [error, setError] = useState(''),
    [busy, setBusy] = useState(false),
    [validating, setValidating] = useState(false),
    [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0),
    [visual, setVisual] = useState<VisualizedPrediction | null>(null),
    [explaining, setExplaining] = useState('');
  const key = useRef(crypto.randomUUID()),
    validation = useRef(0);
  const choice = metadata?.models.find((m) => m.model === model && m.category === category);
  const available = (choice?.available_engines ?? (choice ? ['pytorch'] : [])).includes(
    engine as 'pytorch' | 'onnxruntime',
  );
  useEffect(() => {
    let active = true;
    void Promise.all([
      portalRequest<BatchLimits>('/api/batches/limits'),
      portalRequest<Metadata>('/api/model/metadata'),
    ])
      .then(([l, m]) => {
        if (active) {
          setLimits(l);
          setMetadata(m);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
      validation.current++;
    };
  }, []);
  useEffect(() => {
    const urls = files.slice(0, 8).map((f) => URL.createObjectURL(f));
    setPreviews(urls);
    return () => urls.forEach((url) => URL.revokeObjectURL(url));
  }, [files]);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    async function load() {
      try {
        const data = await portalRequest<{ items: Batch[]; total: number }>(
          `/api/batches?limit=10&offset=${offset}`,
          { signal: controller.signal },
        );
        if (active) {
          setBatches(data.items);
          setTotal(data.total);
        }
      } catch (e) {
        if (active) setError((e as Error).message);
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    const timer = setInterval(() => void load(), 3000);
    return () => {
      active = false;
      controller.abort();
      clearInterval(timer);
    };
  }, [offset, revision]);
  const selectedId = selected?.id;
  useEffect(() => {
    if (!selectedId) return;
    let active = true,
      inFlight = false;
    const controller = new AbortController();
    async function load() {
      if (inFlight) return;
      inFlight = true;
      try {
        const [batch, rows] = await Promise.all([
          portalRequest<Batch>(`/api/batches/${selectedId}/progress`, {
            signal: controller.signal,
          }),
          portalRequest<{ items: BatchItem[]; total: number }>(
            `/api/batches/${selectedId}/items?limit=20&offset=${itemOffset}&filter=${filter}`,
            { signal: controller.signal },
          ),
        ]);
        if (active) {
          setSelected(batch);
          setItems(rows.items);
          setItemTotal(rows.total);
        }
      } catch (e) {
        if (active) setError((e as Error).message);
      } finally {
        inFlight = false;
      }
    }
    void load();
    const timer = setInterval(() => void load(), 2000);
    return () => {
      active = false;
      controller.abort();
      clearInterval(timer);
    };
  }, [selectedId, filter, itemOffset, revision]);
  async function selectFiles(list: FileList | File[]) {
    if (!limits) return;
    const attempt = ++validation.current;
    setValidating(true);
    setError('');
    try {
      const next = Array.from(list);
      await checkBatchFiles(next, limits);
      if (attempt === validation.current) {
        setFiles(next);
        key.current = crypto.randomUUID();
      }
    } catch (e) {
      if (attempt === validation.current) {
        setFiles([]);
        setError((e as Error).message);
      }
    } finally {
      if (attempt === validation.current) setValidating(false);
    }
  }
  async function launch() {
    setBusy(true);
    setError('');
    try {
      const batch = await submitBatch(files, model, category, engine, key.current);
      setSelected(batch);
      setItems([]);
      setItemOffset(0);
      setFilter('all');
      setVisual(null);
      setFiles([]);
      key.current = crypto.randomUUID();
      setRevision((n) => n + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function cancel() {
    if (
      !selected ||
      !window.confirm(
        'Annuler les images encore en attente ? Un calcul déjà lancé peut finir avant l’arrêt du lot.',
      )
    )
      return;
    setCancelling(true);
    setFeedback('');
    try {
      setSelected(
        await portalRequest<Batch>(`/api/batches/${selected.id}/cancel`, { method: 'POST' }),
      );
      setRevision((n) => n + 1);
      setFeedback('Annulation demandée. Les compteurs affichés restent ceux du serveur.');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCancelling(false);
    }
  }
  async function exportCsv() {
    if (!selected || exporting) return;
    setExporting(true);
    setFeedback('');
    try {
      await exportBatch(selected.id);
      setFeedback('CSV prêt : le téléchargement a été déclenché.');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setExporting(false);
    }
  }
  async function explain(item: BatchItem) {
    if (!selected) return;
    setExplaining(item.id);
    setError('');
    try {
      setVisual(
        await portalRequest<VisualizedPrediction>(
          `/api/batches/${selected.id}/items/${item.id}/explanation`,
          { method: 'POST' },
        ),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setExplaining('');
    }
  }
  const choose = (batch: Batch) => {
    setSelected(batch);
    setItems([]);
    setFilter('all');
    setItemOffset(0);
    setVisual(null);
  };
  return (
    <div className="page-stack batch-inspection">
      <div className="batch-intro">
        <span className="eyebrow accent">
          <Files size={16} /> INDUSTRIAL PRODUCTION CONTROL
        </span>
        <p>Des images privées. Un traitement asynchrone. Une trace pour chaque décision.</p>
      </div>
      {error && (
        <div className="notice error" role="alert">
          {error}
        </div>
      )}
      {canInspect && (
        <section className="panel batch-upload" aria-label="Préparer un lot">
          <div className="panel-heading">
            <div><span className="eyebrow">NOUVELLE SÉRIE D’INSPECTIONS</span><h2>Préparer un lot</h2></div>
            <span className="badge">
              {files.length} image{files.length > 1 ? 's' : ''}
            </span>
          </div>
          <label
            className={`batch-drop ${dragging ? 'is-dragging' : ''}`}
            onDragEnter={(e) => { e.preventDefault(); dragDepth.current++; if (!busy && !validating) setDragging(true); }}
            onDragLeave={() => { dragDepth.current = Math.max(0, dragDepth.current - 1); if (!dragDepth.current) setDragging(false); }}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              dragDepth.current = 0;
              setDragging(false);
              if (!busy && !validating) void selectFiles(e.dataTransfer.files);
            }}
          >
            <span className="batch-upload-icon"><UploadCloud size={28} /></span>
            <strong>Déposez vos images, ou parcourez vos fichiers.</strong>
            <span className="batch-file-prompt">Choisir des images</span>
            <span>
              PNG / JPEG · {limits?.max_images ?? '…'} images · 10 Mio par image · 100 Mio par lot
              maximum
            </span>
            <input
              type="file"
              className="batch-file-input"
              multiple
              accept=".png,.jpg,.jpeg,image/png,image/jpeg"
              aria-label="Images du lot"
              disabled={!limits || busy || validating}
              onChange={(e) => {
                if (e.target.files) void selectFiles(e.target.files);
                e.target.value = '';
              }}
            />
          </label>
          {validating && (
            <p role="status">
              <LoaderCircle className="spin" size={16} /> Vérification des fichiers…
            </p>
          )}
          {!!files.length && (
            <>
              <div className="batch-previews">
                {previews.map((url, i) => (
                  <figure key={url}>
                    <img src={url} alt={`Aperçu ${files[i]?.name}`} />
                    <figcaption>{files[i]?.name}</figcaption>
                  </figure>
                ))}
              </div>
              <p className="small muted">
                {files.length} images validées localement ·{' '}
                {(files.reduce((n, f) => n + f.size, 0) / 1048576).toFixed(2)} Mio ·{' '}
                {files.length > 8 ? '8 aperçus affichés.' : ''} Le serveur vérifie à nouveau les
                contenus.
              </p>
              <details className="batch-file-list"><summary>Consulter les {files.length} fichiers sélectionnés</summary>
                <ul>{files.map((file, index) => <li key={`${index}-${file.name}`}><span>{file.name}</span><small>{(file.size / 1048576).toFixed(2)} Mio</small></li>)}</ul>
              </details>
            </>
          )}
          <div className="toolbar batch-selectors">
            <label>
              Catégorie
              <select
                aria-label="Catégorie du lot"
                value={category}
                disabled={busy}
                onChange={(e) => {
                  setCategory(e.target.value);
                  key.current = crypto.randomUUID();
                }}
              >
                <option value="bottle">Bouteille</option>
                <option value="hazelnut">Noisette</option>
                <option value="leather">Cuir</option>
              </select>
            </label>
            <label>
              Modèle
              <select
                aria-label="Modèle du lot"
                value={model}
                disabled={busy}
                onChange={(e) => {
                  setModel(e.target.value);
                  key.current = crypto.randomUUID();
                }}
              >
                {['B0', 'A1', 'T0', 'T1', 'T2'].map((m) => (
                  <option key={m}>{m}</option>
                ))}
              </select>
            </label>
            <label>
              Moteur
              <select
                aria-label="Moteur du lot"
                value={engine}
                disabled={busy}
                onChange={(e) => {
                  setEngine(e.target.value);
                  key.current = crypto.randomUUID();
                }}
              >
                <option value="pytorch">PyTorch</option>
                <option
                  value="onnxruntime"
                  disabled={!choice?.available_engines?.includes('onnxruntime')}
                >
                  ONNX Runtime
                </option>
              </select>
            </label>
            <button
              className="primary"
              onClick={() => void launch()}
              disabled={
                !files.length || !available || busy || validating || limits?.storage !== 'ready'
              }
            >
              {busy ? 'Transmission du lot…' : 'Démarrer le lot'}
            </button>
            {!!files.length && (
              <button className="text-button" disabled={busy} onClick={() => setFiles([])}>
                <X size={15} /> Retirer les fichiers
              </button>
            )}
          </div>
          {!available && metadata && (
            <p className="notice warning">
              Ce couple modèle / catégorie / moteur est indisponible. Aucun repli automatique.
            </p>
          )}
          <p className="scientific-note">
            Images privées : {limits?.image_retention_hours ?? '…'} h · résultats :{' '}
            {limits?.result_retention_days ?? '…'} jours. Valeurs techniques provisoires. Le
            traitement conserve les seuils et le prétraitement scientifiques.
          </p>
        </section>
      )}
      <section className="panel batch-history">
        <div className="panel-heading">
          <h2>Historique des lots</h2>
          <button className="secondary" onClick={() => setRevision((n) => n + 1)}>
            <RefreshCw size={15} /> Actualiser
          </button>
        </div>
        {loading ? (
          <p role="status">Chargement des lots…</p>
        ) : !batches.length ? (
          <div className="empty-state">
            <Files size={30} />
            <h3>Aucun lot accessible.</h3>
            <p>
              {canInspect
                ? 'Importez des images pour commencer.'
                : 'Votre périmètre ne contient aucun lot.'}
            </p>
          </div>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Date UTC</th>
                  <th>Lot</th>
                  <th>Modèle / moteur</th>
                  <th>État</th>
                  <th>Terminées</th>
                  <th>Consulter</th>
                </tr>
              </thead>
              <tbody>
                {batches.map((b) => (
                  <tr key={b.id}>
                    <td>{new Date(b.created_at).toLocaleString('fr-FR', { timeZone: 'UTC' })}</td>
                    <td>
                      <code>{b.id.slice(0, 8)}</code>
                    </td>
                    <td>
                      {b.model} · {b.category} · {b.engine}
                    </td>
                    <td><StatusBadge value={b.status} label={batchStatus[b.status] || b.status} /></td>
                    <td>
                      {b.processed} / {b.total}
                    </td>
                    <td>
                      <button
                        className="text-button"
                        aria-label={`Ouvrir le lot ${b.id}`}
                        onClick={() => choose(b)}
                      >
                        Ouvrir
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="toolbar">
          <button
            className="secondary"
            disabled={!offset}
            onClick={() => setOffset((n) => Math.max(0, n - 10))}
          >
            Lots précédents
          </button>
          <span>
            {total ? offset + 1 : 0}–{Math.min(offset + 10, total)} / {total}
          </span>
          <button
            className="secondary"
            disabled={offset + 10 >= total}
            onClick={() => setOffset((n) => n + 10)}
          >
            Lots suivants
          </button>
        </div>
      </section>
      {selected && (
        <section className="panel batch-detail" aria-label="Suivi du lot">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">LOT {selected.id.slice(0, 8)}</span>
              <h2 key={selected.status} className="batch-state-title">{batchStatus[selected.status] || selected.status}</h2>
            </div>
            <div className="toolbar">
              <button
                className="secondary"
                onClick={() => void exportCsv()}
                disabled={exporting}
                aria-busy={exporting}
              >
                {exporting ? <LoaderCircle className="spin" size={15} /> : <Download size={15} />}
                {exporting ? 'Préparation du CSV…' : 'Exporter CSV'}
              </button>
              {canInspect && !terminalBatch(selected.status) && (
                <button className="secondary danger" disabled={cancelling} aria-busy={cancelling} onClick={() => void cancel()}>
                  {cancelling && <LoaderCircle className="spin" size={15} />}
                  {cancelling ? 'Annulation en cours…' : 'Annuler le lot'}
                </button>
              )}
            </div>
          </div>
          {feedback && <p className="batch-feedback" role="status">{feedback}</p>}
          <div className="batch-progress-track">
          <progress className="sr-only"
            aria-label="Progression réelle du lot"
            max={selected.total}
            value={selected.processed}
          />
          <span aria-hidden="true" style={{ transform: `scaleX(${selected.processed / Math.max(1, selected.total)})` }} />
          </div>
          <p className="small">
            {selected.processed} / {selected.total} images terminées · les annulations et erreurs
            sont comptées séparément des analyses.
          </p>
          <div className="batch-counts">
            <span className="normal"><strong>{selected.normal_count}</strong> normales</span>
            <span className="anomaly"><strong>{selected.anomaly_count}</strong> anormales</span>
            <span><strong>{selected.error_count}</strong> erreurs</span>
            <span><strong>{selected.cancelled_count}</strong> annulées</span>
          </div>
          <label>
            Résultats
            <select
              aria-label="Filtre des résultats du lot"
              value={filter}
              onChange={(e) => {
                setFilter(e.target.value);
                setItemOffset(0);
              }}
            >
              <option value="all">Tous</option>
              <option value="normal">Normal</option>
              <option value="anomaly">Anormal</option>
              <option value="error">Erreur</option>
            </select>
          </label>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Image</th>
                  <th>État</th>
                  <th>Score / seuil</th>
                  <th>Décision</th>
                  <th>Latence moteur</th>
                  <th>Traçabilité</th>
                  <th>Explication</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      {item.position}. {item.filename}
                    </td>
                    <td>
                      <StatusBadge value={item.status} label={batchStatus[item.status] || item.status} />
                      {item.error && <p className="small warning">{item.error.code}</p>}
                    </td>
                    <td className="mono">
                      {item.anomaly_score === null ? '—' : item.anomaly_score.toPrecision(8)} /{' '}
                      {item.threshold === null ? '—' : item.threshold.toPrecision(8)}
                    </td>
                    <td>
                      <StatusBadge value={item.decision ?? undefined} label={item.decision === 'normal'
                        ? 'Normal'
                        : item.decision === 'anomaly'
                          ? 'Anormal'
                          : '—'} />
                    </td>
                    <td>
                      {item.inference_time_ms === null
                        ? '—'
                        : `${item.inference_time_ms.toFixed(1)} ms`}
                    </td>
                    <td>
                      <details>
                        <summary>Provenance</summary>
                        <p className="small mono">
                          Fichier SHA256 : {item.file_sha256}
                          <br />
                          Modèle SHA256 : {item.version || 'Non disponible'}
                          <br />
                          Moteur : {item.engine || 'Non disponible'}
                          <br />
                          Tentatives : {item.attempts}
                        </p>
                      </details>
                    </td>
                    <td>
                      {canInspect && item.status === 'completed' && item.image_available ? (
                        <button
                          className="text-button"
                          disabled={!!explaining}
                          onClick={() => void explain(item)}
                        >
                          {explaining === item.id ? 'Calcul…' : 'Expliquer'}
                        </button>
                      ) : (
                        <span className="muted small">
                          {item.image_available ? 'Non disponible' : 'Image expirée'}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!items.length && <p className="empty-state">Aucune image pour ce filtre.</p>}
          </div>
          <div className="toolbar">
            <button
              className="secondary"
              disabled={!itemOffset}
              onClick={() => setItemOffset((n) => Math.max(0, n - 20))}
            >
              Images précédentes
            </button>
            <span>
              {itemTotal ? itemOffset + 1 : 0}–{Math.min(itemOffset + 20, itemTotal)} / {itemTotal}
            </span>
            <button
              className="secondary"
              disabled={itemOffset + 20 >= itemTotal}
              onClick={() => setItemOffset((n) => n + 20)}
            >
              Images suivantes
            </button>
          </div>
        </section>
      )}
      {visual && (
        <section className="panel">
          <div className="toolbar">
            <h2>Explication réelle de l’image</h2>
            <button className="text-button" onClick={() => setVisual(null)}>
              Fermer l’explication
            </button>
          </div>
          <Explanation result={visual} />
        </section>
      )}
    </div>
  );
}
