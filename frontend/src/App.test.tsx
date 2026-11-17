import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import { health, metadata, prediction, requestId, visualization } from './test/fixtures';
import type { Prediction } from './api/contracts';

const image = () => new File(['image'], 'inspection.png', { type: 'image/png' });
let fetcher: ReturnType<typeof vi.fn<(url: string, options?: RequestInit) => Promise<Response>>>;
let posted: string[];
beforeEach(() => {
  posted = [];
  vi.stubGlobal(
    'Image',
    class {
      naturalWidth = 173;
      naturalHeight = 89;
      onload?: () => void;
      set src(_value: string) {
        queueMicrotask(() => this.onload?.());
      }
    },
  );
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    value: vi.fn(() => 'blob:local-preview'),
  });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() });
  fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    let result: unknown = url.endsWith('/health') ? health : metadata;
    if (options?.method === 'POST') {
      posted.push(url);
      const form = options.body as FormData;
      const value = {
        ...prediction,
        model: form.get('model'),
        category: form.get('category'),
      } as Prediction;
      result = url.endsWith('/visualize') ? visualization(value) : value;
    }
    return new Response(JSON.stringify(result));
  });
  vi.stubGlobal('fetch', fetcher);
});
async function ready() {
  render(<App />);
  await screen.findByText('API opérationnelle');
  await waitFor(() => expect(screen.getByLabelText('Modèle d’inspection')).toHaveValue('B0'));
}
async function upload() {
  await userEvent.upload(screen.getByLabelText('Fichier image à inspecter'), image());
  await screen.findByAltText('Aperçu local : inspection.png');
}

describe('parcours Inspection', () => {
  it('charge les cinq modèles depuis les métadonnées et interdit une analyse sans image', async () => {
    await ready();
    expect(screen.getByLabelText('Modèle d’inspection').querySelectorAll('option')).toHaveLength(5);
    expect(screen.getByRole('button', { name: 'Analyser l’image' })).toBeDisabled();
    expect(posted).toEqual([]);
  });
  it('prévisualise localement puis appelle les deux vrais chemins multipart', async () => {
    await ready();
    await upload();
    expect(posted).toEqual([]);
    await userEvent.click(screen.getByRole('button', { name: 'Analyser l’image' }));
    await screen.findByText('Heatmap de reconstruction');
    expect(posted).toEqual(['/api/predict', '/api/predict/visualize']);
    expect(screen.getByText('Anormal')).toBeInTheDocument();
    expect(screen.getByText('0,034568')).toBeInTheDocument();
    expect(screen.getByText('42,7 ms')).toBeInTheDocument();
    expect(screen.getByText(requestId)).toBeInTheDocument();
    expect(screen.getByText(/Ce score n’est pas une probabilité\./)).toBeInTheDocument();
    const card = screen.getByRole('img', { name: /Superposition : erreur/ });
    expect(card.getAttribute('src')).toMatch(/^data:image\/png;base64,/);
    await userEvent.click(screen.getByRole('button', { name: 'Carte seule' }));
    expect(screen.getByRole('button', { name: 'Carte seule' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });
  it('utilise les choix sélectionnés et explique les limites de Grad-CAM', async () => {
    await ready();
    await upload();
    await userEvent.selectOptions(screen.getByLabelText('Catégorie du produit'), 'leather');
    await userEvent.selectOptions(screen.getByLabelText('Modèle d’inspection'), 'T2');
    await userEvent.click(screen.getByRole('button', { name: 'Analyser l’image' }));
    await screen.findByRole('heading', { name: 'Grad-CAM' });
    expect(screen.getByText(/Grad-CAM n’est pas une segmentation pixel/)).toBeInTheDocument();
    const post = fetcher.mock.calls.find((call) => call[0] === '/api/predict')!;
    expect((post[1]!.body as FormData).get('model')).toBe('T2');
    expect((post[1]!.body as FormData).get('category')).toBe('leather');
    await userEvent.selectOptions(screen.getByLabelText('Catégorie du produit'), 'bottle');
    expect(screen.queryByText('Anormal')).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Grad-CAM' })).not.toBeInTheDocument();
  });
  it('permet le drag-and-drop et refuse plusieurs fichiers', async () => {
    await ready();
    const drop = screen.getByText('Glissez votre image ici').closest('.drop-zone')!;
    fireEvent.drop(drop, { dataTransfer: { files: [image()] } });
    await screen.findByAltText('Aperçu local : inspection.png');
    fireEvent.drop(drop, { dataTransfer: { files: [image(), image()] } });
    await screen.findByText('Importez une seule image à la fois.');
    expect(screen.queryByAltText('Aperçu local : inspection.png')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Analyser l’image' })).toBeDisabled();
  });
  it('signale un fichier invalide avant tout POST', async () => {
    await ready();
    fireEvent.change(screen.getByLabelText('Fichier image à inspecter'), {
      target: { files: [new File(['bad'], 'piece.svg')] },
    });
    await screen.findByText(/Format invalide/);
    expect(posted).toEqual([]);
  });
  it('révoque les URL locales au retrait et efface les résultats', async () => {
    await ready();
    await upload();
    await userEvent.click(screen.getByRole('button', { name: 'Retirer l’image' }));
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:local-preview');
    expect(screen.queryByAltText('Aperçu local : inspection.png')).not.toBeInTheDocument();
  });
  it('autorise un modèle disponible lorsque /health renvoie 503 degraded', async () => {
    fetcher.mockImplementation(
      async (url: string) =>
        new Response(
          JSON.stringify(
            url.endsWith('/health')
              ? { ...health, status: 'degraded', ready_models: 1 }
              : {
                  ...metadata,
                  models: metadata.models.slice(0, 1),
                  unavailable: [
                    { model: 'A1', category: 'bottle', reason: 'Calibration absente.' },
                  ],
                },
          ),
          { status: url.endsWith('/health') ? 503 : 200 },
        ),
    );
    render(<App />);
    await screen.findByText('API dégradée');
    await upload();
    expect(screen.getByRole('button', { name: 'Analyser l’image' })).toBeEnabled();
    expect(screen.getByRole('option', { name: 'A1 · Indisponible' })).toBeDisabled();
  });
  it('affiche hors ligne puis récupère après actualisation', async () => {
    const original = fetcher.getMockImplementation()!;
    fetcher.mockRejectedValue(new TypeError('offline'));
    render(<App />);
    await screen.findByText('API hors ligne');
    expect(screen.getByRole('button', { name: 'Analyser l’image' })).toBeDisabled();
    fetcher.mockImplementation(original);
    await userEvent.click(screen.getByRole('button', { name: 'Actualiser le statut API' }));
    await screen.findByText('API opérationnelle');
  });
  it('affiche les erreurs backend et leur identifiant sans résultat inventé', async () => {
    await ready();
    await upload();
    fetcher.mockResolvedValue(
      new Response(
        JSON.stringify({
          code: 'model_unavailable',
          message: 'Modèle absent.',
          request_id: requestId,
        }),
        { status: 503 },
      ),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Analyser l’image' }));
    await screen.findByText('Modèle absent.');
    expect(screen.getByText(`Requête : ${requestId}`)).toBeInTheDocument();
    expect(screen.queryByText('Anormal')).not.toBeInTheDocument();
  });
  it('conserve la prédiction si la visualisation échoue et relance uniquement celle-ci', async () => {
    await ready();
    await upload();
    const original = fetcher.getMockImplementation()!;
    fetcher.mockImplementation(async (url, options) =>
      url.endsWith('/visualize')
        ? new Response(
            JSON.stringify({
              code: 'inference_failed',
              message: 'Visualisation impossible.',
              request_id: requestId,
            }),
            { status: 500 },
          )
        : original(url, options),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Analyser l’image' }));
    await screen.findByText('Visualisation impossible.');
    expect(screen.getByText('Anormal')).toBeInTheDocument();
    const before = fetcher.mock.calls.filter((call) => call[0] === '/api/predict').length;
    fetcher.mockImplementation(original);
    await userEvent.click(screen.getByRole('button', { name: 'Réessayer la visualisation' }));
    await screen.findByText('Heatmap de reconstruction');
    expect(fetcher.mock.calls.filter((call) => call[0] === '/api/predict')).toHaveLength(before);
  });
  it('verrouille les commandes pendant le calcul et permet l’annulation de l’attente', async () => {
    await ready();
    await upload();
    fetcher.mockImplementation(
      (_url, options) =>
        new Promise((_resolve, reject) => {
          options?.signal?.addEventListener('abort', () =>
            reject(new DOMException('aborted', 'AbortError')),
          );
        }),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Analyser l’image' }));
    expect(screen.getByLabelText('Catégorie du produit')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Analyse en cours…' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Annuler l’attente' }));
    await waitFor(() => expect(screen.getByLabelText('Catégorie du produit')).toBeEnabled());
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
