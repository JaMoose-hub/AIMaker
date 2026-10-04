// Real mobile conversation UI/hooks, isolated synthetic transport only.
import React from 'react';
import { createRoot } from 'react-dom/client';
import { LocaleProvider } from '../src/lib/i18n';
import MobileWebApp from '../src/components/MobileWebApp';
import '../src/styles.css';
import '../src/tinkro.css';

document.documentElement.dataset.theme = new URLSearchParams(location.search).get('theme') === 'light' ? 'light' : 'dark';
localStorage.setItem('tinkro.browser.pairing.v1', JSON.stringify({ token: 'synthetic-test-help-token', session_id: 'test-help-phone',
    conversation_id: 'test-help-conversation', context_id: 'test-help-context', title: '手機接線檢查', base_url: location.origin }));
const qa = { errors: [] as string[], cameraOpens: 0, sockets: 0 };
(window as unknown as { __mobileHelpQA: typeof qa }).__mobileHelpQA = qa;
window.addEventListener('error', event => qa.errors.push(event.message));
window.addEventListener('unhandledrejection', event => qa.errors.push(String(event.reason)));
const originalError = console.error.bind(console);
console.error = (...values) => { qa.errors.push(values.map(String).join(' ')); originalError(...values); };
class FixtureSocket {
    static OPEN = 1; static CONNECTING = 0; static CLOSED = 3;
    readyState = 1;
    onmessage: ((event: { data: string }) => void) | null = null;
    onclose: (() => void) | null = null;
    onerror: (() => void) | null = null;
    constructor() { qa.sockets++; }
    close() { this.readyState = 3; }
}
window.WebSocket = FixtureSocket as unknown as typeof WebSocket;
if (navigator.mediaDevices) navigator.mediaDevices.getUserMedia = async () => {
    qa.cameraOpens++; throw new Error('The isolated fixture does not open a real camera.');
};
createRoot(document.getElementById('root')!).render(<LocaleProvider><MobileWebApp /></LocaleProvider>);
