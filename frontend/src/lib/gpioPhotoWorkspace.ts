import { acceptPhotoCapture, acceptPhotoPlan, photoPlanForProject, photoWiringRequest, type PhotoCapture, type PhotoWire } from './photoWiring';
import type { ProjectDesign, ProjectWire } from './maker';

export type GpioView = 'webcam' | 'phone' | 'photo';
export interface GpioPhotoRecord {
    source: 'webcam' | 'phone';
    projectId: string;
    revision: number;
    round: number;
    capture: PhotoCapture;
}
export function photoRecordCurrent(record: GpioPhotoRecord, project: ProjectDesign | null, round: number) {
    return !!project && record.projectId === project.id && record.revision === project.revision && record.round === round;
}
/** Never substitute another wire when the guide's target is absent from this photo. */
export function photoGuideWire(capture: PhotoCapture, target?: ProjectWire): PhotoWire | undefined {
    return target ? capture.wires.find(w => w.wire_id === target.id && w.component_id === target.componentId
        && w.board_pin === target.boardPin && w.component_pin === target.componentPin) : undefined;
}

export interface GpioCaptureSource { kind: 'webcam' | 'phone'; runtimeRevision: number; }

/** One-shot capture of the selected FrameBus source; viewing never acquires a session. */
export class GpioPhotoCapture {
    private pending: Promise<void> | null = null;
    private session: string | null = null;
    constructor(private request: typeof photoWiringRequest = photoWiringRequest) {}
    get needsResume() { return !!this.session; }
    async resume() {
        if (!this.session) return;
        const id = this.session;
        const state = await this.request<{ resumed: boolean; continuous_inference: boolean }>(`sessions/${encodeURIComponent(id)}`,
            { method: 'DELETE', timeoutMs: 20000 });
        if (!state.resumed || !state.continuous_inference) throw Error('即時辨識尚未恢復，請重試恢復');
        if (this.session === id) this.session = null;
    }
    async capture(project: ProjectDesign, accepted: (capture: PhotoCapture) => void, source?: GpioCaptureSource): Promise<void> {
        if (this.pending) return this.pending;
        if (this.session) throw Error('請先恢復即時辨識，再重新擷取');
        const plan = photoPlanForProject(project);
        if (!acceptPhotoPlan(plan)) throw Error('作品接線清單無效');
        const task = (async () => {
            // Do not cancel acquire: even a late session ID must be released.
            const started = await this.request<{ session_id: string; continuous_inference: boolean }>('sessions', { method: 'POST' });
            this.session = started.session_id || null;
            try {
                if (!this.session || started.continuous_inference !== false) throw Error('照片服務尚未就緒');
                const capture = await this.request<PhotoCapture & { project_id: string; project_revision: number }>(`sessions/${encodeURIComponent(this.session)}/captures`, {
                    method: 'POST', timeoutMs: 45000, body: { project_id: project.id, project_revision: project.revision,
                        catalog_version: plan.catalog_version, profile_versions: plan.profile_versions, wires: plan.wires },
                });
                if (capture.project_id !== project.id || capture.project_revision !== project.revision
                    || !acceptPhotoCapture(capture, this.session, plan)) throw Error('照片與 GPIO 定位資料不一致');
                if (source && (capture.runtime_revision !== source.runtimeRevision
                    || !capture.camera_id.startsWith(`${source.kind}-`))) throw Error('photo_source_changed');
                accepted(capture); // Keep the photograph even if resume needs an explicit retry.
            } finally { await this.resume(); }
        })();
        this.pending = task;
        try { await task; } finally { if (this.pending === task) this.pending = null; }
    }
}

// Keep compatibility with earlier callers; both sources now use the same owner.
export { GpioPhotoCapture as WebcamGpioCapture };
