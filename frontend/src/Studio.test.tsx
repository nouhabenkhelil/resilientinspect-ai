import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import { health, metadata, prediction } from './test/fixtures';
import { readHistory, recordInspection } from './studio/history';

let fetcher: ReturnType<typeof vi.fn>;
// Test navigation, not Vitest's cold transformation of the deferred chart bundle.
// Real cold loading remains covered by the browser QA against the built app.
beforeAll(async () => { await import('./components/Analytics'); }, 30000);
beforeEach(() => {
  localStorage.clear();
  window.history.replaceState(null, '', '/');
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  fetcher = vi.fn(async (url: string) => new Response(JSON.stringify(url.endsWith('/health') ? health : metadata)));
  vi.stubGlobal('fetch', fetcher);
});
afterEach(() => { vi.restoreAllMocks(); });

test('studio defaults to Control Center and navigates through every functional workspace', async () => {
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText('API opérationnelle');
  expect(screen.getByRole('heading', { name: 'Le contrôle, en perspective.' })).toBeInTheDocument();
  expect(screen.getByText('Aucune inspection enregistrée dans ce navigateur.')).toBeInTheDocument();
  const nav = within(screen.getByRole('navigation', { name: 'Navigation principale' }));
  expect(nav.getByRole('link', { name: 'Control Center' })).toHaveAttribute('aria-current', 'page');
  await user.click(nav.getByRole('link', { name: 'Smart Inspection' }));
  expect(screen.getByRole('heading', { name: 'Un regard plus précis.' })).toBeInTheDocument();
  expect(screen.getByLabelText('Fichier image à inspecter')).toBeInTheDocument();
  await user.click(nav.getByRole('link', { name: /^Comparison Lab/ }));
  expect(screen.getByRole('heading', { name: 'Protocole de comparaison' })).toBeInTheDocument();
  expect(screen.getByLabelText('Image de comparaison')).toBeInTheDocument();
  await user.click(nav.getByRole('link', { name: 'Model Analytics' }));
  // Cold lazy-module transformation on Windows can overlap VM CPU validation.
  // Keep the same rendered-table assertion; allow scheduling delay only.
  await screen.findByRole('table', { name: /Valeurs archivées/ }, { timeout: 15000 });
  expect(screen.getByLabelText('Métrique scientifique')).toBeInTheDocument();
  await user.click(nav.getByRole('link', { name: 'System Monitor' }));
  expect(screen.getByText('15 / 15')).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Versions et provenance' })).toBeInTheDocument();
  await user.click(nav.getByRole('link', { name: 'Historique' }));
  expect(screen.getByText('Votre journal est encore vide.')).toBeInTheDocument();
  expect(nav.getByRole('link', { name: 'Historique' })).toHaveAttribute('aria-current', 'page');
  expect(window.location.hash).toBe('#history');
}, 25000);

test('light mode persists across remount and sidebar/demo controls remain operable', async () => {
  const user = userEvent.setup();
  const first = render(<App />);
  await screen.findByText('API opérationnelle');
  expect(document.documentElement.dataset.theme).toBe('dark');
  await user.click(screen.getByRole('button', { name: 'Activer le mode clair' }));
  expect(document.documentElement.dataset.theme).toBe('light');
  expect(localStorage.getItem('ri.theme')).toBe('light');
  first.unmount();
  render(<App />);
  await screen.findByText('API opérationnelle');
  expect(screen.getByRole('button', { name: 'Activer le mode sombre' })).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Réduire la navigation' }));
  expect(screen.getByRole('button', { name: 'Déployer la navigation' })).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Mode démonstration' }));
  expect(screen.getByRole('button', { name: 'Mode démonstration' })).toHaveAttribute('aria-pressed', 'true');
  expect(screen.getByText('Aucune inspection enregistrée dans ce navigateur.')).toBeInTheDocument();
});

test('offline API is explicit and can recover through a real refresh', async () => {
  const user = userEvent.setup();
  fetcher.mockRejectedValue(new TypeError('offline'));
  render(<App />);
  await screen.findByText('API hors ligne');
  expect(screen.getByRole('alert')).toHaveTextContent('Serveur injoignable');
  fetcher.mockImplementation(async (url: string) => new Response(JSON.stringify(url.endsWith('/health') ? health : metadata)));
  await user.click(screen.getByRole('button', { name: 'Actualiser le statut API' }));
  await screen.findByText('API opérationnelle');
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(fetcher.mock.calls.filter(c => c[0] === '/api/health')).toHaveLength(2);
});

test('monitor reports degraded state and the backend reason for an unavailable model', async () => {
  fetcher.mockImplementation(async (url: string) => new Response(JSON.stringify(url.endsWith('/health')
    ? { ...health, status: 'degraded', ready_models: 14 }
    : { ...metadata, models: metadata.models.slice(0, 14), unavailable: [{ model: 'T2', category: 'leather', reason: 'Calibration absente.' }] }),
  { status: url.endsWith('/health') ? 503 : 200 }));
  window.history.replaceState(null, '', '/#monitor');
  render(<App />);
  await screen.findByText('API dégradée');
  expect(screen.getByText('14 / 15')).toBeInTheDocument();
  expect(screen.getByText('Calibration absente.')).toBeInTheDocument();
  expect(screen.getByText('Indisponible')).toBeInTheDocument();
});

async function text(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = reject;
    reader.readAsText(blob);
  });
}

test('history filters genuine local records, exports only the selection and confirms deletion', async () => {
  const user = userEvent.setup();
  recordInspection({ ...prediction, model: 'B0', decision: 'normal', anomaly_score: 0.01 }, 50);
  recordInspection({ ...prediction, request_id: '7e216762-5472-4635-bce5-23d86c6a6a4f', model: 'T2', category: 'hazelnut' }, 75);
  window.history.replaceState(null, '', '/#history');
  const blobs: Blob[] = [];
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn((blob: Blob) => { blobs.push(blob); return 'blob:export'; }) });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  render(<App />);
  await screen.findByText('API opérationnelle');
  expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(3);
  await user.selectOptions(screen.getByLabelText('Modèle'), 'T2');
  await user.selectOptions(screen.getByLabelText('Décision'), 'anomaly');
  await user.type(screen.getByLabelText('Rechercher'), 'hazelnut');
  expect(within(screen.getByRole('table')).getAllByRole('row')).toHaveLength(2);
  await user.click(screen.getByRole('button', { name: /Voir l’inspection T2/ }));
  expect(screen.getByText('Les images et cartes explicatives ne sont pas conservées dans l’historique.')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'CSV' }));
  const csv = await text(blobs[0]);
  expect(csv).toContain('recorded_at,category,model,decision');
  expect(csv).toContain('"hazelnut","T2","anomaly"');
  expect(csv).not.toContain('"B0"');
  await user.click(screen.getByRole('button', { name: 'JSON' }));
  const exported = JSON.parse(await text(blobs[1]));
  expect(exported).toHaveLength(1);
  expect(exported[0].model).toBe('T2');
  expect(JSON.stringify(exported)).not.toMatch(/base64|visualization|image_png/);
  await user.click(screen.getByRole('button', { name: 'Effacer' }));
  expect(screen.getByRole('alertdialog')).toBeInTheDocument();
  expect(readHistory()).toHaveLength(2);
  await user.click(screen.getByRole('button', { name: 'Conserver' }));
  expect(readHistory()).toHaveLength(2);
  await user.click(screen.getByRole('button', { name: 'Effacer' }));
  await user.click(screen.getByRole('button', { name: 'Confirmer l’effacement' }));
  await screen.findByText('Votre journal est encore vide.');
  expect(readHistory()).toHaveLength(0);
  expect(screen.getByRole('button', { name: 'CSV' })).toBeDisabled();
});
