import { useSyncExternalStore } from 'react';
import type { RadiationResult } from '../api/types';

/**
 * Hand-off of radiation exposure events from MISSION LAB to PHANTOM. PHANTOM shows them as exposure context next
 * to its detectors; they are not detector inputs and not a health signal. Kept in memory plus sessionStorage
 * (best effort – storage may be unavailable).
 */
export type RadiationContext = { title: string; at: string; final: RadiationResult['final']; fraction: RadiationResult['fraction_of_career_limit']; events: RadiationResult['events']; days: number };
const KEY = 'aether.radiationContext';
let current: RadiationContext | null = (() => { try { const v = sessionStorage.getItem(KEY); return v ? (JSON.parse(v) as RadiationContext) : null; } catch { return null; } })();
const subs = new Set<() => void>();

export function publishRadiation(r: RadiationResult) {
  current = { title: r.title, at: new Date().toISOString(), final: r.final, fraction: r.fraction_of_career_limit, events: r.events, days: r.days };
  try { sessionStorage.setItem(KEY, JSON.stringify(current)); } catch { /* storage unavailable */ }
  subs.forEach((f) => f());
}

export function useRadiationContext() {
  return useSyncExternalStore((f) => { subs.add(f); return () => subs.delete(f); }, () => current, () => current);
}
