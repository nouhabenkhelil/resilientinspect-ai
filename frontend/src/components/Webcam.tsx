import { useEffect, useRef, useState } from 'react';
import { Camera, X } from 'lucide-react';

export function Webcam({
  onCapture,
  disabled,
}: {
  onCapture: (file: File) => void;
  disabled: boolean;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const revision = useRef(0);
  const [open, setOpen] = useState(false);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const [requesting, setRequesting] = useState(false);
  function stop() {
    revision.current++;
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    setOpen(false);
    setReady(false);
  }
  useEffect(
    () => () => {
      revision.current++;
      stream.current?.getTracks().forEach((t) => t.stop());
    },
    [],
  );
  useEffect(() => {
    if (open && video.current && stream.current) {
      video.current.srcObject = stream.current;
      void video.current.play().catch(() => setError('La caméra ne peut pas démarrer.'));
    }
  }, [open]);
  async function start() {
    if (requesting) return;
    const current = ++revision.current;
    setError('');
    setRequesting(true);
    try {
      if (!navigator.mediaDevices?.getUserMedia)
        throw new Error('Webcam non disponible dans ce navigateur.');
      const media = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' },
        audio: false,
      });
      if (revision.current !== current) {
        media.getTracks().forEach((t) => t.stop());
        return;
      }
      stream.current = media;
      setOpen(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Permission caméra refusée.');
    } finally {
      if (revision.current === current) setRequesting(false);
    }
  }
  function capture() {
    const v = video.current;
    if (!v?.videoWidth) return;
    const canvas = document.createElement('canvas');
    canvas.width = v.videoWidth;
    canvas.height = v.videoHeight;
    canvas.getContext('2d')?.drawImage(v, 0, 0);
    const current = revision.current;
    canvas.toBlob((blob) => {
      if (blob && revision.current === current) {
        onCapture(new File([blob], 'camera.png', { type: 'image/png' }));
        stop();
      }
    }, 'image/png');
  }
  return (
    <div className="webcam-control">
      <button
        className="text-button"
        disabled={disabled || open || requesting}
        onClick={() => void start()}
      >
        <Camera size={17} />
        Activer la webcam
      </button>
      <small>Activation volontaire · autorisation du navigateur requise.</small>
      {error && <p role="alert">{error}</p>}
      {open && (
        <div className="webcam-panel">
          <div className="panel-heading">
            <h3>Capture locale</h3>
            <button aria-label="Fermer la webcam" onClick={stop}>
              <X size={18} />
            </button>
          </div>
          <video ref={video} muted playsInline onLoadedMetadata={() => setReady(true)} />
          <button className="primary-button" disabled={!ready} onClick={capture}>
            Capturer et arrêter la caméra
          </button>
        </div>
      )}
    </div>
  );
}
