// React Bits CountUp, adapted for a bounded one-time measured-value reveal.
// See THIRD_PARTY.md. Values updated by polling are rendered immediately.
import { useInView } from 'motion/react';
import { useCallback, useLayoutEffect, useRef } from 'react';
import { useReducedEffects } from './useReducedEffects';
interface CountUpProps {
  to: number; from?: number; direction?: 'up' | 'down'; delay?: number;
  duration?: number; className?: string; startWhen?: boolean; separator?: string;
  onStart?: () => void; onEnd?: () => void;
}
export default function CountUp({ to, from = 0, direction = 'up', delay = 0,
  duration = .75, className = '', startWhen = true, separator = '', onStart, onEnd }: CountUpProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const emptyRef = useRef<HTMLSpanElement>(null);
  const started = useRef(false);
  const reduced = useReducedEffects();
  const observable = typeof IntersectionObserver !== 'undefined';
  const visible = useInView(observable ? ref : emptyRef, { once: true });
  const target = direction === 'down' ? from : to;
  const origin = direction === 'down' ? to : from;
  const decimals = Math.min(20, Math.max(...[from, to].map((value) => (String(value).split('.')[1] || '').length)));
  const format = useCallback((value: number) => {
    const text = Intl.NumberFormat('en-US', { useGrouping: !!separator,
      minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(value);
    return separator ? text.replace(/,/g, separator) : text;
  }, [decimals, separator]);
  // Set the starting/final text before paint: no target → zero flash on mount,
  // and polling updates remain exact without a stale intermediate frame.
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    const write = (value: number) => { node.textContent = format(value); };
    if (reduced || started.current || !startWhen || duration <= 0 || origin === target) {
      write(target); node.dataset.counting = 'false'; return;
    }
    if (observable && !visible) { write(origin); return; }
    write(origin);
    let frame = 0, beginning: number | undefined;
    const milliseconds = Math.min(900, duration * 1000);
    const timer = setTimeout(() => {
      node.dataset.counting = 'true';
      frame = requestAnimationFrame(function tick(now) {
        if (beginning === undefined) { beginning = now; started.current = true; onStart?.(); }
        const progress = Math.min(1, (now - beginning) / milliseconds);
        write(origin + (target - origin) * (1 - (1 - progress) ** 3));
        if (progress < 1) frame = requestAnimationFrame(tick);
        else { write(target); node.dataset.counting = 'false'; onEnd?.(); }
      });
    }, delay * 1000);
    return () => { clearTimeout(timer); cancelAnimationFrame(frame); node.dataset.counting = 'false'; };
  }, [target, origin, reduced, startWhen, duration, observable, visible, delay, format, onStart, onEnd]);
  return <span className={className} ref={ref} aria-label={format(target)}>{format(target)}</span>;
}
