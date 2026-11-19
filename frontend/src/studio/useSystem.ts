import { useEffect, useState } from 'react';
import { api, errorMessage } from '../api/client';
import type { Health, Metadata } from '../api/contracts';

export function useSystem() {
  const [health, setHealth] = useState<Health | null>(null);
  const [metadata, setMetadata] = useState<Metadata | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [timings, setTimings] = useState<{ at: string; ms: number }[]>([]);
  useEffect(() => {
    const controller = new AbortController();
    let inFlight = false;
    async function poll() {
      if (inFlight) return;
      inFlight = true;
      setLoading(true);
      const started = performance.now();
      const results = await Promise.allSettled([
        api.health(controller.signal),
        api.metadata(controller.signal),
      ]);
      if (controller.signal.aborted) return;
      setHealth(results[0].status === 'fulfilled' ? results[0].value : null);
      setMetadata(results[1].status === 'fulfilled' ? results[1].value : null);
      const failed = results.find((r) => r.status === 'rejected');
      setError(failed?.status === 'rejected' ? errorMessage(failed.reason) : '');
      if (!failed)
        setTimings((rows) =>
          [{ at: new Date().toISOString(), ms: performance.now() - started }, ...rows].slice(0, 30),
        );
      setLoading(false);
      inFlight = false;
    }
    void poll();
    const timer = setInterval(() => void poll(), 30000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [revision]);
  return { health, metadata, error, loading, timings, refresh: () => setRevision((r) => r + 1) };
}
export type SystemState = ReturnType<typeof useSystem>;
