import { CheckCircle2, CircleDashed, TriangleAlert } from 'lucide-react';

type Tone = 'positive' | 'negative' | 'warning' | 'neutral';
export function StatusBadge({ value, label, tone }: { value?: string; label: string; tone?: Tone }) {
  const state = tone ?? (['normal', 'completed', 'available', 'active'].includes(value ?? '')
    ? 'positive'
    : ['anomaly', 'failed', 'unavailable'].includes(value ?? '')
      ? 'negative'
      : ['running', 'queued', 'retrying', 'processing', 'cancelling'].includes(value ?? '')
        ? 'warning' : 'neutral');
  const Glyph = state === 'positive' ? CheckCircle2 : state === 'negative' ? TriangleAlert : CircleDashed;
  return <span className={`ui-status ui-status--${state}`} key={`${value}-${label}-${state}`}><Glyph size={13} aria-hidden="true" />{label}</span>;
}
