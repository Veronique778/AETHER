/**
 * Minimal typed hash router. Hash URLs work from file://, static hosting and the
 * dev server alike. The API (useRoute / navigate / <Link>) mirrors React Router
 * closely enough that switching to react-router-dom is a local change.
 */
import { createContext, useContext, useEffect, useMemo, useState, type AnchorHTMLAttributes, type ReactNode } from 'react';

export type Route = { path: string; segments: string[]; query: URLSearchParams };

function parse(): Route {
  const raw = (globalThis.location?.hash ?? '').replace(/^#/, '') || '/';
  const [path, qs = ''] = raw.split('?');
  const clean = '/' + path.split('/').filter(Boolean).join('/');
  return { path: clean, segments: clean.split('/').filter(Boolean), query: new URLSearchParams(qs) };
}

const RouteContext = createContext<Route>({ path: '/', segments: [], query: new URLSearchParams() });

export function navigate(to: string, opts: { replace?: boolean } = {}) {
  const hash = '#' + (to.startsWith('/') ? to : '/' + to);
  if (opts.replace) history.replaceState(null, '', hash);
  else if (location.hash !== hash) history.pushState(null, '', hash);
  dispatchEvent(new HashChangeEvent('hashchange'));
}

export function RouterProvider({ children }: { children: ReactNode }) {
  const [route, setRoute] = useState<Route>(parse);
  useEffect(() => {
    const on = () => setRoute(parse());
    addEventListener('hashchange', on);
    addEventListener('popstate', on);
    return () => { removeEventListener('hashchange', on); removeEventListener('popstate', on); };
  }, []);
  const value = useMemo(() => route, [route]);
  return <RouteContext.Provider value={value}>{children}</RouteContext.Provider>;
}

export const useRoute = () => useContext(RouteContext);

export function Link({ to, children, ...rest }: { to: string; children: ReactNode } & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href'>) {
  return (
    <a
      href={'#' + to}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
        e.preventDefault();
        navigate(to);
        rest.onClick?.(e);
      }}
      {...rest}
    >
      {children}
    </a>
  );
}

/** Update one query parameter of the current route without adding history noise. */
export function setQuery(key: string, value: string | null) {
  const r = parse();
  if (value == null) r.query.delete(key); else r.query.set(key, value);
  const qs = r.query.toString();
  navigate(r.path + (qs ? '?' + qs : ''), { replace: true });
}
