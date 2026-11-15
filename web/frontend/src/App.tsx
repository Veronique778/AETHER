import { useEffect } from 'react';
import { BiosignalPage, BiosignalProvider, usePersonalView } from './features/biosignals/BiosignalPage';
import { LiveSensorsPage } from './features/sensors/LiveSensorsPage';
import { AboutPage } from './features/about/AboutPage';
import { BodyPage } from './features/body/BodyPage';
import { CoOrbitPage } from './features/co-orbit/CoOrbitPage';
import { MissionControlPage } from './features/mission-control/MissionControlPage';
import { MissionLabPage } from './features/mission-lab/MissionLabPage';
import { PhantomPage } from './features/phantom/PhantomPage';
import { RecoveryPage } from './features/recovery/RecoveryPage';
import { SciencePage } from './features/science/SciencePage';
import { SettingsPage } from './features/settings/SettingsPage';
import { SymbiosisPage } from './features/symbiosis/SymbiosisPage';
import { AuthPage } from './features/auth/AuthPage';
import { ProfilePage } from './features/auth/ProfilePage';
import { AppShell, BackendUnavailable } from './layout/AppShell';
import { isDesktop } from './desktop/bridge';
import { navigate, RouterProvider, useRoute } from './lib/router';
import { AppStateProvider, useApp } from './state/AppState';
import { AuthProvider, useAuth } from './state/AuthState';
import { missionNeedsSyntheticAdapter, personalRouteState } from './state/personalAccess';
import { MissionPreviewBridge } from './state/MissionPreviewBridge';
import { Empty, Loading, PendingBackend } from './ui';

function Routes() {
  const { user } = useAuth();
  const { segments } = useRoute();
  const { mode } = useApp();
  const personalView = usePersonalView();
  const route = segments[0] ?? '';
  const missionPreview = mode === 'live' && missionNeedsSyntheticAdapter(route, personalView);
  const content = (() => { switch (segments[0]) {
    case undefined: return <MissionControlPage />;
    case 'biosignals': return mode === 'live' ? <LiveSensorsPage /> : <BiosignalPage />;
    case 'body': return <BodyPage />;
    case 'phantom': return <PhantomPage />;
    case 'symbiosis': return <SymbiosisPage />;
    case 'co-orbit': return <CoOrbitPage />;
    case 'recovery': return <RecoveryPage />;
    case 'mission-lab': return <MissionLabPage />;
    case 'science': return <SciencePage />;
    case 'about': return <AboutPage />;
    case 'settings': return <SettingsPage />;
    case 'login': case 'register': case 'password-reset': case 'recover': case 'recovery-code': return <AuthPage />;
    case 'profile': return <ProfilePage key={user?.id ?? 'signed-out'} />;
    default: return <Empty title="Page not found" icon="compass">Use the navigation to choose a module.</Empty>;
  } })();
  return missionPreview ? <MissionPreviewBridge>{content}</MissionPreviewBridge> : content;
}

function Gate() {
  const { connection, mode, personalApiAvailable } = useApp();
  const { status, recoveryCodeNotice } = useAuth();
  const { segments } = useRoute();
  const route = segments[0] ?? '';
  const onAuthRoute = ['login', 'register', 'password-reset', 'recover', 'recovery-code'].includes(route);
  const personalRoute = route === 'profile';
  const accountState = personalRoute ? personalRouteState(mode, personalApiAvailable, status) : null;
  useEffect(() => {
    if (recoveryCodeNotice && route !== 'recovery-code') navigate('/recovery-code', { replace: true });
  }, [recoveryCodeNotice, route]);
  if (recoveryCodeNotice && route !== 'recovery-code') return <AuthPage forceRecoveryCode />;
  if (connection === 'checking' && !recoveryCodeNotice) return <Loading label={isDesktop && mode === 'live' ? 'Starting the AETHER backend' : 'Connecting to AETHER'} className="min-h-screen" />;
  if (connection === 'offline' && mode === 'live' && !recoveryCodeNotice) return <BackendUnavailable />;
  if (onAuthRoute) return <AuthPage />;
  if (accountState === 'demo' || accountState === 'sign-in') return <AuthPage />;
  if (accountState === 'pending') {
    return <main className="mx-auto max-w-3xl p-4 sm:p-8"><PendingBackend contract="AETHER Personal API 1.5" owner="Backend №2" /></main>;
  }
  if (accountState === 'checking') return <Loading label="Checking account state" className="min-h-screen" />;
  return <AppShell><Routes /></AppShell>;
}

export function App() {
  return (
    <AppStateProvider>
      <AuthProvider>
        <BiosignalProvider><RouterProvider>
          <Gate />
        </RouterProvider></BiosignalProvider>
      </AuthProvider>
    </AppStateProvider>
  );
}
