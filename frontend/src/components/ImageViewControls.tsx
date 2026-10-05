import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useMakerText } from '../lib/useMaker';
import './ImageViewControls.css';

export type ImageViewMode = 'live' | 'diagram' | 'photo';
export type ImageSource = 'webcam' | 'phone';

/** Viewing a reference does not acquire a camera or change the selected source. */
export function ImageViewControls({ view, disabled, photoDisabled = false, diagramAvailable, onChange }: {
  view: ImageViewMode; disabled: boolean; photoDisabled?: boolean; diagramAvailable: boolean;
  onChange: (view: ImageViewMode) => void;
}) {
  const tr = useMakerText();
  const views: Array<{ id: ImageViewMode; label: string; hint: string }> = [
    { id: 'live', label: tr('即時畫面', 'Live view'), hint: tr('查看目前來源的即時影像與辨識', 'Live image and recognition from the selected source') },
    { id: 'diagram', label: tr('接線圖', 'Wiring diagram'), hint: tr('查看這一步的預期接法', 'Intended wiring for this step') },
    { id: 'photo', label: tr('接線照片', 'Wiring photo'), hint: tr('查看拍攝當下的接線與 GPIO 標示', 'Captured wiring with GPIO markers') },
  ];
  return <div className="image-view-controls">
    <div className="image-view-segments" role="group" aria-label={tr('畫面檢視', 'View mode')}>
      {views.map(item => <button type="button" key={item.id} aria-pressed={view === item.id}
        title={item.hint} disabled={disabled || (item.id === 'diagram' && !diagramAvailable) || (item.id === 'photo' && photoDisabled)}
        onClick={() => onChange(item.id)}>{item.label}</button>)}
    </div>
  </div>;
}

function ImageSourceIcon({ source }: { source: ImageSource }) {
  return <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {source === 'phone' ? <><rect x="6" y="2" width="12" height="20" rx="3"/><path d="M10 18h4"/></>
      : <><rect x="3" y="4" width="18" height="13" rx="4"/><circle cx="12" cy="10.5" r="3"/><path d="M12 17v4m-4 0h8"/></>}
  </svg>;
}

export function ImageSourceSelect({ source, disabled, phoneConnected, onSelect, onConnect }: {
  source: ImageSource; disabled: boolean; phoneConnected: boolean;
  onSelect: (source: ImageSource) => void; onConnect: () => void;
}) {
  const tr = useMakerText();
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ left: 0, top: 0 });
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const options = useRef<Array<HTMLButtonElement | null>>([]);
  const initialFocus = useRef(0);
  const menuId = useId();
  const expanded = open && !disabled;
  const entries: Array<{ id: ImageSource; label: string; hint: string }> = [
    { id: 'webcam', label: 'Webcam', hint: tr('電腦鏡頭', 'Computer camera') },
    { id: 'phone', label: tr('手機串流', 'Phone stream'), hint: phoneConnected
      ? tr('手機即時影像', 'Live phone video') : tr('連接手機', 'Connect your phone') },
  ];
  useEffect(() => { setOpen(false); }, [disabled, source]);
  useEffect(() => {
    const closeMenu = () => setOpen(false);
    document.addEventListener('fullscreenchange', closeMenu);
    return () => document.removeEventListener('fullscreenchange', closeMenu);
  }, []);
  // Portal avoids clipping by the resizable video shell. It has no camera lifecycle.
  useLayoutEffect(() => {
    if (!expanded) return;
    const place = () => {
      const anchor = trigger.current?.getBoundingClientRect();
      const panel = menu.current;
      if (!anchor || !panel || !trigger.current?.getClientRects().length) { setOpen(false); return; }
      const gap = 8, edge = 12;
      const left = Math.max(edge, Math.min(anchor.right - panel.offsetWidth, window.innerWidth - panel.offsetWidth - edge));
      const below = anchor.bottom + gap;
      const top = below + panel.offsetHeight <= window.innerHeight - edge ? below : Math.max(edge, anchor.top - panel.offsetHeight - gap);
      setPosition(previous => previous.left === left && previous.top === top ? previous : { left, top });
    };
    place();
    options.current[initialFocus.current]?.focus({ preventScroll: true });
    const resize = new ResizeObserver(place);
    if (trigger.current) resize.observe(trigger.current);
    if (menu.current) resize.observe(menu.current);
    window.addEventListener('resize', place);
    window.addEventListener('scroll', place, true);
    return () => { resize.disconnect(); window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true); };
  }, [expanded]);
  useEffect(() => {
    if (!expanded) return;
    const outside = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!trigger.current?.contains(target) && !menu.current?.contains(target)) setOpen(false);
    };
    document.addEventListener('pointerdown', outside, true);
    return () => document.removeEventListener('pointerdown', outside, true);
  }, [expanded]);
  const show = (index = source === 'phone' ? 1 : 0) => {
    if (!disabled) { initialFocus.current = index; setOpen(true); }
  };
  const close = () => { setOpen(false); trigger.current?.focus({ preventScroll: true }); };
  const choose = (next: ImageSource) => {
    if (disabled) return;
    close();
    if (next === 'phone' && !phoneConnected) onConnect();
    else if (next !== source) onSelect(next);
  };
  return <div className="image-source-select">
    <button ref={trigger} className="image-source-trigger" type="button" disabled={disabled}
      aria-label={`${tr('影像來源', 'Image source')}：${source === 'phone' ? tr('手機串流', 'Phone stream') : 'Webcam'}`}
      aria-haspopup="menu" aria-expanded={expanded} aria-controls={expanded ? menuId : undefined}
      title={tr('切換影像來源', 'Switch image source')}
      onClick={() => expanded ? close() : show()}
      onKeyDown={event => {
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          event.preventDefault(); show(event.key === 'ArrowDown' ? 0 : 1);
        }
      }}>
      <ImageSourceIcon source={source} /><span>{source === 'phone' ? tr('手機串流', 'Phone stream') : 'Webcam'}</span>
      <svg className="image-source-chevron" viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="m4 6 4 4 4-4"/></svg>
    </button>
    {expanded ? createPortal(<div ref={menu} id={menuId} className="image-source-menu" role="menu"
      aria-label={tr('影像來源', 'Image source')} style={position}
      onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget) && !trigger.current?.contains(event.relatedTarget)) setOpen(false); }}
      onKeyDown={event => {
        const current = options.current.indexOf(document.activeElement as HTMLButtonElement);
        const next = event.key === 'ArrowDown' ? (current + 1) % entries.length
          : event.key === 'ArrowUp' ? (current + entries.length - 1) % entries.length
          : event.key === 'Home' ? 0 : event.key === 'End' ? entries.length - 1 : -1;
        if (next >= 0) { event.preventDefault(); options.current[next]?.focus(); }
        if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); }
        // Move Tab's starting point back to the trigger before the portal closes.
        if (event.key === 'Tab') close();
      }}>
      <div className="image-source-menu-heading" aria-hidden="true">{tr('影像來源', 'IMAGE SOURCE')}</div>
      {entries.map((item, index) => <button ref={node => { options.current[index] = node; }} key={item.id}
        type="button" className="image-source-option" role="menuitemradio" aria-checked={source === item.id}
        disabled={disabled} tabIndex={-1} onClick={() => choose(item.id)}>
        <span className="image-source-option-icon"><ImageSourceIcon source={item.id} /></span>
        <span className="image-source-option-copy"><strong>{item.label}</strong><small>{item.hint}</small></span>
        {source === item.id ? <svg className="image-source-check" viewBox="0 0 20 20" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m5 10 3 3 7-7"/></svg> : null}
      </button>)}
    </div>, document.fullscreenElement ?? document.body) : null}
  </div>;
}
