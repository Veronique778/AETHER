// Environment variables read at build time (Vite `import.meta.env`, or esbuild `define` in the offline build).
interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  /** 'live' (default) – use the HTTP backend; 'demo' – start with the in-browser demo adapter. */
  readonly VITE_DATA_MODE?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare module '*.css';
