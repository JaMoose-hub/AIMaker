import { acceptPhotoCapture, acceptPhotoPlan, photoMissingEndpoints, photoPlanForProject, photoWiringRequest, type PhotoCapture, type PhotoWire } from './photoWiring';
import { currentWire, type ProjectDesign, type ProjectGuideState, type ProjectWire } from './maker';

export type GpioView = 'webcam' | 'phone' | 'photo';
export interface GpioPhotoRecord {
    source: 'webcam' | 'phone';
    projectId: string;
    revision: number;
    round: number;
    capture: PhotoCapture;
}
export function photoRecordCurrent(record: GpioPhotoRecord, project: ProjectDesign | null, round: number) {
    return photoRecordMismatch(record, project, round) === null;
}
export type PhotoRecordMismatch = 'project' | 'revision' | 'round' | 'invalidated';
export function photoRecordMismatch(record: GpioPhotoRecord, project: ProjectDesign | null, round: number): PhotoRecordMismatch | null {
    if (!project || record.projectId !== project.id) return 'project';
    if (record.revision !== project.revision) return 'revision';
    if (record.round !== round) return 'round';
    return record.capture.stale ? 'invalidated' : null;
}
/** Never substitute another wire when the guide's target is absent from this photo. */
export function photoGuideWire(capture: PhotoCapture, target?: ProjectWire): PhotoWire | undefined {
    return target ? capture.wires.find(w => w.wire_id === target.id && w.component_id === target.componentId
        && w.board_pin === target.boardPin && w.component_pin === target.componentPin
        && w.connection_kind === target.connectionKind) : undefined;
}

/** Merely opening the workspace or selecting a prepared module never starts wiring. */
export function photoGuidanceTarget(project: ProjectDesign | null, guide: ProjectGuideState): ProjectWire | undefined {
    return project && guide.phase === 'active' ? currentWire(project, guide) : undefined;
}

/** A prior round can show intended positions, while remaining historical evidence.
 * Changed projects, plans and invalidated captures can never supply that reference.
 */
export function photoGuidanceState(capture: PhotoCapture, target: ProjectWire | undefined, historical: boolean,
    historicalReason?: PhotoRecordMismatch | null) {
    const referenceOnly = historical && historicalReason === 'round' && !capture.stale;
    if ((historical && !referenceOnly) || capture.stale) return { kind: 'historical' as const, wire: undefined, missing: [], referenceOnly: false };
    if (!target) return { kind: 'no-target' as const, wire: undefined, missing: [], referenceOnly };
    const wire = photoGuideWire(capture, target);
    if (!wire) return { kind: 'plan-mismatch' as const, wire: undefined, missing: [], referenceOnly };
    const missing = photoMissingEndpoints(capture, wire);
    return { kind: missing.length ? 'missing-endpoints' as const : wire.connection_kind === 'divider' ? 'divider' as const : 'ready' as const, wire, missing, referenceOnly };
}

export interface GpioCaptureSource { kind: 'webcam' | 'phone'; runtimeRevision: number; }

/** One-shot capture of the selected FrameBus source; viewing never acquires a session. */
export class GpioPhotoCapture {
    private pending: Promise<void> | null = null;
    constructor(private request: typeof photoWiringRequest = photoWiringRequest) {}
    // Keep the workspace's recovery interface; snapshots never acquire a pause
    // lease, so an upload/model failure has no live worker to resume.
    get needsResume() { return false; }
    async resume() {}
    async capture(project: ProjectDesign, accepted: (capture: PhotoCapture) => void, source?: GpioCaptureSource): Promise<void> {
        if (this.pending) return this.pending;
        const plan = photoPlanForProject(project);
        if (!acceptPhotoPlan(plan)) throw Error('作品接線清單無效');
        const task = (async () => {
            const capture = await this.request<PhotoCapture & { project_id: string; project_revision: number; continuous_inference: boolean }>('snapshot', {
                method: 'POST', timeoutMs: 45000, body: { project_id: project.id, project_revision: project.revision,
                    catalog_version: plan.catalog_version, profile_versions: plan.profile_versions, wires: plan.wires },
            });
            if (capture.project_id !== project.id || capture.project_revision !== project.revision
                || capture.continuous_inference !== true || !capture.session_id
                || !acceptPhotoCapture(capture, capture.session_id, plan)) throw Error('照片與 GPIO 定位資料不一致');
            if (source && (capture.runtime_revision !== source.runtimeRevision
                || !capture.camera_id.startsWith(`${source.kind}-`))) throw Error('photo_source_changed');
            accepted(capture);
        })();
        this.pending = task;
        try { await task; } finally { if (this.pending === task) this.pending = null; }
    }
}

// Keep compatibility with earlier callers; both sources now use the same owner.
export { GpioPhotoCapture as WebcamGpioCapture };
