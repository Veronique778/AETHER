import { useEffect, useState, type FormEvent } from 'react';
import { Link, navigate, useRoute } from '../../lib/router';
import { IS_MOBILE_BUILD, MOBILE_API_CONFIGURED, useApp } from '../../state/AppState';
import { useAuth } from '../../state/AuthState';
import { Button, Notice, PendingBackend } from '../../ui';

type AuthView = 'login' | 'register' | 'recover' | 'recovery-code';

function authView(path: string): AuthView {
  if (path === '/register') return 'register';
  if (path === '/recover' || path === '/password-reset') return 'recover';
  if (path === '/recovery-code') return 'recovery-code';
  return 'login';
}

export function AuthPage({ forceRecoveryCode = false }: { forceRecoveryCode?: boolean } = {}) {
  const { path } = useRoute();
  const view = forceRecoveryCode ? 'recovery-code' : authView(path);
  const { mode, setMode, personalApiAvailable } = useApp();
  const {
    status, user, error, clearError, signIn, register, recover, recoveryCodeNotice,
    showRecoveryCode, clearRecoveryCode,
  } = useAuth();
  const [busy, setBusy] = useState(false);
  const [savedCode, setSavedCode] = useState(false);
  const [copyMessage, setCopyMessage] = useState('');
  const [message, setMessage] = useState('');

  useEffect(() => {
    setSavedCode(false);
    setCopyMessage('');
  }, [recoveryCodeNotice?.code]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setMessage('');
    clearError();
    try {
      if (view === 'login') {
        await signIn(String(form.get('login') ?? ''), String(form.get('password') ?? ''));
        navigate('/profile');
      } else if (view === 'register') {
        const language = String(form.get('language') ?? 'uk');
        const result = await register({
          login: String(form.get('login') ?? ''),
          password: String(form.get('password') ?? ''),
          display_name: String(form.get('display_name') ?? ''),
          language: language === 'en' ? 'en' : 'uk',
        });
        showRecoveryCode({ login: result.user.login, code: result.recovery_code, reason: 'registration' });
        navigate('/recovery-code');
      } else if (view === 'recover') {
        const login = String(form.get('login') ?? '');
        const result = await recover({
          login,
          recovery_code: String(form.get('recovery_code') ?? ''),
          new_password: String(form.get('new_password') ?? ''),
        });
        showRecoveryCode({ login, code: result.recovery_code, reason: 'recovery' });
        navigate('/recovery-code');
      }
    } catch {
      // The auth provider keeps a safe, sanitized message for display.
    } finally {
      setBusy(false);
    }
  };

  const copyRecoveryCode = async () => {
    const code = recoveryCodeNotice?.code;
    if (!code) return;
    try {
      await navigator.clipboard.writeText(code);
      setCopyMessage('Recovery code copied. Keep it somewhere secure.');
    } catch {
      setCopyMessage('Copy was unavailable. Select and copy the code manually.');
    }
  };

  const title = view === 'register' ? 'Create AETHER account'
    : view === 'recover' ? 'Recover access'
      : view === 'recovery-code' ? 'Save your recovery code'
        : 'Sign in to AETHER';
  const recoveryCode = view === 'recovery-code' ? recoveryCodeNotice : null;
  const showUnavailable = mode === 'live' && !personalApiAvailable && view !== 'recovery-code';

  return (
    <main className="grid min-h-screen place-items-center px-4 py-8">
      <section className="card w-full max-w-lg space-y-5 p-6 sm:p-8" aria-labelledby="auth-title">
        <div className="text-center">
          <div className="eyebrow">AETHER · personal account</div>
          <h1 id="auth-title" className="mt-2 text-2xl font-semibold">{title}</h1>
          <p className="mt-2 text-sm text-ink-2">Identity and access permissions come from the authenticated backend.</p>
        </div>
        {mode === 'demo' && (
          <Notice tone="attention" title={IS_MOBILE_BUILD ? 'Mobile Demo Mode' : 'Synthetic Demo Mode'}>
            {IS_MOBILE_BUILD
              ? `This mobile build is offline demo only; personal sign-in is not enabled. ${MOBILE_API_CONFIGURED ? 'VITE_API_URL is configured, but mobile live mode is not yet validated.' : 'A future integration build must set VITE_API_URL to the HTTPS Mission Hub endpoint.'}`
              : 'The AETHER demo is available without signing in. Personal accounts and records are only available in Live Mode; no local demo identity grants access.'}
          </Notice>
        )}
        {mode === 'live' && personalApiAvailable && (
          <Notice tone="unknown">
            The short-lived personal Bearer token stays in memory only. Reloading the page signs you out; secure session persistence is not configured.
          </Notice>
        )}
        {showUnavailable && (
          <PendingBackend contract="AETHER Personal API 1.5" owner="Backend №2">
            <p className="mt-1">Legacy AETHER screens remain available without an account. No personal data will be substituted with demo records.</p>
          </PendingBackend>
        )}
        {error && <div role="alert" className="rounded-xl border border-high/40 bg-high/5 p-3 text-sm text-high">{error}</div>}
        {message && <div role="status" className="rounded-xl border border-good/40 bg-good/5 p-3 text-sm text-good">{message}</div>}

        {view === 'recovery-code' ? (
          recoveryCode ? (
            <div className="space-y-4">
              <Notice tone="attention" title="This code is shown only once">
                Store it securely now. AETHER cannot recover or email this code. It is not saved in browser storage.
              </Notice>
              <div className="rounded-xl border border-line bg-canvas p-4">
                <div className="mb-2 text-xs text-ink-3">Account: {recoveryCode.login}</div>
                <code className="block break-all select-all text-sm text-ink" aria-label="One-time recovery code">{recoveryCode.code}</code>
              </div>
              <Button className="w-full" onClick={() => void copyRecoveryCode()}>Copy recovery code</Button>
              {copyMessage && <p role="status" className="text-sm text-ink-2">{copyMessage}</p>}
              <label className="flex items-start gap-2 text-sm text-ink-2">
                <input type="checkbox" checked={savedCode} onChange={(event) => setSavedCode(event.target.checked)} className="mt-1" />
                I saved this recovery code somewhere secure.
              </label>
              <Button
                variant="primary"
                className="w-full"
                disabled={!savedCode}
                onClick={() => { clearRecoveryCode(); navigate('/login'); }}
              >
                Continue to sign in
              </Button>
            </div>
          ) : (
            <div className="space-y-4">
              <Notice tone="high">The one-time recovery code is not available in memory. It cannot be restored by reloading this page.</Notice>
              <Button variant="primary" className="w-full" onClick={() => navigate('/login')}>Continue to sign in</Button>
            </div>
          )
        ) : status === 'signed-in' && user ? (
          <div className="space-y-4">
            <p className="text-center text-ink-2">Signed in as <strong className="text-ink">{user.login}</strong> ({user.role.replace(/_/g, ' ')}).</p>
            <Button variant="primary" className="w-full" onClick={() => navigate('/profile')}>Open my profile</Button>
          </div>
        ) : showUnavailable ? null : mode === 'demo' ? (
          IS_MOBILE_BUILD
            ? null
            : <Button className="w-full" onClick={() => setMode('live')}>Switch to Live Mode</Button>
        ) : (
          <form className="space-y-4" onSubmit={(event) => void submit(event)}>
            {view === 'register' ? <>
              <label className="block text-sm">Login
                <input className="field mt-1" name="login" autoComplete="username" required minLength={3} maxLength={64} pattern="(?:[A-Za-z0-9_.]|-)+" />
              </label>
              <label className="block text-sm">Display name
                <input className="field mt-1" name="display_name" autoComplete="name" required minLength={1} maxLength={80} />
              </label>
              <label className="block text-sm">Language
                <select className="field mt-1" name="language" defaultValue="uk">
                  <option value="uk">Українська</option>
                  <option value="en">English</option>
                </select>
              </label>
              <label className="block text-sm">Password
                <input className="field mt-1" name="password" type="password" autoComplete="new-password" required minLength={12} maxLength={128} />
              </label>
            </> : view === 'recover' ? <>
              <label className="block text-sm">Login
                <input className="field mt-1" name="login" autoComplete="username" required minLength={3} maxLength={64} />
              </label>
              <label className="block text-sm">Recovery code
                <input className="field mt-1" name="recovery_code" autoComplete="off" spellCheck={false} required minLength={32} maxLength={128} />
              </label>
              <label className="block text-sm">New password
                <input className="field mt-1" name="new_password" type="password" autoComplete="new-password" required minLength={12} maxLength={128} />
              </label>
              <Notice tone="attention">Recovery uses the one-time code saved during registration or the last password change. No email is sent.</Notice>
            </> : <>
              <label className="block text-sm">Login
                <input className="field mt-1" name="login" autoComplete="username" required minLength={3} maxLength={64} />
              </label>
              <label className="block text-sm">Password
                <input className="field mt-1" name="password" type="password" autoComplete="current-password" required minLength={1} maxLength={128} />
              </label>
            </>}
            <Button type="submit" variant="primary" className="w-full" disabled={busy}>
              {busy ? 'Please wait…' : view === 'register' ? 'Create account' : view === 'recover' ? 'Recover account' : 'Sign in'}
            </Button>
          </form>
        )}

        {view !== 'recovery-code' && mode === 'live' && personalApiAvailable && (
          <nav className="flex flex-wrap justify-center gap-x-4 gap-y-2 border-t border-line pt-4 text-sm">
            {view !== 'login' && <Link to="/login" className="text-teal-300 hover:underline">Sign in</Link>}
            {view !== 'register' && <Link to="/register" className="text-teal-300 hover:underline">Create account</Link>}
            {view !== 'recover' && <Link to="/recover" className="text-ink-2 hover:underline">Use recovery code</Link>}
          </nav>
        )}
        {mode === 'live' && personalApiAvailable && <p className="text-center text-xs text-ink-3">The recovery code cannot be emailed or restored. Keep it private.</p>}
      </section>
    </main>
  );
}
