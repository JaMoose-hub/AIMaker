import test from 'node:test';
import assert from 'node:assert/strict';
import { flowModule, reviewHelpers } from './wiring_photo_flow_fixture.mjs';

const { wiringPhotoStatus, wiringPhotosReady, sameWiringCrop } = flowModule('../src/lib/wiringPhotoStatus.ts', { './wiringReview': reviewHelpers });
const roles = ['pi_side_a', 'pi_side_b', 'component_header'];
const slot = role => ({ role, capture_id: `capture-${role}`, sha256: `hash-${role}`, size: [4000, 3000], available: true,
  crop: null, crop_source: 'none', photo_acceptance: { capture_id: `capture-${role}`, sha256: `hash-${role}`, round: 1, source: 'human' } });
function review() {
  const slots = Object.fromEntries(roles.map(role => [role, slot(role)]));
  return { id: 'review', revision: 12, analysis_revision: 11, round: 1, component_id: 'hc-sr04', status: 'ready', slots,
    missing_roles: [], observations: [], results: [], reviews: {}, no_progress_count: 0,
    model_receipt: { review_id: 'review', wiring_round: 1, capture_ids: roles.map(role => slots[role].capture_id),
      capture_hashes: roles.map(role => slots[role].sha256), reused_roles: [], image_inputs: [] } };
}
const image = (r, role, view = 'overview', crop = null) => ({ role, view, crop, capture_id: r.slots[role].capture_id,
  source_sha256: r.slots[role].sha256, source_size: [4000, 3000], size: view === 'overview' ? [2048, 1536] : [2048, 1593] });

test('photo readiness requires all exact human selections and distinguishes unavailable or unselected photos', () => {
  const r = review(); assert.equal(wiringPhotosReady(r), true);
  for (const mutate of [s => delete s.photo_acceptance, s => s.photo_acceptance.capture_id = 'old',
    s => s.photo_acceptance.sha256 = 'old', s => s.photo_acceptance.round = 0, s => s.photo_acceptance.source = 'model']) {
    const changed = structuredClone(r); mutate(changed.slots.pi_side_a);
    assert.equal(wiringPhotosReady(changed), false); assert.equal(wiringPhotoStatus(changed, 'pi_side_a').state, 'unaccepted');
  }
  r.slots.pi_side_a.available = false; assert.equal(wiringPhotosReady(r), false);
  assert.equal(wiringPhotoStatus(r, 'pi_side_a').state, 'missing');
  assert.equal(wiringPhotoStatus(null, 'pi_side_a').state, 'missing');
});

test('crop edits compare exact normalized coordinates without hiding small changes or accepting malformed crops', () => {
  const crop = [.1, .2, .8, .9];
  assert.equal(sameWiringCrop(crop, [...crop]), true); assert.equal(sameWiringCrop(null, null), true);
  assert.equal(sameWiringCrop(null, undefined), false); assert.equal(sameWiringCrop(crop, [.100001, .2, .8, .9]), false);
  assert.equal(sameWiringCrop([0, 0, NaN, 1], [0, 0, NaN, 1]), false);
  assert.equal(sameWiringCrop([.8, 0, .1, 1], [.8, 0, .1, 1]), false);
});

test('saved crops and running or failed analyses cannot reuse an old completed receipt as current evidence', () => {
  for (const [state, expected] of [['collecting', 'pending'], ['analysing', 'analysing'], ['error', 'pending'], ['stale', 'unverified']]) {
    const r = review(); r.slots.pi_side_b.crop = [.2, .2, .8, .8];
    r.model_receipt.image_inputs = [image(r, 'pi_side_b')]; r.status = state;
    const result = wiringPhotoStatus(r, 'pi_side_b');
    assert.equal(result.state, expected); assert.deepEqual(result.images, []); assert.equal(result.detail, false);
  }
});

test('completed full-photo receipt verifies source identity while allowing later manual-decision revisions', () => {
  const r = review(); r.revision = 17; r.model_receipt.image_inputs = [image(r, 'pi_side_a')];
  assert.deepEqual(wiringPhotoStatus(r, 'pi_side_a'), { state: 'analysed', images: r.model_receipt.image_inputs, detail: false });
  for (const mutate of [r => r.model_receipt.review_id = 'other', r => r.model_receipt.wiring_round = 2,
    r => r.analysis_revision = null, r => r.analysis_revision = 18, r => r.model_receipt.image_inputs[0].capture_id = 'old',
    r => r.model_receipt.image_inputs[0].source_sha256 = 'old', r => r.model_receipt.image_inputs[0].source_size = [3000, 4000]]) {
    const changed = structuredClone(r); mutate(changed); assert.equal(wiringPhotoStatus(changed, 'pi_side_a').state, 'unverified');
  }
});

test('saved crop is marked analysed only when both overview and the exact original-pixel detail were sent', () => {
  const r = review(); r.slots.pi_side_b.crop = [.2381, .2198, .8137, .8164];
  r.model_receipt.image_inputs = [image(r, 'pi_side_b'), image(r, 'pi_side_b', 'detail', [952, 659, 3255, 2450])];
  const result = wiringPhotoStatus(r, 'pi_side_b'); assert.equal(result.state, 'analysed'); assert.equal(result.detail, true);
  for (const mutate of [r => r.model_receipt.image_inputs.pop(), r => r.model_receipt.image_inputs.shift(),
    r => r.model_receipt.image_inputs[1].crop[0]++, r => r.slots.pi_side_b.crop = null,
    r => r.model_receipt.image_inputs[1].size = [0, 1593]]) {
    const changed = structuredClone(r); mutate(changed); assert.equal(wiringPhotoStatus(changed, 'pi_side_b').state, 'unverified');
  }
});

test('reused roles require matching capture and hash at the same receipt index and never claim a crop was analysed', () => {
  const r = review(); r.model_receipt.reused_roles = ['pi_side_a']; r.slots.pi_side_a.crop = [.1, .1, .9, .9];
  assert.deepEqual(wiringPhotoStatus(r, 'pi_side_a'), { state: 'reused', images: [], detail: false });
  for (const mutate of [r => delete r.model_receipt.capture_hashes, r => r.model_receipt.capture_hashes[0] = 'wrong',
    r => r.model_receipt.capture_hashes.reverse(), r => r.model_receipt.capture_ids.push(r.slots.pi_side_a.capture_id),
    r => r.model_receipt.capture_ids[0] = 'old']) {
    const changed = structuredClone(r); mutate(changed); assert.equal(wiringPhotoStatus(changed, 'pi_side_a').state, 'unverified');
  }
});

test('missing receipt metadata remains unverified and presentation never mutates the review or decisions', () => {
  const r = review(), before = structuredClone(r);
  assert.equal(wiringPhotoStatus(r, 'component_header').state, 'unverified');
  assert.equal(wiringPhotosReady(r), true); assert.deepEqual(r, before);
  r.model_receipt = null; assert.equal(wiringPhotoStatus(r, 'component_header').state, 'unverified');
});

test('row-plan delivery cannot borrow a legacy receipt or claim a different requested row was analysed', () => {
  const r = review(); r.capture_plan = 'pi_rows_v1'; r.slots.pi_side_a.target_row = 'inner';
  r.model_receipt.image_inputs = [{...image(r, 'pi_side_a'), requested_row: 'inner'}];
  assert.equal(wiringPhotoStatus(r, 'pi_side_a').state, 'unverified');
  r.model_receipt.capture_plan = 'pi_rows_v1';
  assert.equal(wiringPhotoStatus(r, 'pi_side_a').state, 'analysed');
  for (const mutate of [r => r.model_receipt.image_inputs[0].requested_row = 'outer',
    r => delete r.model_receipt.image_inputs[0].requested_row, r => r.slots.pi_side_a.target_row = 'outer']) {
    const changed = structuredClone(r); mutate(changed);
    assert.equal(wiringPhotoStatus(changed, 'pi_side_a').state, 'unverified');
  }
});
