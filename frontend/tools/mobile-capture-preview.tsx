// Actual phone UI and lifecycle hook, with a browser-native synthetic video track.
import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { LocaleProvider } from '../src/lib/i18n';
import { useMobileBrowser } from '../src/lib/useMobileBrowser';
import { MobileWebSurface } from '../src/components/MobileWebApp';
import '../src/styles.css';
import '../src/tinkro.css';

const fixture = (window as unknown as { __MOBILE_CAPTURE_FIXTURE__: object }).__MOBILE_CAPTURE_FIXTURE__;
localStorage.setItem('tinkro.browser.pairing.v1', JSON.stringify(fixture));
const query = new URLSearchParams(location.search);
localStorage.setItem('boardvision.locale.v1', query.get('lang') ?? 'zh-TW');
document.documentElement.dataset.theme = query.get('theme') ?? 'dark';
const portrait = query.has('portrait');
const small = query.has('small');
const orientation = Object.assign(new EventTarget(), { type: portrait ? 'portrait-primary' : 'landscape-primary', angle: portrait ? 0 : 90 });
Object.defineProperty(screen, 'orientation', { configurable:true, value:orientation });
(window as unknown as { __setPhoneOrientation: (landscape: boolean) => void }).__setPhoneOrientation = landscape => {
  orientation.type = landscape ? 'landscape-primary' : 'portrait-primary'; orientation.angle = landscape ? 90 : 0;
  orientation.dispatchEvent(new Event('change'));
};
const counters = { getUserMedia: 0, trackStops: 0, peerCloses: 0, paintFrames: 0,
  actual_size: portrait ? [1080, 1920] : small ? [1280, 720] : [1920, 1080], output_size: null as null | number[], canvasCapture: null as null | { width: number; height: number; type?: string; quality?: number } };
(window as unknown as { __mobileCaptureQa: typeof counters }).__mobileCaptureQa = counters;
const publishCounters = () => { void fetch('/__fixture/metrics', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(counters) }); };
const originalBlob = HTMLCanvasElement.prototype.toBlob;
HTMLCanvasElement.prototype.toBlob = function(callback, type, quality) {
  if (type === 'image/jpeg') { counters.canvasCapture = { width: this.width, height: this.height, type, quality }; publishCounters(); }
  return originalBlob.call(this, callback, type, quality);
};

Object.defineProperty(navigator.mediaDevices, 'getUserMedia', { configurable: true, value: async (constraints: MediaStreamConstraints) => {
  counters.getUserMedia++;
  const video = typeof constraints.video === 'object' ? constraints.video : {};
  const ideal = (value: ConstrainULong | undefined, fallback: number) => typeof value === 'number' ? value : value?.exact ?? value?.ideal ?? fallback;
  const width = ideal(video.width, 1920), height = ideal(video.height, 1080);
  counters.actual_size = small ? width < height ? [720, 1280] : [1280, 720] : [width, height];
  const canvas = document.createElement('canvas');
  [canvas.width, canvas.height] = counters.actual_size;
  const ctx = canvas.getContext('2d')!;
  (window as unknown as { __rotateCamera: () => void }).__rotateCamera = () => {
    [canvas.width, canvas.height] = [canvas.height, canvas.width]; counters.actual_size = [canvas.width, canvas.height]; publishCounters();
  };
  const draw = () => {
    const w = canvas.width, h = canvas.height;
    counters.paintFrames++;
    ctx.fillStyle = '#d4e4e9'; ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = '#a4bdc6'; ctx.lineWidth = 2;
    for (let x = 0; x < w; x += 80) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); }
    for (let y = 0; y < h; y += 80) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }
    ctx.fillStyle = '#337c59'; ctx.fillRect(.08*w, .18*h, .46*w, .5*h);
    ctx.fillStyle = '#377bc2'; ctx.fillRect(.64*w, .3*h, .3*w, .3*h);
    ctx.fillStyle = '#fff'; ctx.font = `${Math.round(w*.025)}px sans-serif`;
    ctx.fillText('Synthetic Pi 5', .1*w, .35*h); ctx.fillText('HC-SR04', .66*w, .4*h);
    ctx.fillStyle = '#142e3d'; ctx.font = `${Math.round(w*.015)}px monospace`;
    ctx.fillText(`Synthetic video frame ${counters.paintFrames} | ${w} x ${h}`, .04*w, .92*h);
    ctx.fillText('No camera / model / physical GPIO evidence', .04*w, .97*h);
    ctx.fillStyle = '#fff4ad';
    for (const [x, y] of [[.19,.62],[.31,.62],[.71,.55],[.85,.55]]) { ctx.beginPath(); ctx.arc(x*w,y*h,w*.007,0,Math.PI*2); ctx.fill(); }
    ctx.fillStyle = '#f29632'; ctx.fillRect(.03*w + counters.paintFrames%100*3, .07*h, .03*w, .03*h);
    // Fixed corner markers allow QA to prove pixel rotation, not merely dimensions.
    for (const [color,x,y] of [['#ff0000',0,0],['#00ff00',w-80,0],['#0000ff',w-80,h-80],['#ffff00',0,h-80]] as const) {
      ctx.fillStyle = color; ctx.fillRect(x,y,80,80);
    }
  };
  draw(); const timer = setInterval(draw, 1000/30), stream = canvas.captureStream(30);
  const track = stream.getVideoTracks()[0], nativeStop = track.stop.bind(track);
  track.stop = () => { counters.trackStops++; clearInterval(timer); nativeStop(); publishCounters(); };
  publishCounters(); return stream;
} });

class FixtureEvents {
  static OPEN = 1; static CONNECTING = 0; static CLOSED = 3;
  readyState = 1;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(_url: string) { void this.tick(); }
  private closed = false;
  timer = setInterval(() => void this.tick(), 200);
  async tick() {
    const value = await fetch('/__fixture/events').then(r => r.json());
    if (!this.closed) this.onmessage?.({ data: JSON.stringify(value) });
  }
  close() { this.closed = true; this.readyState = 3; clearInterval(this.timer); this.onclose?.(); }
}
window.WebSocket = FixtureEvents as unknown as typeof WebSocket;
class FixturePeer {
  connectionState = 'new'; iceGatheringState = 'complete'; localDescription: RTCSessionDescriptionInit | null = null;
  onconnectionstatechange: (() => void) | null = null; onicegatheringstatechange = null;
  begun = performance.now(); track: MediaStreamTrack | null = null; parameters = { encodings: [{}] };
  sender = { track: null as MediaStreamTrack | null, getParameters: () => structuredClone(this.parameters),
    setParameters: async (value: typeof this.parameters) => { this.parameters = value; } };
  addTrack(track: MediaStreamTrack) { this.track = this.sender.track = track; const settings=track.getSettings(); counters.output_size=[settings.width!,settings.height!]; publishCounters(); return this.sender; }
  getTransceivers() { return [{ sender: this.sender, receiver: { track: this.track }, setCodecPreferences() {} }]; }
  async createOffer() { return { type: 'offer' as const, sdp: 'isolated-no-network' }; }
  async setLocalDescription(value: RTCSessionDescriptionInit) { this.localDescription = value; }
  async setRemoteDescription() { this.connectionState = 'connected'; this.onconnectionstatechange?.(); }
  async getStats() {
    const seconds = (performance.now()-this.begun)/1000, {width,height} = this.track?.getSettings() ?? {};
    return new Map<string, unknown>([
      ['source', { type: 'media-source', kind: 'video', framesPerSecond: 30 }],
      ['codec', { type: 'codec', mimeType: 'video/H264' }],
      ['transport', { type: 'transport', selectedCandidatePairId: 'pair' }],
      ['pair', { type: 'candidate-pair', state: 'succeeded', currentRoundTripTime: .008 }],
      ['video', { id: 'synthetic-outbound', type: 'outbound-rtp', kind: 'video', ssrc: 42, timestamp: performance.now(),
        framesSent: Math.floor(seconds*30), bytesSent: Math.floor(seconds*1000000), totalEncodeTime: seconds*.12,
        frameWidth: width, frameHeight: height, qualityLimitationReason: 'none', codecId: 'codec', transportId: 'transport' }],
    ]);
  }
  close() { this.connectionState = 'closed'; counters.peerCloses++; publishCounters(); }
}
window.RTCPeerConnection = FixturePeer as unknown as typeof RTCPeerConnection;

function Preview() {
  const workspace = useMobileBrowser();
  const [stats, setStats] = useState(counters);
  useEffect(() => { const timer = setInterval(() => { setStats({ ...counters }); publishCounters(); }, 750); return () => clearInterval(timer); }, []);
  return <>
    <style>{'.mobile-web-app { top:60px; height:calc(100dvh - 60px); }'}</style>
    <aside style={{ position: 'fixed', zIndex: 10000, top: 0, left: 0, right: 0, background: '#173042', color: '#fff', font: '11px monospace', padding: 6 }}>
      Synthetic QA · no hardware / AI · getUserMedia {stats.getUserMedia} · track.stop {stats.trackStops} · generation {workspace.session?.stream.generation ?? 0}
      <button type="button" style={{ display: 'block', marginTop: 3, minHeight: 24 }} onClick={() => {
        const next = orientation.type.startsWith('portrait');
        (window as unknown as { __setPhoneOrientation: (horizontal: boolean) => void }).__setPhoneOrientation(next);
      }}>切換橫直方向</button>
    </aside>
    <MobileWebSurface workspace={workspace} />
  </>;
}
createRoot(document.getElementById('root')!).render(<LocaleProvider><Preview /></LocaleProvider>);
