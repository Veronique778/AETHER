import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { installDesktopIntegration } from './desktop/bridge';
import { installSecureFetch } from './lib/secureFetch';
import { API_BASE } from './state/AppState';
import './styles/index.css';

installSecureFetch(API_BASE);
installDesktopIntegration();
if (import.meta.env.VITE_MOBILE_APP === '1') {
  document.documentElement.dataset.aetherMobile = 'true';
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
