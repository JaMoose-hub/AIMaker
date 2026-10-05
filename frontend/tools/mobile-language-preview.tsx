// Actual phone surface and locale provider, with no API, camera or Pi transport.
import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { LocaleProvider } from '../src/lib/i18n';
import { MobileWebSurface } from '../src/components/MobileWebApp';
import '../src/styles.css';
import '../src/tinkro.css';

const screen = new URLSearchParams(location.search).get('screen');
const landscape = new URLSearchParams(location.search).get('layout') === 'landscape';
const referencePreview = new URLSearchParams(location.search).has('reference');
const noop = async () => {};
function PhonePreview() {
  const [draft, setDraft] = useState('Keep this draft');
  const [reference, setReference] = useState(referencePreview);
  const workspace = { ready: true, pairing: screen === 'paired' ? { session_id: 'fixture' } : null,
    connected: true, secureContext: true, busy: false, error: '', api: null,
    session: { session_id: 'fixture', conversation_id: 'fixture', title: 'DEMO · 3 items',
      context: { stage: 'guide' }, context_id: 'fixture', view: { wire_id: null }, stream: { active: false, state: 'finding' } },
    conversation: { id: 'fixture', context_epoch: 0, round: 1, messages: [], jobs: [], before: null },
    draft, setDraft, attachments: [], outbox: [], capture: null, captureJob: null, captureTicket: null,
    rtc: { stream: null, settings: null, stats: {}, status: 'off' }, canCapture: false,
    inheritedMediaLabel: reference ? '此訊息引用：最近照片（3 張）· pi-side-a.jpg、pi-side-b.jpg、component-header.jpg' : null,
    removeMediaReference: () => setReference(false),
    pair: noop, send: noop, disconnect: noop, stopStream: noop, openCapture: noop, older: noop,
    addFiles: noop, removeAttachment() {}, retry: noop, removeOutbox() {},
  } as unknown as Parameters<typeof MobileWebSurface>[0]['workspace'];
  return <MobileWebSurface workspace={workspace} />;
}
createRoot(document.getElementById('root')!).render(screen ? <LocaleProvider><PhonePreview /></LocaleProvider> : <>
  <style>{`body{padding:24px;color:var(--ink-primary)}h1{font-size:20px;margin:0 0 8px}p{font-size:13px;color:var(--ink-secondary)}.phone-preview-grid{display:flex;gap:28px;justify-content:center;flex-wrap:wrap;margin-top:20px}.phone-preview-grid h2{font-size:14px}iframe{width:390px;height:780px;border:1px solid var(--line-default);border-radius:16px;max-width:100%}`}</style>
  <header><h1>{referencePreview ? '手機引用 · 可隨時取消' : '手機語系 · 繁中 / English'}</h1><p>隔離預覽，無相機、AI 或 Pi 連線。聊天草稿與目前分頁不會因語系切換而重設。</p></header>
  <div className="phone-preview-grid">
    {!landscape ? <section><h2>配對前</h2><iframe src="/?screen=unpaired" title="配對前語系預覽" /></section> : null}
    <section><h2>已連線</h2><iframe src={`/?screen=paired${referencePreview ? '&reference' : ''}`} title="已連線語系預覽" style={landscape ? { width: 844, height: 390 } : undefined} /></section>
  </div>
</>);
