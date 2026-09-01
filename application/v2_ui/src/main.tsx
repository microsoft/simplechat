// main.tsx
// Entry point. The router basename is /v2 because Flask serves the SPA there, while the
// asset base is /static/v2 so bundle files go through Flask's static handler.

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { App } from './App';
import './styles/theme.css';

const container = document.getElementById('root');

if (!container) {
    throw new Error('Root container #root was not found in the document.');
}

createRoot(container).render(
    <StrictMode>
        <BrowserRouter basename="/v2">
            <App />
        </BrowserRouter>
    </StrictMode>,
);
