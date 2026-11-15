/**
 * Local-data portability (v0.6). Browser localStorage is per origin, so data saved by AETHER in a browser
 * (preferences, saved MISSION LAB experiments, confirmed CO-ORBIT plans) is not visible to the desktop app
 * (origin http://tauri.localhost) and vice versa. Export / import moves the `aether.*` keys between them.
 * Import only adds or overwrites `aether.*` keys – it never deletes anything.
 */
const PREFIX = 'aether.';
export type LocalBundle = { app: 'AETHER'; kind: 'local-data'; version: 1; exported_at: string; items: Record<string, string> };

export function exportLocalData(): LocalBundle {
  const items: Record<string, string> = {};
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k?.startsWith(PREFIX)) items[k] = localStorage.getItem(k) ?? '';
    }
  } catch { /* storage unavailable */ }
  return { app: 'AETHER', kind: 'local-data', version: 1, exported_at: new Date().toISOString(), items };
}

export function importLocalData(text: string): number {
  const b = JSON.parse(text) as Partial<LocalBundle>;
  if (b.app !== 'AETHER' || b.kind !== 'local-data' || typeof b.items !== 'object' || !b.items) throw new Error('Not an AETHER local-data file.');
  let n = 0;
  for (const [k, v] of Object.entries(b.items)) {
    if (!k.startsWith(PREFIX) || typeof v !== 'string') continue;
    localStorage.setItem(k, v);
    n++;
  }
  return n;
}
