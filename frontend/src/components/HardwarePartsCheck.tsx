import { useId, useState } from 'react';
import { useMakerText } from '../lib/useMaker';
import { useI18n } from '../lib/i18n';
import { demoHardware, emptyPurchasedHardware, hardwarePartsCheckPrompt } from '../lib/hardwarePartsCheck';
import { usePhoneUploadEntry } from '../lib/headerPanels';

export function HardwarePartsCheck({ onAsk, disabledReason, photoLabel, photoKey, onOpenAI, projectScope }: {
  onAsk?: (prompt: string, includePhoto: boolean) => Promise<boolean>;
  disabledReason?: string; photoLabel?: string; photoKey?: string; onOpenAI?: () => void;
  projectScope?: string;
}) {
  const tr = useMakerText();
  const { locale } = useI18n();
  const phoneUpload = usePhoneUploadEntry();
  const id = useId();
  const [purchased, setPurchased] = useState(emptyPurchasedHardware);
  const [selectedPhoto, setSelectedPhoto] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [status, setStatus] = useState('');
  const includePhoto = Boolean(photoKey && photoLabel && selectedPhoto === photoKey);
  const ready = demoHardware.some(key => purchased[key].trim()) || includePhoto;
  const parts = [
    { name: 'Raspberry Pi 5', kind: tr('控制板', 'Controller'), hint: tr('填寫板上型號或商品名稱', 'Board model or product name') },
    { name: 'HC-SR04+ · 3.3V', kind: tr('超音波感測器', 'Ultrasonic sensor'), hint: tr('型號、供電與 ECHO 規格', 'Model and voltage'), detail: tr('請填寫供電與 ECHO 規格；外觀相似不代表同版本。', 'Include supply voltage and ECHO rating. Similar appearance does not mean the same variant.') },
    { name: 'MRD_TFT240_8P_CS · ILI9341', kind: tr('TFT 螢幕', 'TFT display'), hint: tr('填寫型號、控制晶片或腳位數量', 'Model, controller or pin count') },
  ];
  async function ask() {
    if (!onAsk || !ready || pending || disabledReason) return;
    setPending(true); setStatus('');
    try {
      const accepted = await onAsk(hardwarePartsCheckPrompt(purchased, locale, includePhoto), includePhoto);
      setStatus(accepted ? tr('已送出，請在 AI 對話查看核對結果。', 'Sent. Read the comparison in the AI conversation.')
        : tr('尚未送出，請查看 AI 對話中的提示後重試。', 'Not sent. Check the AI conversation and retry.'));
    } catch {
      setStatus(tr('送出失敗，資料已保留，可以重試。', 'Could not send. Your details are kept for retry.'));
    } finally { setPending(false); }
  }
  return <div className="blueprint-hardware-check">
    <header><span className="maker-eyebrow">DEMO · {tr('3 項硬體', '3 hardware items')}</span>
      <h3>{tr('先確認，買的是同一款', 'Check that you bought the same hardware')}</h3>
      <p className="maker-muted">{tr('拍下零件標籤，或填寫型號。', 'Photograph the labels, or enter the models.')}</p></header>
    <div className="blueprint-upload-entry"><span className="blueprint-upload-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><rect x="7" y="2" width="10" height="20" rx="3" /><path d="M10 18h4M12 14V6m-3 3 3-3 3 3" /></svg></span>
      <div><strong>{tr('用手機拍照核對', 'Check parts from your phone')}</strong><small>{tr('掃碼開啟 → 選「拍照核對」或「相簿核對」→ 送出', 'Scan → choose Photograph parts or Select part photos → send')}</small></div>
      <button type="button" disabled={!phoneUpload.open} onClick={() => phoneUpload.open?.(projectScope)}>{tr('開啟手機', 'Connect phone')} <span aria-hidden="true">↗</span></button></div>
    <ol className="blueprint-hardware-list">{demoHardware.map((key, index) => <li key={key}>
      <span className="blueprint-hardware-number" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
      <div className="blueprint-hardware-info"><span>{parts[index].kind}</span><strong>{parts[index].name}</strong>
        <label htmlFor={`${id}-${key}`}>{tr('我買的零件', 'My purchased part')}</label>
        <input id={`${id}-${key}`} value={purchased[key]} maxLength={600} placeholder={parts[index].hint}
          aria-describedby={parts[index].detail ? `${id}-${key}-hint` : undefined}
          onChange={event => { setPurchased(value => ({ ...value, [key]: event.target.value })); setStatus(''); }} />
        {parts[index].detail ? <small id={`${id}-${key}-hint`} className="blueprint-hardware-hint">{parts[index].detail}</small> : null}
      </div>
    </li>)}</ol>
    {photoLabel ? <label className="blueprint-photo-choice"><input type="checkbox" checked={includePhoto}
      onChange={event => { setSelectedPhoto(event.target.checked ? photoKey ?? null : null); setStatus(''); }} />
      <span>{tr('一併核對目前對話照片', 'Include the current conversation photo')}<small>{photoLabel}</small></span></label> :
      <p className="maker-muted">{tr('手機可直接送出零件核對；也可在這裡填型號核對。', 'Compare directly from your phone, or enter the models here.')}</p>}
    <footer><div><small>{tr('只比對這三項；不會修改作品或標記接線完成。', 'Only compares these three items; does not change the project or confirm wiring.')}</small>
      {disabledReason ? <p role="status">{disabledReason}</p> : null}</div>
      <button type="button" className="maker-primary" disabled={!onAsk || !ready || pending || Boolean(disabledReason)} onClick={() => void ask()}>
        {pending ? tr('正在送出…', 'Sending…') : tr('請 AI 核對 →', 'Ask AI to compare →')}</button>
      <button type="button" className="blueprint-chat-link" onClick={onOpenAI}>{tr('查看 AI 對話', 'Open AI conversation')}</button></footer>
    {status ? <p className="blueprint-check-status" role="status">{status}</p> : null}
  </div>;
}
