import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { IndustrialAuth } from './portal/Auth';
import { PORTAL_MODE } from './portal/session';
import './styles.css';
import './premium.css';
import './motion.css';
import './role-themes.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {PORTAL_MODE ? (
      <IndustrialAuth>
        <App />
      </IndustrialAuth>
    ) : (
      <App />
    )}
  </StrictMode>,
);
