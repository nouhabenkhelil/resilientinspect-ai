import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Explanation, Result, ScoreGauge, formatScore } from './Result';
import { prediction, visualization } from '../test/fixtures';

test('tiny thresholds remain visible and the gauge uses this model’s own scale', () => {
  const result = { ...prediction, anomaly_score: 0.0000004, threshold: 0.0000003 };
  expect(formatScore(result.threshold)).toBe('3.000000e-7');
  const { container } = render(
    <>
      <Result result={result} elapsed={25} />
      <ScoreGauge result={result} />
    </>,
  );
  expect(screen.getByText('3.000000e-7')).toBeInTheDocument();
  expect(screen.getByText(/Ce score n’est pas une probabilité/)).toBeInTheDocument();
  expect(screen.getByText(/Seuil : 3e-7/)).toBeInTheDocument();
  expect(container.querySelector('.threshold-marker')).toHaveStyle({
    left: `${(100 * result.threshold) / (result.anomaly_score * 1.4)}%`,
  });
});

test('viewer compares original letterbox assets, zooms and downloads the unchanged PNG', async () => {
  const user = userEvent.setup();
  const result = visualization();
  const { container } = render(<Explanation result={result} />);
  const download = screen.getByRole('link', { name: 'Télécharger le PNG original' });
  expect(download).toHaveAttribute(
    'href',
    `data:image/png;base64,${result.visualization.overlay_png_base64}`,
  );
  fireEvent.change(screen.getByLabelText('Intensité de la superposition'), {
    target: { value: '0.2' },
  });
  expect(container.querySelector('.api-overlay')).toHaveStyle({ opacity: '0.4' });
  expect(download).toHaveAttribute(
    'href',
    `data:image/png;base64,${result.visualization.overlay_png_base64}`,
  );
  await user.selectOptions(screen.getByLabelText('Zoom'), '2');
  expect(container.querySelector('.zoom-canvas')).toHaveStyle({ transform: 'scale(2)' });
  await user.click(screen.getByRole('button', { name: 'Côte à côte' }));
  expect(
    screen.getByRole('img', { name: 'Image préparée en coordonnées letterbox' }),
  ).toHaveAttribute('src', `data:image/png;base64,${result.visualization.image_png_base64}`);
  expect(screen.getByRole('img', { name: 'Carte explicative originale' })).toHaveAttribute(
    'src',
    `data:image/png;base64,${result.visualization.heatmap_png_base64}`,
  );
  expect(download).toHaveAttribute(
    'href',
    `data:image/png;base64,${result.visualization.heatmap_png_base64}`,
  );
  expect(
    screen.getByText(/Le score est la moyenne du top 1 % des pixels valides/),
  ).toBeInTheDocument();
});

test('viewer fullscreen controls and Grad-CAM explanation preserve scientific limits', async () => {
  const user = userEvent.setup();
  const show = vi.fn();
  const close = vi.fn();
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', {
    configurable: true,
    value: show,
  });
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value: close });
  render(<Explanation result={visualization({ ...prediction, model: 'T2' })} />);
  expect(screen.getByText(/Grad-CAM n’est pas une segmentation pixel/)).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Ouvrir le visualiseur plein écran' }));
  expect(show).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Fermer le visualiseur', hidden: true }));
  expect(close).toHaveBeenCalledTimes(1);
});
