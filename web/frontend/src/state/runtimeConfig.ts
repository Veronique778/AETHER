export type ApiBaseConfig = {
  desktopApiBase?: string;
  configuredApiBase?: string;
  mobileBuild: boolean;
  browserOrigin?: string;
};

export function resolveApiBase(config: ApiBaseConfig): string {
  const desktopApiBase = config.desktopApiBase?.trim();
  if (desktopApiBase) return desktopApiBase;

  const configuredApiBase = config.configuredApiBase?.trim();
  if (configuredApiBase) return configuredApiBase;

  // A mobile WebView origin is the app shell, not the Mission Hub API.
  if (config.mobileBuild) return '';

  return config.browserOrigin && config.browserOrigin !== 'null'
    ? config.browserOrigin
    : 'http://127.0.0.1:8000';
}
