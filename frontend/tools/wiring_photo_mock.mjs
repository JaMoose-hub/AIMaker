// In-memory responses for UI fixtures only. This is not the production server.
export function applyFixturePhotoAction(review, action, {captureSlot, now=()=>Date.now()/1000}={}) {
  if (!review || action.review_id !== review.id || action.revision !== review.revision) throw new Error('stale_wiring_review');
  if (action.op==='accept_photo') {
    const slot=review.slots[action.role];
    if (!slot || slot.available===false || slot.capture_id!==action.capture_id || slot.sha256!==action.sha256) throw new Error('stale_wiring_review_photo');
    return {...review,revision:review.revision+1,slots:{...review.slots,[action.role]:{...slot,photo_acceptance:{
      capture_id:slot.capture_id,sha256:slot.sha256,round:review.round,accepted_at:now(),source:'human',
    }}}};
  }
  if (action.op==='capture') {
    if (!captureSlot) throw new Error('Fixture capture unavailable');
    const slot=captureSlot(action.role);
    return {...review,revision:review.revision+1,status:'collecting',slots:{...review.slots,[action.role]:slot},results:[],observations:[],
      reviews:Object.fromEntries(Object.entries(review.reviews).map(([id,value])=>[id,{...value,evidence_stale:true}]))};
  }
  if (action.op==='changed') return {...review,revision:review.revision+1,round:review.round+1,status:'collecting',
    slots:{pi_side_a:null,pi_side_b:null,component_header:null},results:[],observations:[],reviews:{}};
  throw new Error(`Fixture operation unsupported: ${action.op}`);
}
