/** One full-size local video frame. Does not acquire, stop, or replace a camera. */
export async function captureBrowserVideoFrame(video: HTMLVideoElement, stream: MediaStream): Promise<File> {
    const live = () => video.srcObject === stream && stream.getVideoTracks().some(track => track.readyState === 'live');
    const width = video.videoWidth, height = video.videoHeight;
    if (!live() || video.readyState < 2 || video.paused || width < 1 || height < 1)
        throw Error('手機串流尚未就緒，請保持串流後再拍照。');
    const canvas = video.ownerDocument.createElement('canvas');
    canvas.width = width; canvas.height = height;
    try {
        const context = canvas.getContext('2d');
        if (!context) throw Error('無法擷取手機影像，請重試。');
        context.drawImage(video, 0, 0, width, height);
        const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, 'image/jpeg', .95));
        if (!blob) throw Error('手機影像保存失敗，串流仍持續，請重試。');
        if (!live() || video.videoWidth !== width || video.videoHeight !== height)
            throw Error('串流來源或方向已改變，請重試拍照。');
        return new File([blob], `tinkro-phone-frame-${Date.now()}.jpg`, { type: blob.type || 'image/jpeg' });
    } finally {
        canvas.width = canvas.height = 0;
    }
}
