import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import ts from 'typescript';

const source = readFileSync(new URL('../src/lib/photoWiring.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022}}).outputText;
const helpers = await import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
const {acceptPhotoPlan, acceptPhotoCapture, acceptPhotoImageSize, acceptPhotoCheck, locatedPhotoPin,
  photoPlanBinding, photoPlanForProject, photoVerdictLabel, mergePhotoResults, openPhotoSession, photoWiringRequest,
  photoLocalizationFor,reliablePhotoPose,photoModelConfidence,photoOverlayObjects,photoFitScale,photoFocusBox,photoFocusView} = helpers;

test('missing endpoints explain hidden wires and cannot focus only the Pi end',()=>{
  const photo=capture(), wire=plan.wires[0];
  assert.deepEqual(helpers.photoMissingEndpoints(photo,wire),[]);
  photo.localization.find(p=>p.object_id==='hc-sr04').status='uncertain';
  assert.deepEqual(helpers.photoMissingEndpoints(photo,wire),['hc-sr04']);
  assert.equal(photoFocusBox(photo,undefined,wire),null);
  photo.localization.find(p=>p.object_id==='raspberry-pi-5').status='uncertain';
  assert.deepEqual(helpers.photoMissingEndpoints(photo,wire),['raspberry-pi-5','hc-sr04']);
});

test('an absent requested pin is not repaired from the raw box or another pin',()=>{
  const photo=capture();
  assert.deepEqual(helpers.photoMissingEndpoints(photo,{...plan.wires[0],component_pin:'ECHO'}),['hc-sr04']);
  assert.ok(photoFocusBox(photo,'hc-sr04')); // Object inspection is still available.
});

test('fitted photos stay inside fractional viewport sizes without creating scrollbars',()=>{
  for (const videoSize of [[1920,1080],[3840,2160],[1080,1920]]) {
    for (const [width,height] of [[519.999,477.047],[792.5,471.25],[320.2,350.4]]) {
      const scale=photoFitScale(videoSize,width,height);
      assert.ok(Number.isFinite(scale) && scale>0);
      assert.ok(videoSize[0]*scale<=width-3.99);
      assert.ok(videoSize[1]*scale<=height-3.99);
      assert.ok(Math.abs((videoSize[0]*scale)/(videoSize[1]*scale)-videoSize[0]/videoSize[1])<1e-12);
    }
  }
});

const plan = {catalog_version: 'fixture-v1', profile_versions: {}, component_ids: ['hc-sr04', 'mrd-tf240-8p-cs'], wires: [
  {wire_id:'hc:vcc', component_id:'hc-sr04', board_pin:'3V3_P1', component_pin:'VCC', connection_kind:'direct'},
  {wire_id:'tft:gnd', component_id:'mrd-tf240-8p-cs', board_pin:'GND_P6', component_pin:'GND', connection_kind:'direct'},
]};
const pin = id => ({id, x:20, y:30, c:.9, v:true});
const outline=[[10,10],[210,10],[210,110],[10,110]];
const pose = extra => ({frame_id:42, runtime_revision:7, tracking:'locked', video_size:[1920,1080], pins:[], outline:structuredClone(outline), ...extra});
const localization = object_id => ({object_id,status:'located',method:'fixture-photo-anchors',reason:'fixture-supported',
  evidence:{board_geometry_verified:true,pin_geometry_verified:true,model_confidence:.52,pin_method:'profile_projection_current_anchors'},
  raw_outline_px:[[5,0],[205,0],[205,100],[5,100]],corrected_outline_px:structuredClone(outline)});
function capture() {return {capture_id:'capture-a', session_id:'session-a', image_url:'/api/photo-wiring/captures/capture-a/image',
  captured_at:'2026-10-02T02:03:04Z', image_sha256:'a'.repeat(64), frame_id:42, runtime_revision:7, video_size:[1920,1080],
  camera_id:'mx-brio', quality:{warnings:[]}, stale:false, wires:structuredClone(plan.wires),
  detection:pose({board_id:'raspberry-pi-5', pins:[pin('3V3_P1'),pin('GND_P6')]}),
  components:[pose({component_id:'hc-sr04', pins:[pin('VCC')]}), pose({component_id:'mrd-tf240-8p-cs', pins:[pin('GND')]})],
  localization:['raspberry-pi-5',...plan.component_ids].map(localization)};}
function result(wire) {return {wire_id:wire.wire_id, verdict:'matched',
  board_observation:{state:'target',observed_pin:wire.board_pin,evidence:'Pi contact visible'},
  component_observation:{state:'target',observed_pin:wire.component_pin,evidence:'Module contact visible'},
  wire_observation:{same_wire:'consistent',visibility:'traceable',evidence:'One continuous route'}, note:'Visible match'};}
function job(photo=capture()) {return {job_id:'job-a',status:'completed',capture_id:photo.capture_id,frame_id:photo.frame_id,
  image_sha256:photo.image_sha256,results:photo.wires.map(result),electrical_verified:false};}

test('the canonical plan keeps exact component and pin identities and unique wires',()=>{
  assert.equal(acceptPhotoPlan(plan),true);
  for (const mutate of [p=>p.wires.push({...p.wires[0]}), p=>p.component_ids.push('hw-123'),p=>p.wires[0].component_id='different',p=>p.wires[0].board_pin='']) {
    const value=structuredClone(plan); mutate(value); assert.equal(acceptPhotoPlan(value),false);
  }
});

test('project conversion preserves wiring without saving or modifying manual records',()=>{
  const project={id:'project-a',revision:1,catalog_version:plan.catalog_version,profile_versions:{},component_ids:plan.component_ids,
    wiring:plan.wires.map(wire=>({id:wire.wire_id,componentId:wire.component_id,boardPin:wire.board_pin,componentPin:wire.component_pin,connectionKind:wire.connection_kind}))};
  const before=structuredClone(project);
  assert.deepEqual(photoPlanForProject(project),plan);
  assert.deepEqual(project,before);
  assert.notEqual(photoPlanBinding(plan,project),photoPlanBinding(plan,{...project,revision:2}));
  const rewired=structuredClone(plan);rewired.wires[0].board_pin='GPIO17';
  assert.notEqual(photoPlanBinding(plan,project),photoPlanBinding(rewired,project));
});

test('a frozen photo accepts only one image, frame, runtime, resolution and wiring binding',()=>{
  assert.equal(acceptPhotoCapture(capture(),'session-a',plan),true);
  const changes=[p=>p.session_id='other',p=>p.stale=true,p=>p.detection.frame_id++,p=>p.detection.runtime_revision++,
    p=>p.detection.video_size=[1280,720],p=>p.components[0].frame_id++,p=>p.components[0].runtime_revision++,
    p=>p.components[1].component_id='hc-sr04',p=>p.components[0].component_id='other',p=>p.wires[0].board_pin='GPIO17',
    p=>p.image_sha256='short',p=>p.image_url='/api/photo-wiring/captures/other/image',p=>p.frame_id=-1,
    p=>p.components[0].pins[0].x=Infinity,p=>p.detection.pins[0].x=99999];
  for (const mutate of changes) {const photo=capture();mutate(photo);assert.equal(acceptPhotoCapture(photo,'session-a',plan),false);}
});

test('missing poses may be shown as unlocated; a source size mismatch is never drawn',()=>{
  const photo=capture();photo.components=[];photo.detection.tracking='searching';photo.detection.pins=[];
  photo.localization=photo.localization.map(item=>({...item,status:'not_found',corrected_outline_px:null}));
  assert.equal(acceptPhotoCapture(photo,'session-a',plan),true);
  assert.equal(acceptPhotoImageSize(photo,1920,1080),true);
  assert.equal(acceptPhotoImageSize(photo,1280,720),false);
  assert.equal(locatedPhotoPin(photo.detection,'3V3_P1'),null);
});

test('legacy locked model predictions cannot become trusted GPIO coordinates',()=>{
  const photo=capture();delete photo.localization;
  assert.equal(acceptPhotoCapture(photo,'session-a',plan),true);
  assert.equal(photoLocalizationFor(photo,'raspberry-pi-5').status,'uncertain');
  assert.equal(reliablePhotoPose(photo,'raspberry-pi-5'),null);
  assert.deepEqual(photoOverlayObjects(photo,'corrected').flatMap(item=>item.pins),[]);
  assert.equal(acceptPhotoCheck(job(photo),photo),false);
});

test('reliable photo geometry requires explicit board and pin evidence, never confidence alone',()=>{
  const photo=capture();assert.equal(reliablePhotoPose(photo,'raspberry-pi-5'),photo.detection);
  assert.equal(photoModelConfidence(photo,'raspberry-pi-5'),.52);
  photo.detection.confidence=.999;assert.equal(photoModelConfidence(photo,'raspberry-pi-5'),.52);
  for(const field of ['board_geometry_verified','pin_geometry_verified']) {
    const invalid=capture();invalid.localization[0].evidence[field]=false;
    assert.equal(reliablePhotoPose(invalid,'raspberry-pi-5'),null);
    assert.equal(acceptPhotoCapture(invalid,'session-a',plan),false);
  }
  for(const mutate of [p=>p.localization.push({...p.localization[0]}),p=>p.localization[0].object_id='wrong',
    p=>p.localization[0].corrected_outline_px[0][0]=99,p=>p.localization[0].evidence=[],
    p=>p.localization[0].raw_outline_px[0][1]=NaN]) {
    const invalid=capture();mutate(invalid);assert.equal(acceptPhotoCapture(invalid,'session-a',plan),false);
  }
});

test('raw outlines and uncertain profile estimates are diagnostic only, including selected-wire matches',()=>{
  const photo=capture();const board=photo.localization[0];
  board.status='uncertain';board.reason='j8_rows_unverified';board.evidence.pin_geometry_verified=false;
  board.candidate_pins=structuredClone(photo.detection.pins);photo.detection.pins=[];photo.detection.tracking='searching';photo.detection.outline=null;
  assert.equal(acceptPhotoCapture(photo,'session-a',plan),true);
  assert.equal(reliablePhotoPose(photo,'raspberry-pi-5'),null);
  const corrected=photoOverlayObjects(photo,'corrected')[0];
  assert.deepEqual(corrected.outline,board.corrected_outline_px);assert.deepEqual(corrected.pins,[]);
  assert.deepEqual(corrected.candidatePins,board.candidate_pins);
  const raw=photoOverlayObjects(photo,'raw')[0];assert.deepEqual(raw.outline,board.raw_outline_px);
  assert.deepEqual(raw.pins,[]);assert.deepEqual(raw.candidatePins,[]);assert.deepEqual(photoOverlayObjects(photo,'photo'),[]);
  assert.equal(acceptPhotoCheck(job(photo),photo),false);
  const uncertain=job(photo);uncertain.results=uncertain.results.map(item=>({...item,verdict:'uncertain'}));
  assert.equal(acceptPhotoCheck(uncertain,photo),true);
  const contradiction=structuredClone(photo);contradiction.detection.tracking='locked';assert.equal(acceptPhotoCapture(contradiction,'session-a',plan),false);
});

test('focus uses original source coordinates and never promotes candidate GPIO to endpoints',()=>{
  const photo=capture();photo.detection.pins[0]={...pin('3V3_P1'),x:450,y:350};photo.components[0].pins[0]={...pin('VCC'),x:900,y:600};
  const box=photoFocusBox(photo,undefined,photo.wires[0]);assert.deepEqual(box,{x:375,y:275,width:600,height:400});
  const view=photoFocusView(box,800,500);assert.equal(view.scale,1.2);assert.equal(view.left,410);assert.equal(view.top,320);
  photo.localization[0].status='uncertain';photo.localization[0].candidate_pins=[{...pin('3V3_P1'),x:1900,y:1000}];
  assert.equal(photoFocusBox(photo,undefined,photo.wires[0]),null); // Both ends are required by this control.
  assert.deepEqual(photoFocusBox(photo,'raspberry-pi-5'),{x:0,y:0,width:285,height:185});
  photo.localization[1].status='uncertain';assert.equal(photoFocusBox(photo,undefined,photo.wires[0]),null);
  assert.equal(photoFocusBox(photo,'absent'),null);
});

test('photo pin lookup is component-local and requires an actually visible, locked pose',()=>{
  const photo=capture();
  assert.equal(locatedPhotoPin(photo.components[0],'VCC')?.id,'VCC');
  assert.equal(locatedPhotoPin(photo.components[1],'VCC'),null);
  const hidden=structuredClone(photo.components[0]);hidden.pins[0].v=false;
  assert.equal(locatedPhotoPin(hidden,'VCC'),null);
  hidden.pins[0].v=true;hidden.tracking='stale';assert.equal(locatedPhotoPin(hidden,'VCC'),null);
});

test('structured AI reports are accepted only for the exact frozen image and job',()=>{
  const photo=capture();assert.equal(acceptPhotoCheck(job(photo),photo,undefined,'job-a'),true);
  for(const mutate of [j=>j.capture_id='old',j=>j.frame_id++,j=>j.image_sha256='b'.repeat(64),j=>j.electrical_verified=true,
    j=>j.results[0].wire_id='unknown',j=>j.results.push({...j.results[0]}),j=>j.results[0].board_observation='old-contract',j=>j.results.pop()]) {
    const value=job(photo);mutate(value);assert.equal(acceptPhotoCheck(value,photo),false);
  }
  assert.equal(acceptPhotoCheck(job(photo),photo,undefined,'other-job'),false);
});

test('a selected wire job cannot apply reports from another wire',()=>{
  const photo=capture();const value=job(photo);value.results=[value.results[0]];
  assert.equal(acceptPhotoCheck(value,photo,'hc:vcc'),true);
  assert.equal(acceptPhotoCheck(value,photo,'tft:gnd'),false);
  value.results.push(result(photo.wires[1]));assert.equal(acceptPhotoCheck(value,photo,'hc:vcc'),false);
});

test('selected-wire rechecks preserve other current-photo reports but drop old photos or plans',()=>{
  const first=mergePhotoResults(null,'photo-a','binding-a',plan.wires.map(result));
  const changed={...result(plan.wires[0]),verdict:'uncertain'};
  const next=mergePhotoResults(first,'photo-a','binding-a',[changed]);
  assert.equal(next.values['hc:vcc'].verdict,'uncertain');assert.equal(next.values['tft:gnd'],first.values['tft:gnd']);
  assert.equal(first.values['hc:vcc'].verdict,'matched');
  assert.deepEqual(Object.keys(mergePhotoResults(first,'photo-b','binding-a',[changed]).values),['hc:vcc']);
  assert.deepEqual(Object.keys(mergePhotoResults(first,'photo-a','binding-b',[changed]).values),['hc:vcc']);
});

test('a matched report needs visible target contacts and a traceable same-wire route',()=>{
  const photo=capture();
  for(const mutate of [j=>j.results[0].board_observation.state='occluded',j=>j.results[0].component_observation.state='empty',
    j=>j.results[0].board_observation.observed_pin='GPIO17',j=>j.results[0].wire_observation.same_wire='different',
    j=>j.results[0].wire_observation.visibility='partially_visible']) {
    const value=job(photo);mutate(value);assert.equal(acceptPhotoCheck(value,photo),false);
  }
  const divider=capture();divider.wires[0].connection_kind='divider';assert.equal(acceptPhotoCheck(job(divider),divider),false);
});

test('photo verdict labels are translated and never claim electrical confirmation',()=>{
  assert.equal(photoVerdictLabel('matched','zh-TW'),'照片符合');
  assert.equal(photoVerdictLabel('suspected','en'),'Possible mismatch');
  assert.equal(photoVerdictLabel('uncertain','zh-TW'),'無法確認');
  for(const verdict of ['matched','suspected','uncertain']) assert.doesNotMatch(photoVerdictLabel(verdict,'en'),/verified|safe|pass/i);
});

function deferred() {let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
test('StrictMode cleanup before its queued POST prevents a duplicate session',async()=>{
  const queue={current:Promise.resolve()},events=[];
  const create=async()=>{events.push('POST');return 'token';},release=async id=>events.push(`DELETE ${id}`);
  const first=openPhotoSession(queue,create,release,()=>events.push('first-ready'),assert.fail);
  first.close();
  const second=openPhotoSession(queue,create,release,()=>events.push('second-ready'),assert.fail);
  await queue.current;assert.deepEqual(events,['POST','second-ready']);
  await second.close();assert.deepEqual(events,['POST','second-ready','DELETE token']);
});

test('closing while POST is in flight releases its late token before the next POST',async()=>{
  const queue={current:Promise.resolve()},pending=deferred(),events=[];
  const first=openPhotoSession(queue,()=>{events.push('POST first');return pending.promise;},async id=>events.push(`DELETE ${id}`),()=>events.push('stale-ready'),assert.fail);
  await flush();const closing=first.close();
  const second=openPhotoSession(queue,async()=>{events.push('POST second');return 'second';},async id=>events.push(`DELETE ${id}`),()=>events.push('second-ready'),assert.fail);
  await flush();assert.deepEqual(events,['POST first']);
  pending.resolve('first');await closing;await queue.current;
  assert.deepEqual(events,['POST first','DELETE first','POST second','second-ready']);
  await second.close();
});

test('a failed resume keeps the close pending for an explicit retry with the same token',async()=>{
  const queue={current:Promise.resolve()},events=[];let fail=true;
  const owner=openPhotoSession(queue,async()=> 'token',async id=>{events.push(id);if(fail)throw new Error('resume_failed');},()=>{},assert.fail);
  await queue.current;await assert.rejects(owner.close(),/resume_failed/);
  fail=false;await owner.close();await owner.close();assert.deepEqual(events,['token','token']);
});

test('poll and heartbeat requests have bounded network waits and preserve owner cancellation',async()=>{
  const originalFetch=globalThis.fetch;
  globalThis.fetch=async(_url,{signal})=>new Promise((_resolve,reject)=>{
    if(signal.aborted)reject(signal.reason);else signal.addEventListener('abort',()=>reject(signal.reason),{once:true});
  });
  try {
    await assert.rejects(photoWiringRequest('checks/test',{timeoutMs:5}),/timed out/);
    const controller=new AbortController();const promise=photoWiringRequest('checks/test',{timeoutMs:1000,signal:controller.signal});
    controller.abort(new Error('owner cancelled'));await assert.rejects(promise,/owner cancelled/);
  } finally {globalThis.fetch=originalFetch;}
});

test('photo workspace never subscribes to live pose feeds or writes manual confirmations',()=>{
  const component=readFileSync(new URL('../src/components/PhotoWiringPoc.tsx',import.meta.url),'utf8');
  assert.doesNotMatch(component,/useDetections|useRealtimeTracking|useGuidedPose|wsClient|localStorage|confirmProjectWire|deployPi|useComponentTests/);
  assert.match(component,/src="\/video"/);assert.match(component,/acceptPhotoCapture/);assert.match(component,/acceptPhotoCheck/);
  assert.match(component,/await closeSession\.current\?\.\(\)/);
  assert.match(component,/addEventListener\("visibilitychange", wakeHeartbeat\)/);
  assert.match(component,/removeEventListener\("pageshow", wakeHeartbeat\)/);
  assert.match(component,/candidatePins\.map/);assert.match(component,/reliablePhotoPose/);
});
