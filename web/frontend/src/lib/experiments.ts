import type { AetherApi, SavedExperiment } from '../api/types';

export type { SavedExperiment };

/**
 * Saved MISSION LAB experiments.
 * Live Mode with a v0.8+ backend: stored server-side (GET/POST/DELETE /api/mission-lab/experiments, SQLite in the
 * user's data directory). Demo Mode or an older backend: stored in this browser (localStorage).
 */
const KEY = 'aether.experiments.v1';

export function listExperiments(): SavedExperiment[] {
  try { return JSON.parse(localStorage.getItem(KEY) ?? '[]') as SavedExperiment[]; } catch { return []; }
}
export function saveExperiment(e: SavedExperiment): boolean {
  try { localStorage.setItem(KEY, JSON.stringify([e, ...listExperiments()].slice(0, 30))); return true; } catch { return false; }
}
export function deleteExperiment(id: string) {
  try { localStorage.setItem(KEY, JSON.stringify(listExperiments().filter((e) => e.id !== id))); } catch { /* ignore */ }
}

/** Storage location chosen from the connected backend's capabilities. */
export function experimentStore(api: AetherApi, remote: boolean) {
  return remote ? {
    where: 'server' as const,
    list: () => api.experiments(),
    save: async (e: SavedExperiment) => (await api.saveExperiment(e)).saved,
    remove: async (id: string) => { await api.deleteExperiment(id); },
  } : {
    where: 'browser' as const,
    list: async () => listExperiments(),
    save: async (e: SavedExperiment) => saveExperiment(e),
    remove: async (id: string) => deleteExperiment(id),
  };
}
