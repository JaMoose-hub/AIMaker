import test from 'node:test';
import assert from 'node:assert/strict';
import {fixtureRequestAllowed} from './wiring-ai-preview.mjs';

test('isolated wiring preview permits its assets and explicitly synthetic photo endpoint',()=>{
  for(const path of ['/','/?scenario=review','/preview.js','/preview.css',
    '/api/debug/sessions/qa-check/evidence/photo-one?view=overview',
    '/api/debug/sessions/qa-check/evidence/photo-one?view=pi_contact'])assert(fixtureRequestAllowed(path),path);
});
test('fixture scope rejects production/cloud origins and all real hardware/model/session APIs',()=>{
  for(const path of ['http://127.0.0.1:8100/','https://example.com/','//127.0.0.1:8100/preview.js',
    '/api/pi/status','/api/debug/sessions/real-session/evidence/photo-one','/api/debug/sessions',
    '/api/maker/generate','/api/camera/modes'])assert.equal(fixtureRequestAllowed(path),false,path);
});
