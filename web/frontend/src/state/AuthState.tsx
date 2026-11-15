import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  createAccountApi,
  type AccountApi,
  type LoginResult,
  type RecoveryResult,
  type RegistrationInput,
  type RegistrationResult,
  type UserIdentity,
} from '../api/accountApi';
import { navigate } from '../lib/router';
import { currentAuthToken, setAuthToken } from '../lib/secureFetch';
import { API_BASE, useApp } from './AppState';

export type AuthStatus = 'checking' | 'signed-out' | 'signed-in';
export type RecoveryCodeNotice = {
  login: string;
  code: string;
  reason: 'registration' | 'recovery' | 'password-change';
};

type AuthState = {
  status: AuthStatus;
  user: UserIdentity | null;
  token: string | null;
  api: AccountApi;
  recoveryCodeNotice: RecoveryCodeNotice | null;
  showRecoveryCode: (notice: RecoveryCodeNotice) => void;
  clearRecoveryCode: () => void;
  updateSignedInIdentity: (user: UserIdentity) => void;
  error: string;
  clearError: () => void;
  signIn: (login: string, password: string) => Promise<void>;
  register: (input: RegistrationInput) => Promise<RegistrationResult>;
  recover: (input: { login: string; recovery_code: string; new_password: string }) => Promise<RecoveryResult>;
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

function message(error: unknown): string {
  return error instanceof Error ? error.message : 'Account request failed.';
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const { mode, retry } = useApp();
  const api = useMemo(() => createAccountApi(API_BASE), []);
  const [status, setStatus] = useState<AuthStatus>('checking');
  const [user, setUser] = useState<UserIdentity | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [recoveryCodeNotice, setRecoveryCodeNotice] = useState<RecoveryCodeNotice | null>(null);
  const [error, setError] = useState('');

  const clearSignedInState = useCallback((clearRecoveryCode = true) => {
    setAuthToken(null);
    setToken(null);
    setUser(null);
    setStatus('signed-out');
    if (clearRecoveryCode) setRecoveryCodeNotice(null);
    window.dispatchEvent(new CustomEvent('aether:account-changed'));
  }, []);

  useEffect(() => {
    clearSignedInState();
    setError('');
  }, [mode, clearSignedInState]);

  useEffect(() => {
    const expired = () => {
      clearSignedInState();
      setError('Your personal session expired. Sign in again.');
    };
    window.addEventListener('aether:auth-expired', expired);
    return () => window.removeEventListener('aether:auth-expired', expired);
  }, [clearSignedInState]);

  useEffect(() => {
    if (!recoveryCodeNotice) return;
    const warnBeforeLeaving = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', warnBeforeLeaving);
    return () => window.removeEventListener('beforeunload', warnBeforeLeaving);
  }, [recoveryCodeNotice]);

  const acceptLogin = (result: LoginResult) => {
    setAuthToken(result.access_token);
    setToken(result.access_token);
    setUser(result.user);
    setStatus('signed-in');
    setRecoveryCodeNotice(null);
    setError('');
    window.dispatchEvent(new CustomEvent('aether:account-changed'));
    retry();
  };

  const signIn = async (login: string, password: string) => {
    setError('');
    try { acceptLogin(await api.login(login, password)); }
    catch (cause) { setError(message(cause)); throw cause; }
  };

  const register = async (input: RegistrationInput) => {
    setError('');
    try { return await api.register(input); }
    catch (cause) { setError(message(cause)); throw cause; }
  };

  const recover = async (input: { login: string; recovery_code: string; new_password: string }) => {
    setError('');
    try { return await api.recover(input); }
    catch (cause) { setError(message(cause)); throw cause; }
  };

  const changePassword = async (currentPassword: string, newPassword: string) => {
    if (!token || !user) throw new Error('Sign in before changing the password.');
    setError('');
    try {
      const result = await api.changePassword(token, currentPassword, newPassword);
      setRecoveryCodeNotice({ login: user.login, code: result.recovery_code, reason: 'password-change' });
      clearSignedInState(false);
      navigate('/recovery-code');
    } catch (cause) {
      setError(message(cause));
      throw cause;
    }
  };

  const signOut = async () => {
    const signedInToken = token ?? currentAuthToken();
    clearSignedInState();
    setError('');
    if (signedInToken) {
      try {
        await api.logout(signedInToken);
      } catch (cause) {
        const safeMessage = message(cause);
        setError(`You are signed out on this device, but server logout could not be confirmed. ${safeMessage}`);
        throw cause;
      }
    }
  };

  const value: AuthState = {
    status,
    user,
    token,
    api,
    recoveryCodeNotice,
    showRecoveryCode: setRecoveryCodeNotice,
    clearRecoveryCode: () => setRecoveryCodeNotice(null),
    updateSignedInIdentity: setUser,
    error,
    clearError: () => setError(''),
    signIn,
    register,
    recover,
    changePassword,
    signOut,
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>');
  return value;
}
