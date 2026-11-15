import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// Relative base: the dist/ folder works at any path (Cloudflare Pages root, a sub-folder, or file preview).
export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss()],
  build: { target: 'es2020', assetsInlineLimit: 0, chunkSizeWarningLimit: 900 },
  server: { port: 5174, strictPort: true },
});
