
/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_MOBILE_APP?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
