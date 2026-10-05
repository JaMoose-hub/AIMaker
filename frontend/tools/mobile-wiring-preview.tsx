// Actual phone UI and hooks with a loopback-only, synthetic transport.
import React from 'react';
import { createRoot } from 'react-dom/client';
import { LocaleProvider } from '../src/lib/i18n';
import MobileWebApp from '../src/components/MobileWebApp';
import { mobileBrowserDraftKey, saveBrowserDraft } from '../src/lib/mobileBrowser';
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
async function renderPreview() {
    if (new URLSearchParams(location.search).get('parts') === '1') {
        const image = new Blob(['<svg xmlns="http://www.w3.org/2000/svg" width="120" height="90"><rect width="120" height="90" fill="#37725b"/><text x="8" y="50" fill="white">TEST ONLY</text></svg>'], { type: 'image/svg+xml' });
        await saveBrowserDraft(mobileBrowserDraftKey(location.origin, 'fixture-conversation'), { text: '', outbox: [], captureJob: null,
            attachments: [{ id: 'fixture-parts-photo', upload_id: 'fixture-parts-upload', file: image, name: 'synthetic-part.svg', filename: 'synthetic-part.svg',
                type: 'image', mime: image.type, size: image.size, width: 120, height: 90, purpose: 'parts_check' }] });
    }
    createRoot(document.getElementById('root')!).render(<LocaleProvider><MobileWebApp /></LocaleProvider>);
}
void renderPreview();
