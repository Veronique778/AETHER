import type { CapacitorConfig } from '@capacitor/cli';

// Production uses packaged assets, not a development server or remote URL.
const config: CapacitorConfig = {
  appId: 'org.aether.mission',
  appName: 'AETHER',
  webDir: '../web/frontend/dist',
  bundledWebRuntime: false,
  android: { allowMixedContent: false },
};
export default config;
