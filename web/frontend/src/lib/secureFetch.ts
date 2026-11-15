const HEADER = 'X-AETHER-Token';
const PUBLIC_AUTH_PATHS = new Set(['/api/auth/register', '/api/auth/login', '/api/auth/recover']);
let launchToken: string | null = null;
let personalToken: string | null = null;
let launchTokenRequest: Promise<string | null> | null = null;

function fromMeta(): string | null {
  try { return document.querySelector('meta[name="aether-session-token"]')?.getAttribute('content') || null; } catch { return null; }
}

export function sessionToken(): string | null { return launchToken ?? fromMeta(); }
export function setAuthToken(value: string | null) { personalToken = value; }
export function currentAuthToken(): string | null { return personalToken; }

function isBackendUrl(url: URL, apiBase: string): boolean {
  if (!url.pathname.startsWith('/api/')) return false;
  if (url.origin === location.origin) return true;
  try { return url.origin === new URL(apiBase).origin; } catch { return false; }
}

function withoutAetherCredentials(input: RequestInfo | URL, init?: RequestInit): Headers {
  const headers = input instanceof Request ? new Headers(input.headers) : new Headers();
  new Headers(init?.headers).forEach((value, key) => headers.set(key, value));
  const authorization = headers.get('Authorization');
  if (authorization && /^Bearer\s/i.test(authorization)) headers.delete('Authorization');
  headers.delete(HEADER);
  return headers;
}

function isLocalBackend(apiBase: string): boolean {
  try {
    const url = new URL(apiBase);
    return url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  } catch {
    return false;
  }
}

function bodyObject(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

export function isInvalidLaunchToken(status: number, body: unknown): boolean {
  if (status !== 401) return false;
  const value = bodyObject(body);
  return typeof value?.detail === 'string' && /aether session token/i.test(value.detail);
}

export function isExpiredPersonalResponse(status: number, body: unknown, hasBearer: boolean, pathname: string): boolean {
  if (status !== 401 || !hasBearer || PUBLIC_AUTH_PATHS.has(pathname)) return false;
  const value = bodyObject(body);
  const error = bodyObject(value?.error);
  if (error?.code === 'unauthenticated') return true;
  return typeof value?.detail === 'string' && /valid personal session|personal session.*expired/i.test(value.detail);
}

export function installSecureFetch(apiBase: string) {
  if (typeof window === 'undefined' || (window as unknown as { __aetherFetch?: boolean }).__aetherFetch) return;
  (window as unknown as { __aetherFetch?: boolean }).__aetherFetch = true;
  launchToken = fromMeta();
  const original = window.fetch.bind(window);
  const localBackend = isLocalBackend(apiBase);
  const secureBackend = localBackend || (() => {
    try { return new URL(apiBase).protocol === 'https:'; } catch { return false; }
  })();

  const getLaunchToken = (refresh = false): Promise<string | null> => {
    if (!localBackend) return Promise.resolve(null);
    if (refresh) launchToken = null;
    if (launchToken && !refresh) return Promise.resolve(launchToken);
    if (launchTokenRequest) return launchTokenRequest;
    launchTokenRequest = original(`${apiBase}/api/session`, { cache: 'no-store' })
      .then(async (response) => {
        if (!response.ok) return null;
        const value: unknown = await response.json();
        const data = bodyObject(value);
        return typeof data?.token === 'string' && data.token.length > 0 ? data.token : null;
      })
      .then((value) => {
        launchToken = value;
        return value;
      })
      .catch(() => null)
      .finally(() => { launchTokenRequest = null; });
    return launchTokenRequest;
  };

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    let url: URL;
    try {
      url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, location.href);
    } catch {
      return original(input, init);
    }
    if (!isBackendUrl(url, apiBase)) {
      return original(input, { ...init, headers: withoutAetherCredentials(input, init) });
    }
    if (url.pathname === '/api/session') {
      return original(input, { ...init, headers: withoutAetherCredentials(input, init) });
    }

    const publicAuth = PUBLIC_AUTH_PATHS.has(url.pathname);
    const requestTemplate = input instanceof Request ? new Request(input, init) : null;
    const inputHeaders = requestTemplate?.headers;
    const initHeaders = new Headers(init?.headers);
    const explicitAuthorization = initHeaders.get('Authorization') ?? inputHeaders?.get('Authorization') ?? null;
    const requestBearer = publicAuth || !secureBackend ? null : (explicitAuthorization ?? personalToken);
    const hasBearer = Boolean(requestBearer?.startsWith('Bearer '));

    const send = (token: string | null) => {
      const headers = new Headers(inputHeaders);
      initHeaders.forEach((value, key) => headers.set(key, value));
      if (token) headers.set(HEADER, token);
      if (publicAuth) headers.delete('Authorization');
      else if (requestBearer) headers.set('Authorization', requestBearer);
      const requestInit = { ...init, headers };
      return requestTemplate
        ? original(new Request(requestTemplate.clone(), requestInit))
        : original(input, requestInit);
    };

    const initialLaunchToken = await getLaunchToken();
    let response = await send(initialLaunchToken);
    let errorBody: unknown = null;
    if (response.status === 401) {
      try { errorBody = await response.clone().json(); } catch { /* Errors without JSON remain status-only. */ }
    }

    if (isInvalidLaunchToken(response.status, errorBody) && localBackend) {
      const refreshed = await getLaunchToken(true);
      if (refreshed && refreshed !== initialLaunchToken) {
        response = await send(refreshed);
        errorBody = null;
        if (response.status === 401) {
          try { errorBody = await response.clone().json(); } catch { /* Errors without JSON remain status-only. */ }
        }
      }
    }

    if (isExpiredPersonalResponse(response.status, errorBody, hasBearer, url.pathname)) {
      personalToken = null;
      window.dispatchEvent(new CustomEvent('aether:auth-expired'));
    }
    return response;
  };
}
