import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Webcam } from './Webcam';

const originalDevices = Object.getOwnPropertyDescriptor(navigator, 'mediaDevices');
let getUserMedia: ReturnType<typeof vi.fn>;
let stop: ReturnType<typeof vi.fn>;
let media: MediaStream;

beforeEach(() => {
  stop = vi.fn();
  media = { getTracks: () => [{ stop }] } as unknown as MediaStream;
  getUserMedia = vi.fn().mockResolvedValue(media);
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } });
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
});
afterEach(() => {
  vi.restoreAllMocks();
  if (originalDevices) Object.defineProperty(navigator, 'mediaDevices', originalDevices);
  else Reflect.deleteProperty(navigator, 'mediaDevices');
});

test('webcam requests permission only after explicit activation and exposes a denial', async () => {
  getUserMedia.mockRejectedValue(new DOMException('Permission caméra refusée.', 'NotAllowedError'));
  render(<Webcam onCapture={vi.fn()} disabled={false} />);
  expect(getUserMedia).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('button', { name: 'Activer la webcam' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Permission caméra refusée.');
  expect(getUserMedia).toHaveBeenCalledWith({ video: { facingMode: 'environment' }, audio: false });
  expect(screen.queryByText('Capture locale')).not.toBeInTheDocument();
});

test('closing and unmounting stop every opened track', async () => {
  const { unmount } = render(<Webcam onCapture={vi.fn()} disabled={false} />);
  await userEvent.click(screen.getByRole('button', { name: 'Activer la webcam' }));
  await screen.findByText('Capture locale');
  await userEvent.click(screen.getByRole('button', { name: 'Fermer la webcam' }));
  expect(stop).toHaveBeenCalledTimes(1);
  expect(screen.queryByText('Capture locale')).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Activer la webcam' }));
  await screen.findByText('Capture locale');
  unmount();
  expect(stop).toHaveBeenCalledTimes(2);
});

test('a permission granted after unmount is immediately released', async () => {
  let grant: (stream: MediaStream) => void = () => {};
  getUserMedia.mockImplementation(
    () =>
      new Promise<MediaStream>((resolve) => {
        grant = resolve;
      }),
  );
  const { unmount } = render(<Webcam onCapture={vi.fn()} disabled={false} />);
  await userEvent.click(screen.getByRole('button', { name: 'Activer la webcam' }));
  unmount();
  grant(media);
  await waitFor(() => expect(stop).toHaveBeenCalledTimes(1));
});

test('capture produces a local PNG File and shuts the stream down', async () => {
  const onCapture = vi.fn();
  const drawImage = vi.fn();
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    drawImage,
  } as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation((callback) =>
    callback(new Blob(['test-only'], { type: 'image/png' })),
  );
  const { container } = render(<Webcam onCapture={onCapture} disabled={false} />);
  await userEvent.click(screen.getByRole('button', { name: 'Activer la webcam' }));
  await screen.findByText('Capture locale');
  const video = container.querySelector('video')!;
  Object.defineProperties(video, { videoWidth: { value: 640 }, videoHeight: { value: 480 } });
  fireEvent.loadedMetadata(video);
  await userEvent.click(screen.getByRole('button', { name: 'Capturer et arrêter la caméra' }));
  expect(onCapture).toHaveBeenCalledTimes(1);
  const captured = onCapture.mock.calls[0][0] as File;
  expect(captured.name).toBe('camera.png');
  expect(captured.type).toBe('image/png');
  expect(drawImage).toHaveBeenCalledWith(video, 0, 0);
  expect(stop).toHaveBeenCalledTimes(1);
  expect(screen.queryByText('Capture locale')).not.toBeInTheDocument();
});
