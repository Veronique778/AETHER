/**
 * Desktop bridge (AETHER v0.6). Inert in a normal browser.
 *
 * The Tauri shell (desktop/src-tauri) injects `window.__AETHER_DESKTOP__` before the page loads:
 * the address of the bundled backend it started on a free localhost port, plus diagnostics.
 * No @tauri-apps/api dependency: fullscreen uses the global `window.__TAURI__` (app.withGlobalTauri).
 */
export type DesktopInfo = {
  apiBase: string;
  version: string;
  dataDir?: string;
  logFile?: string;
  backendError?: string | null;
};

type TauriWindow = { setFullscreen(v: boolean): Promise<void>; isFullscreen(): Promise<boolean> };
type TauriGlobal = { window?: { getCurrentWindow(): TauriWindow } };

declare global {
  interface Window { __AETHER_DESKTOP__?: DesktopInfo; __TAURI__?: TauriGlobal }
}

export const desktop: DesktopInfo | null = typeof window !== 'undefined' ? window.__AETHER_DESKTOP__ ?? null : null;
export const isDesktop = desktop != null;

function nativeWindow(): TauriWindow | null {
  try { return window.__TAURI__?.window?.getCurrentWindow() ?? null; } catch { return null; }
}

/** F11 toggles native fullscreen; HTML fullscreen requests (e.g. Earth Window) also fill the screen. */
export function installDesktopIntegration() {
  if (!isDesktop) return;
  document.documentElement.dataset.desktop = 'true';
  const win = nativeWindow();
  if (!win) return;
  let byElement = false;
  addEventListener('keydown', (e) => {
    if (e.key !== 'F11') return;
    e.preventDefault();
    void win.isFullscreen().then((f) => win.setFullscreen(!f)).catch(() => undefined);
  });
  document.addEventListener('fullscreenchange', () => {
    if (document.fullscreenElement) { byElement = true; void win.setFullscreen(true).catch(() => undefined); }
    else if (byElement) { byElement = false; void win.setFullscreen(false).catch(() => undefined); }
  });
}
