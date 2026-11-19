import { useEffect, useState } from 'react';

/** Static fallbacks for touch/mobile, reduced motion and older browsers. */
export function useReducedEffects() {
  const query = '(prefers-reduced-motion: reduce), (max-width: 700px), (pointer: coarse)';
  const [reduced, setReduced] = useState(() =>
    typeof window === 'undefined' || !window.matchMedia ? true : window.matchMedia(query).matches,
  );
  useEffect(() => {
    if (!window.matchMedia) return;
    const media = window.matchMedia(query);
    const sync = () => setReduced(media.matches);
    sync();
    media.addEventListener?.('change', sync);
    return () => media.removeEventListener?.('change', sync);
  }, []);
  return reduced;
}
