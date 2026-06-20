import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { ErrorBoundary } from './components/ErrorBoundary';
import './index.css';

// Surface non-React failures (module/import errors, async throws) that an error
// boundary can't catch — these otherwise leave a silent blank window. Forwarded to
// the terminal via the main process's console-message listener.
window.addEventListener('error', (e) => {
  console.error('[window.onerror]', e.message, e.filename, e.lineno);
});
window.addEventListener('unhandledrejection', (e) => {
  console.error('[unhandledrejection]', (e.reason && e.reason.message) || e.reason);
});

const rootEl = document.getElementById('root');
if (!rootEl) {
  console.error('[main] #root element not found');
} else {
  ReactDOM.createRoot(rootEl).render(
    <React.StrictMode>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </React.StrictMode>
  );
}
