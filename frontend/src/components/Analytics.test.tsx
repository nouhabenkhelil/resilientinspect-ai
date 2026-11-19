import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Analytics } from './Analytics';
import experiments from '../data/experiments.json';

// jsdom has no layout engine; scientific values are also exposed as HTML tables.
beforeEach(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

describe('official model analytics', () => {
  it('renders authentic records, accessible chart descriptions, and honest limits', () => {
    render(<Analytics />);
    expect(screen.getByRole('img', { name: /Comparaison AUROC image/ })).toBeInTheDocument();
    const table = screen.getByRole('table', { name: /Valeurs archivées/ });
    expect(within(table).getAllByRole('row')).toHaveLength(16);
    expect(screen.getByText(/absence de validation indépendante/)).toBeInTheDocument();
    expect(screen.getByText(/aucun score AE\/sigmoid fusionné/)).toBeInTheDocument();
  });

  it('filters architectures and categories without inventing pixel measures', async () => {
    const user = userEvent.setup();
    render(<Analytics />);
    await user.selectOptions(screen.getByLabelText('Architecture analytique'), 'transfer');
    await user.selectOptions(screen.getByLabelText('Catégorie analytique'), 'bottle');
    const table = screen.getByRole('table', { name: /Valeurs archivées/ });
    expect(within(table).getAllByRole('row')).toHaveLength(4);
    expect(within(table).queryByText('B0')).not.toBeInTheDocument();
    expect(screen.getByText(/Aucune métrique pixel pour cette sélection/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('Métrique scientifique'), 'fpr');
    expect(
      screen.getByRole('heading', { name: 'Faux positifs par catégorie' }),
    ).toBeInTheDocument();
  });

  it('selects the official confusion matrix and preserves its calibrated threshold', async () => {
    const user = userEvent.setup();
    render(<Analytics />);
    await user.selectOptions(screen.getByLabelText('Rapport de matrice de confusion'), 'B0/bottle');
    const matrix = screen.getByRole('table', { name: /Vérité terrain en lignes/ });
    expect(within(matrix).getByText('32')).toBeInTheDocument();
    expect(within(matrix).getByText('31')).toBeInTheDocument();
    const source = experiments.records.find((r) => r.model === 'B0' && r.category === 'bottle')!;
    expect(source.confusion).toEqual({ tp: 32, tn: 19, fp: 1, fn: 31 });
    expect(source.threshold).toBe(0.20367741357625985);
  });
});
