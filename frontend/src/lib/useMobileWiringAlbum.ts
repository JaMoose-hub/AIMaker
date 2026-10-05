import { useEffect, useRef, useState } from 'react';
import { wiringPhotoRoles, type WiringPhotoRole, type WiringReviewState } from './wiringReview';
import type { MobileWiringPhotoRequest } from './useMobileBrowser';

export interface WiringAlbumContext {
  contextId?: string; conversationId?: string; epoch?: number; review?: WiringReviewState | null;
}
export interface WiringAlbumPhoto { file: File; role: WiringPhotoRole; sent: boolean }
interface Selection { key: string; photos: WiringAlbumPhoto[]; confirmed: boolean }
export function wiringAlbumKey(context: WiringAlbumContext): string | null {
  return context.contextId && context.conversationId && context.epoch !== undefined && context.review
    ? JSON.stringify([context.contextId, context.conversationId, context.epoch, context.review.id, context.review.round, context.review.component_id]) : null;
}
const requestKey = (request: MobileWiringPhotoRequest) => wiringAlbumKey({ ...request, review: request.review });

/** Files stay on the phone. Each upload still needs a fresh, exact server question. */
export function useMobileWiringAlbum(context: WiringAlbumContext) {
  const [selection, setSelection] = useState<Selection | null>(null);
  const key = wiringAlbumKey(context);
  const live = useRef({ key, selection });
  live.current = { key, selection };
  useEffect(() => { setSelection(previous => previous?.key === key ? previous : null); }, [key]);
  const current = selection?.key === key ? selection : null;
  return {
    selection: current,
    stage(files: File[], request: MobileWiringPhotoRequest) {
      const target = requestKey(request);
      if (!target || target !== live.current.key || files.length < 2 || files.length > 3) return false;
      const roles = files.length === 3 ? wiringPhotoRoles : [request.role, ...wiringPhotoRoles.filter(role => role !== request.role)];
      const next = { key: target, confirmed: false, photos: files.map((file, index) => ({ file, role: roles[index], sent: false })) };
      live.current.selection = next; setSelection(next); return true;
    },
    assign(index: number, role: WiringPhotoRole) {
      setSelection(previous => {
        if (!previous || previous.key !== live.current.key || !wiringPhotoRoles.includes(role) || !previous.photos[index] || previous.photos[index].sent) return previous;
        const other = previous.photos.findIndex(photo => photo.role === role);
        if (other >= 0 && previous.photos[other].sent) return previous;
        const oldRole = previous.photos[index].role;
        return { ...previous, confirmed: false, photos: previous.photos.map((photo, position) => ({ ...photo,
          role: position === index ? role : position === other ? oldRole : photo.role })) };
      });
    },
    confirm(value: boolean) { setSelection(previous => previous?.key === live.current.key ? { ...previous, confirmed: value } : previous); },
    fileFor(request: MobileWiringPhotoRequest) {
      const value = live.current.selection;
      return value && value.confirmed && value.key === live.current.key && value.key === requestKey(request)
        ? value.photos.find(photo => photo.role === request.role && !photo.sent)?.file ?? null : null;
    },
    submitted(request: MobileWiringPhotoRequest) {
      const target = requestKey(request);
      setSelection(previous => previous && previous.key === target && target === live.current.key
        ? { ...previous, photos: previous.photos.map(photo => photo.role === request.role ? { ...photo, sent: true } : photo) } : previous);
    },
    clear() { live.current.selection = null; setSelection(null); },
  };
}
export type MobileWiringAlbum = ReturnType<typeof useMobileWiringAlbum>;
