export type AccountRouteState = 'demo' | 'pending' | 'checking' | 'sign-in' | 'authorized';

export function personalRouteState(
  mode: 'demo' | 'live',
  personalApiAvailable: boolean,
  authStatus: 'checking' | 'signed-out' | 'signed-in',
): AccountRouteState {
  if (mode === 'demo') return 'demo';
  if (!personalApiAvailable) return 'pending';
  if (authStatus === 'checking') return 'checking';
  return authStatus === 'signed-in' ? 'authorized' : 'sign-in';
}

/** Mission / research screens that use the labelled synthetic demonstration interface (no personal data). */
export const DEMO_RESEARCH_PAGES = ['', 'biosignals', 'body', 'phantom', 'symbiosis', 'co-orbit', 'recovery', 'mission-lab', 'science'];

/**
 * Legacy Live Mode route guard (AETHER 1.5, retained only for old contract tests). The unified shell no longer calls it. Personal screens: BIOSIGNALS (Live Sensors · Bluetooth HRS, authenticated
 * Device Manager API), BODY and PHANTOM for Personal Monitoring / Live Sensors. Every other mission/research screen
 * remains the separately labelled synthetic DEMO and is not opened implicitly in Live Mode.
 */
export function liveRouteAllowed(route: string, personalView: boolean): boolean {
  if (!DEMO_RESEARCH_PAGES.includes(route)) return true;
  return route === 'biosignals' || (personalView && (route === 'body' || route === 'phantom'));
}


/**
 * In the unified Windows shell, mission/crew/cabin/RECOVERY screens run under the
 * labelled synthetic API without changing the user's authenticated Live Mode.
 * BODY and PHANTOM use that API only when the source is explicitly non-personal.
 */
export function missionNeedsSyntheticAdapter(route: string, personalView: boolean): boolean {
  return ['', 'symbiosis', 'co-orbit', 'recovery', 'mission-lab', 'science'].includes(route)
    || ((route === 'body' || route === 'phantom') && !personalView);
}
