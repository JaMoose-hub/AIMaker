import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {transpileModule, ModuleKind, ScriptTarget} from 'typescript';

const source = readFileSync(new URL('../src/lib/pinCalibration.ts', import.meta.url), 'utf8');
const output = transpileModule(source, {compilerOptions: {module: ModuleKind.ESNext, target: ScriptTarget.ES2022}}).outputText;
const {resolvePinCalibration: resolve, CONTACT_ALIGNMENT_VERSION: version} = await import('data:text/javascript;base64,' + Buffer.from(output).toString('base64'));
const auto = {version, accepted: true, offset_px: [-19, 1]};

test('supported contacts take over without double correction or erasing the saved manual fallback', () => {
  const saved = Object.freeze({x:-18, y:0});
  const effective = resolve(saved, 'raspberry-pi-5', auto);
  assert.deepEqual(effective, {x:0, y:0});
  assert.equal(950 + auto.offset_px[0] + effective.x, 931);
  assert.deepEqual(saved, {x:-18, y:0});
  // Reacquisition can move the board projection without moving real contacts.
  // Do not undo the new correct position to retain an old screen-space nudge.
  assert.deepEqual(resolve(saved, 'raspberry-pi-5', {...auto, offset_px:[0,-26]}), {x:0,y:0});
  assert.equal(resolve(saved, 'raspberry-pi-5', {...auto, accepted:false}), saved);
});

test('neutral/reset calibration uses automatic contact alignment; new nudges are residuals', () => {
  assert.deepEqual(resolve({x:0,y:0}, 'raspberry-pi-5', auto), {x:0,y:0});
  const nudged = {x:2,y:-1,alignmentVersion:version};
  assert.equal(resolve(nudged, 'raspberry-pi-5', auto), nudged);
});

test('old backend, unsupported frame, other boards and malformed evidence preserve user offset', () => {
  const saved = {x:-18,y:0};
  for(const evidence of [undefined, {...auto,accepted:false}, {...auto,version:'unknown'},
    {...auto,offset_px:[NaN,0]}, {...auto,offset_px:[Infinity,0]}, {...auto,offset_px:[1]}]) {
    assert.equal(resolve(saved, 'raspberry-pi-5', evidence), saved);
  }
  assert.equal(resolve(saved, 'arduino-uno-q', auto), saved);
});

test('overlay and guide use the same displayed pose correction; old saved nudges are not erased', () => {
  const view = readFileSync(new URL('../src/components/VideoView.tsx', import.meta.url), 'utf8');
  assert.match(view, /resolvePinCalibration\(pinCalibrationOffset, boardId, guideDetection\?\.pin_alignment\)/);
  assert.match(view, /boardDisplayOffsetPx=\{displayedPinOffset\}/);
  assert.match(view, /displayOffsetPx=\{displayedPinOffset\}/);
  assert.match(view, /boardvision\.gpio-pin-calibration\.v3/);
  assert.match(view, /X \{displayedPinOffset.x\}.*Y \{displayedPinOffset.y\}/);
  assert.match(view, /camera.pinCalibrationAutoRetained/);
});
