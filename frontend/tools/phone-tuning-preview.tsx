import { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { LocaleProvider, useI18n } from '../src/lib/i18n';
import { usePhoneCameraTune } from '../src/lib/usePhoneCameraTune';
import { MobileWebCamera } from '../src/components/MobileWebApp';
import type { BrowserRtcStats } from '../src/lib/mobileBrowserRtc';
import '../src/tinkro.css';
import './phone-tuning-preview.css';

function Preview() {
  const { setLocale } = useI18n();
  const [stream, setStream] = useState<MediaStream | null>(null), [scene, setScene] = useState('normal');
  const [load, setLoad] = useState('bandwidth'), [cap, setCap] = useState(12000), [restarts, setRestarts] = useState(0);
  const [clock, setClock] = useState(Date.now()), [hiddenCamera, setHiddenCamera] = useState(false), [unsupported, setUnsupported] = useState(false);
  const [theme, setTheme] = useState('dark');
  const capRef = useRef(cap), sceneRef = useRef(scene), currentStream = useRef(stream), dimensions = useRef([1080, 1920]);
  sceneRef.current = scene; currentStream.current = stream;
  useEffect(() => { setLocale('zh-TW'); }, []);
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  useEffect(() => {
    const canvas = document.createElement('canvas'); canvas.width = dimensions.current[0]; canvas.height = dimensions.current[1];
    const ctx = canvas.getContext('2d')!;
    const draw = () => {
      if (sceneRef.current !== 'normal') { ctx.fillStyle = sceneRef.current === 'dark' ? '#080808' : '#ffffff'; ctx.fillRect(0, 0, canvas.width, canvas.height); return; }
      ctx.fillStyle = '#b6bdc3'; ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = '#30735d'; ctx.fillRect(120, 250, 520, 1000);
      for (let y = 300; y < 1170; y += 38) { ctx.fillStyle = y % 3 ? '#d0b043' : '#282b31'; ctx.fillRect(560, y, 32, 15); }
      ctx.fillStyle = '#1e6887'; ctx.fillRect(740, 370, 220, 400);
      ctx.fillStyle = '#eeeeee'; ctx.fillRect(190, 410, 230, 270);
      ctx.fillStyle = '#202834'; ctx.fillRect(290, 900, 180, 180);
      ctx.fillStyle = '#162638'; ctx.fillRect(170, 1390, 740, 280);
      ctx.fillStyle = '#ffffff'; ctx.font = 'bold 52px sans-serif'; ctx.fillText('SYNTHETIC ONLY', 200, 1500);
      ctx.font = '32px sans-serif'; ctx.fillText('Not GPIO evidence', 235, 1580);
    };
    draw(); const media = canvas.captureStream(30); setStream(media);
    const timer = setInterval(draw, 33); return () => { clearInterval(timer); media.getTracks().forEach(track => track.stop()); };
  }, [restarts]);
  useEffect(() => { const timer = setInterval(() => setClock(Date.now()), 500); return () => clearInterval(timer); }, []);
  const stats: BrowserRtcStats = { measuredAtMs: load === 'stale' ? 1 : Math.floor(clock / 1000) * 1000,
    sampleIntervalMs: 1000, sendFps: load === 'normal' ? 30 : 15, qualityLimitationReason: load === 'stale' ? 'bandwidth' : load,
    width: dimensions.current[0], height: dimensions.current[1], appliedBitrateKbps: cap, parameterStatus: unsupported ? 'unsupported' : 'applied' };
  const cameraTune = usePhoneCameraTune({ stream, scope: `fixture:${restarts}`, busy: false, stats,
    readBitrate: () => unsupported ? null : capRef.current,
    adjustBitrate: async (expected, value, signal) => {
      if (expected !== currentStream.current || signal?.aborted) throw Error('phone_tune_source_changed');
      capRef.current = value; setCap(value); return value;
    } });
  const workspace = { ready: true, secureContext: true, busy: cameraTune.busy, connected: true, canCapture: !cameraTune.busy,
    previewFresh: true, cameraTune, captureTicket: null, captureJob: null,
    session: { session_id: 'fixture', context_id: 'fixture-project', conversation_id: 'none', stream: { active: true, state: 'locked',
      video_received_at: clock / 1000, video_receive_fresh: true, video_fps: 30, recognition_fps: 3 } },
    rtc: { stream, publishing: true, stats, status: 'Synthetic preview only', frame: { sourceSize: dimensions.current, outputSize: dimensions.current } },
    startStream: async (options: { resolution: string; bitrateKbps: number }) => {
      dimensions.current = options.resolution === '720p' ? [720, 1280] : [1080, 1920]; capRef.current = options.bitrateKbps; setCap(options.bitrateKbps); setRestarts(n => n + 1);
    }, stopStream: async () => { stream?.getTracks().forEach(track => track.stop()); setStream(null); },
  } as unknown as Parameters<typeof MobileWebCamera>[0]['w'];
  return <>
    <aside className="qa-controls"><strong>ISOLATED QA · 合成串流，非 Safari 實機</strong>
      <label>Scene<select aria-label="Fixture scene" value={scene} onChange={e => setScene(e.target.value)}><option value="normal">Normal</option><option value="dark">Dark</option><option value="glare">Glare</option></select></label>
      <label>Load<select aria-label="Fixture load" value={load} onChange={e => setLoad(e.target.value)}><option value="bandwidth">Bandwidth limited</option><option value="cpu">CPU limited</option><option value="normal">Normal</option><option value="stale">Stale reports</option></select></label>
      <label><input type="checkbox" checked={unsupported} onChange={e => setUnsupported(e.target.checked)} /> No cap support</label>
      <button onClick={() => setHiddenCamera(v => !v)}>{hiddenCamera ? 'Show camera page' : 'Leave camera page'}</button>
      <button onClick={() => setTheme(v => v === 'dark' ? 'light' : 'dark')}>Toggle theme</button>
      <button onClick={() => setLocale('en')}>English</button>
      <output aria-label="Fixture monitor">Cap: {cap / 1000} Mbps · Explicit restarts: {restarts} · Real camera acquisitions: 0</output>
    </aside>
    <div className="mobile-web-app qa-phone" data-tab="camera"><header className="mw-header"><strong>Tinkro · 手機智慧調整</strong></header>
      <main className="mw-main">{hiddenCamera ? <p>Fixture tab changed; stream owner stays mounted.</p> : <MobileWebCamera w={workspace} onCaptured={() => {}} />}</main>
    </div>
  </>;
}
createRoot(document.getElementById('root')!).render(<LocaleProvider><Preview /></LocaleProvider>);
