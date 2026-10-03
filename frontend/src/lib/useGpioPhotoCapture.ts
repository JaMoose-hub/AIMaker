import { useEffect, useRef, useState } from 'react';
import type { ProjectDesign } from './maker';
import { GpioPhotoCapture, photoRecordCurrent, type GpioPhotoRecord, type GpioCaptureSource } from './gpioPhotoWorkspace';

interface CaptureContext {
    project: ProjectDesign | null;
    round: number;
    source: GpioCaptureSource;
    active: boolean;
    allowed: boolean;
}

/** Own the camera lease above both live and photo views, so switching views never interrupts release. */
export function useGpioPhotoCapture(context: CaptureContext, onPhoto: (record: GpioPhotoRecord, show: boolean) => void) {
    const [owner] = useState(() => new GpioPhotoCapture());
    const [busy, setBusy] = useState(false);
    const [needsResume, setNeedsResume] = useState(false);
    const [error, setError] = useState<'capture' | 'source' | null>(null);
    const flight = useRef(false);
    const mounted = useRef(true);
    const latest = useRef({ context, onPhoto });
    latest.current = { context, onPhoto };
    useEffect(() => {
        mounted.current = true;
        return () => { mounted.current = false; };
    }, []);

    async function capture() {
        const start = latest.current.context;
        const project = start.project;
        if (flight.current || owner.needsResume || !start.allowed || !start.active || !project) return;
        let accepted = false;
        flight.current = true;
        setBusy(true); setError(null);
        try {
            await owner.capture(project, photo => {
                accepted = true;
                if (!mounted.current) return;
                const record: GpioPhotoRecord = { source: start.source.kind, projectId: project.id,
                    revision: project.revision, round: start.round, capture: photo };
                const now = latest.current.context;
                // Keep the original ownership, but never navigate a different project/source to a late result.
                const show = now.active && photoRecordCurrent(record, now.project, now.round)
                    && now.source.kind === start.source.kind && now.source.runtimeRevision === start.source.runtimeRevision;
                latest.current.onPhoto(record, show);
            }, start.source);
        } catch (cause) {
            if (mounted.current && !accepted)
                setError(cause instanceof Error && cause.message === 'photo_source_changed' ? 'source' : 'capture');
        } finally {
            flight.current = false;
            if (mounted.current) { setBusy(false); setNeedsResume(owner.needsResume); }
        }
    }

    async function resume() {
        if (flight.current || !owner.needsResume) return;
        flight.current = true; setBusy(true);
        try { await owner.resume(); }
        catch { /* The recovery action remains visible; no new session is acquired. */ }
        finally {
            flight.current = false;
            if (mounted.current) { setBusy(false); setNeedsResume(owner.needsResume); }
        }
    }

    return { busy, needsResume, error, capture, resume };
}
