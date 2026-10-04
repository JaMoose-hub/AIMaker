// Actual phone UI and hooks with a loopback-only, synthetic transport.
import React from 'react';
import { createRoot } from 'react-dom/client';
import { LocaleProvider } from '../src/lib/i18n';
import MobileWebApp from '../src/components/MobileWebApp';
import '../src/styles.css';
import '../src/tinkro.css';

document.documentElement.dataset.theme = new URLSearchParams(location.search).get('theme') === 'light' ? 'light' : 'dark';
localStorage.setItem('tinkro.browser.pairing.v1', JSON.stringify({ token: 'synthetic-phone-token', session_id: 'fixture-phone',
    conversation_id: 'fixture-conversation', context_id: 'fixture-context', title: '接線照片對話測試', base_url: location.origin }));
class FixtureSocket {
    readyState = 1;
    onmessage: ((event: { data: string }) => void) | null = null;
    onclose: (() => void) | null = null;
    onerror: (() => void) | null = null;
    close() { this.readyState = 3; }
}
window.WebSocket = FixtureSocket as unknown as typeof WebSocket;
createRoot(document.getElementById('root')!).render(<LocaleProvider><MobileWebApp /></LocaleProvider>);
