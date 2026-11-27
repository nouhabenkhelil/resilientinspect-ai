import { useRef, type ComponentPropsWithoutRef } from 'react';
import { useInView, useReducedMotion } from 'motion/react';

/** Reveal on first visibility, including panels initially below the fold. */
export function useRevealOnce<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const fallback = useRef<T>(null);
  const observable = typeof IntersectionObserver !== 'undefined';
  const visible = useInView(observable ? ref : fallback, { once: true, amount: .12 });
  const reduced = useReducedMotion();
  return { ref, 'data-motion-visible': reduced || !observable || visible ? 'true' : 'false' };
}

export function RevealSection({ className = '', ...props }: ComponentPropsWithoutRef<'section'>) {
  const reveal = useRevealOnce<HTMLElement>();
  return <section {...props} {...reveal} className={`viewport-reveal ${className}`} />;
}
