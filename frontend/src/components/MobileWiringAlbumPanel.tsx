import { useEffect, useState } from 'react';
import { wiringPhotoRoles, type WiringPhotoRole } from '../lib/wiringReview';
import type { MobileWiringAlbum } from '../lib/useMobileWiringAlbum';

type Translate = (zh: string, en: string) => string;
const roleLabel = (role: WiringPhotoRole, tr: Translate) => role === 'pi_side_a' ? tr('Pi 第一側', 'Pi first side')
  : role === 'pi_side_b' ? tr('Pi 另一側', 'Pi other side') : tr('零件接頭', 'Module header');
function AlbumImage({ file }: { file: File }) {
  const [preview, setPreview] = useState<{ file: File; url: string } | null>(null);
  useEffect(() => {
    const url = URL.createObjectURL(file); setPreview({ file, url });
    return () => URL.revokeObjectURL(url);
  }, [file]);
  return preview?.file === file ? <img src={preview.url} alt={file.name} /> : null;
}
export function MobileWiringAlbumPanel({ album, role, disabled, onUse, tr }: {
  album: MobileWiringAlbum; role: WiringPhotoRole; disabled: boolean; onUse: () => void; tr: Translate;
}) {
  const selection = album.selection;
  if (!selection) return null;
  const available = selection.photos.some(photo => photo.role === role && !photo.sent);
  return <section className="mw-wiring-album" aria-label={tr('待送相簿照片', 'Queued album photos')}>
    <header><strong>{tr('已選照片，逐張送出', 'Selected photos, sent one at a time')}</strong>
      <button type="button" className="mw-quiet" disabled={disabled} onClick={album.clear}>{tr('清除', 'Clear')}</button></header>
    <div className="mw-wiring-album-grid">{selection.photos.map((photo, index) => <label key={index} className={photo.sent ? 'is-sent' : ''}>
      <AlbumImage file={photo.file} />
      <select aria-label={tr(`第 ${index + 1} 張照片的角度`, `View for photo ${index + 1}`)} value={photo.role} disabled={disabled || photo.sent}
        onChange={event => album.assign(index, event.target.value as WiringPhotoRole)}>
        {wiringPhotoRoles.map(option => <option key={option} value={option} disabled={selection.photos.some(other => other.role === option && other.sent)}>{roleLabel(option, tr)}</option>)}
      </select><small>{photo.sent ? tr('已送出', 'Sent') : tr('待送出', 'Not sent')}</small>
    </label>)}</div>
    <label className="mw-wiring-album-confirm"><input type="checkbox" checked={selection.confirmed} disabled={disabled}
      onChange={event => album.confirm(event.target.checked)} />{tr('角度正確，拍攝後接線未更動', 'Views are correct and the wiring is unchanged')}</label>
    <button type="button" className="mw-button mw-primary" disabled={disabled || !selection.confirmed || !available} onClick={onUse}>
      {tr(`送出${roleLabel(role, tr)}照片`, `Send ${roleLabel(role, tr)} photo`)}</button>
    <small>{tr('只送目前要求的這一張；收到下一題後再送下一張。', 'Only this requested view is sent. Send the next photo after the next question arrives.')}</small>
  </section>;
}
