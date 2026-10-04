import { wireSignature, type ProjectDesign, type ProjectGuideState } from './maker';
import { componentTestKey } from './componentTests';
import type { DebugContext } from './debug';

/** Explicit human action only. Unknown/ambiguous wire IDs fail without changing the guide. */
export function confirmReviewedWire(design: ProjectDesign, guide: ProjectGuideState, wireId: string): ProjectGuideState {
    const matches = design.wiring.filter(wire => wire.id === wireId && design.component_ids.includes(wire.componentId));
    if (matches.length !== 1) throw new Error('wiring_review_wire_not_found');
    const wire = matches[0];
    const signature = wireSignature(wire);
    const existing = guide.confirmed[wire.id];
    if (existing?.signature === signature && ['camera', '2d'].includes(existing.mode)
        && typeof existing.at === 'string' && Number.isFinite(Date.parse(existing.at))) return guide;
    return { ...guide, confirmed: { ...guide.confirmed, [wire.id]: {
        signature, mode: guide.mode, at: new Date().toISOString(),
    } } };
}

/** An explicit unsure/needs-change response retracts only this wire's earlier confirmation. */
export function unconfirmReviewedWire(design: ProjectDesign, guide: ProjectGuideState, wireId: string): ProjectGuideState {
    const matches = design.wiring.filter(wire => wire.id === wireId && design.component_ids.includes(wire.componentId));
    if (matches.length !== 1) throw new Error('wiring_review_wire_not_found');
    if (!Object.hasOwn(guide.confirmed, wireId)) return guide;
    const confirmed = { ...guide.confirmed };
    delete confirmed[wireId];
    return { ...guide, confirmed };
}

/** Call after hardware-stop reconciliation. Keeps browsing and the wiring round intact. */
export function invalidateReviewedComponent(design: ProjectDesign, guide: ProjectGuideState, componentId?: string): ProjectGuideState {
    if (componentId !== undefined && !design.component_ids.some(id => id === componentId)) {
        throw new Error('wiring_review_component_not_found');
    }
    const affected = new Set(design.wiring.filter(wire => componentId === undefined || wire.componentId === componentId).map(wire => wire.id));
    const confirmed = componentId === undefined ? {} : Object.fromEntries(
        Object.entries(guide.confirmed).filter(([wireId]) => !affected.has(wireId)),
    );
    return { ...guide, confirmed, checks: [] };
}

/** Build one coherent context; a stale project's context must never be rebound silently. */
export function contextWithReviewGuide(context: DebugContext, design: ProjectDesign, guide: ProjectGuideState): DebugContext {
    const original = context.project;
    if (!original || original.id !== design.id || original.revision !== design.revision
        || original.wiring.length !== design.wiring.length
        || original.wiring.some(wire => !design.wiring.some(current => current.id === wire.id && wireSignature(current) === wireSignature(wire)))) {
        throw new Error('wiring_review_project_changed');
    }
    return { ...context, project: design, guide_confirmations: guide.confirmed, guide_run: guide.run ?? 0,
        test_keys: Object.fromEntries(design.component_ids.map(componentId => [componentId, componentTestKey(design, guide, componentId)])),
    };
}
