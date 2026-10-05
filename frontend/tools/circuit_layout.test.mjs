import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const sourceURL = new URL("../src/lib/circuitLayout.ts", import.meta.url);
const source = readFileSync(sourceURL, "utf8").replace(/import (\w+) from "([^"]+\.json)";/g,
  (_, name, path) => `const ${name} = ${readFileSync(new URL(path, sourceURL), "utf8")};`);
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } });
const { circuitLayout, circuitSelection } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
const catalog = JSON.parse(readFileSync(new URL("../../profiles/component-catalog.json", import.meta.url), "utf8"));
const board = JSON.parse(readFileSync(new URL("../../profiles/boards/raspberry-pi-5/board.json", import.meta.url), "utf8"));
const ids = catalog.modules.map(m => m.id);
function design(component_ids = ids) {
  return { component_ids, wiring: component_ids.flatMap(id => catalog.modules.find(m => m.id === id).steps.map(s => ({ ...s, id: `${id}:${s.id}`, componentId: id }))) };
}

test("all active combinations preserve the canonical project wires and endpoint identity", () => {
  for (let mask = 1; mask < (1 << ids.length); mask++) {
    const d = design(ids.filter((_, i) => mask & (1 << i)));
    const snapshot = JSON.stringify(d);
    const { modules, height } = circuitLayout(d);
    const routes = modules.flatMap(m => m.routes);
    assert.equal(routes.length, d.wiring.length);
    assert.equal(new Set(routes.map(r => r.wire.id)).size, d.wiring.length);
    for (const module of modules) {
      assert(module.top + module.height < height);
      for (const r of module.routes) {
        assert.equal(r.wire.componentId, module.id);
        assert.equal(r.pin.id, r.wire.componentPin);
        assert.equal(r.pin.wire, r.wire);
        assert.equal(r.boardPin.id, r.wire.boardPin);
        assert(r.boardY > 128, "Pi heading must not overlap a terminal");
      }
    }
    assert.equal(JSON.stringify(d), snapshot);
  }
});

test("Pi J8 always contains all forty physical pins in two paired rows of twenty", () => {
  for (const only of [undefined, ...ids]) {
    const {boardPins, height} = circuitLayout(design(), only);
    assert.equal(boardPins.length, 40);
    assert.equal(new Set(boardPins.map(pin => pin.id)).size, 40);
    assert.deepEqual(boardPins.map(pin => pin.number), Array.from({length:40}, (_, i) => i + 1));
    assert.equal(new Set(boardPins.map(pin => pin.x)).size, 2);
    for (let row = 0; row < 20; row++) {
      const pair = boardPins.filter(pin => pin.row === row);
      assert.deepEqual(pair.map(pin => pin.number), [row * 2 + 1, row * 2 + 2]);
      assert.deepEqual(pair.map(pin => pin.column), [0, 1]);
      assert.equal(pair[0].y, pair[1].y);
      assert(pair.every(pin => pin.y > 132 && pin.y < height - 28));
    }
    for (const pin of boardPins) assert.equal(pin.id, board.pins.find(p => p.index === pin.number).id);
  }
});

test("routes connect to physical pins, not lesson order or a GPIO number", () => {
  const {modules} = circuitLayout(design());
  const routes = modules.flatMap(module => module.routes);
  const expected = {"hc-sr04:VCC":1, "hc-sr04:TRIG":11, "hc-sr04:ECHO":12,
    "hc-sr04:GND":6, "mrd-tf240-8p-cs:VCC":17, "mrd-tf240-8p-cs:GND":20};
  for (const [key, number] of Object.entries(expected)) {
    const route = routes.find(r => `${r.wire.componentId}:${r.wire.componentPin}` === key);
    assert.equal(route.boardPin.number, number, key);
  }
  assert.equal(new Set(routes.map(route => route.laneX)).size, routes.length);
});

test("an unknown Pi endpoint never invents a connection or an infinite canvas", () => {
  const d = design(['hc-sr04']);
  d.wiring = d.wiring.map(wire => ({...wire, boardPin:'unknown'}));
  const {modules, boardPins, height} = circuitLayout(d);
  assert.equal(boardPins.length, 40);
  assert.equal(modules[0].routes.length, 0);
  assert(modules[0].pins.every(pin => !pin.wire));
  assert(Number.isFinite(height));
});

test("module pin order and header edge follow camera vision profiles, not lesson order", () => {
  for (const module of circuitLayout(design()).modules) {
    const vision = JSON.parse(readFileSync(new URL(`../../profiles/components/${module.id}/vision_profile.json`, import.meta.url), "utf8"));
    assert.deepEqual(module.pins.map(p => p.id), [...vision.pins].sort((a, b) => a.x_norm - b.x_norm).map(p => p.id));
    assert.equal(module.headerAtTop, module.id === "mrd-tf240-8p-cs");
    assert.equal(new Set(module.pins.map(p => p.x)).size, module.pins.length);
  }
});

test("TFT VCC uses Pin17 but unverified BLK is drawn without a connection", () => {
  const modules = circuitLayout(design()).modules;
  const display = modules.find(m => m.id === "mrd-tf240-8p-cs");
  assert.deepEqual(display.pins.filter(p => p.state === "pending").map(p => p.id), ["BLK"]);
  assert.equal(display.pins.find(p => p.id === "VCC").wire.boardPin, "3V3_P17");
  assert(display.pins.filter(p => p.state === "pending").every(p => !p.wire));
});

test("ECHO divider branch terminates on this module's real GND route", () => {
  const legacy = design();
  legacy.wiring.find(w => w.componentPin === 'ECHO').connectionKind = 'divider';
  const ultrasonic = circuitLayout(legacy).modules[0];
  const echo = ultrasonic.routes.find(r => r.pin.id === "ECHO");
  const ground = ultrasonic.routes.find(r => r.pin.id === "GND");
  assert.equal(echo.wire.connectionKind, "divider");
  assert.equal(echo.groundY, ground.boardY);
  assert(echo.groundX > Math.max(echo.laneX, ground.laneX));
  assert(echo.groundX < 366, 'divider branch joins the routed ECHO before its resistor');
  assert.equal(echo.wire.boardPin, "GPIO18");
  assert.equal(ground.wire.boardPin, "GND_P6");
});

test("focusing a module does not confuse shared SDA or GND names", () => {
  const full = design();
  for (const id of ids) {
    const result = circuitLayout(full, id);
    assert.equal(result.modules.length, 1);
    assert.equal(result.modules[0].id, id);
    assert(result.modules[0].routes.every(r => r.wire.componentId === id));
  }
});

test("Blueprint step selection follows exact wire IDs and switches away from an old module filter", () => {
  const d = design();
  const before = JSON.stringify(d);
  for (const wire of d.wiring) {
    const result = circuitSelection(d, {selectedId: wire.id, moduleFilter: 'mrd-tf240-8p-cs'});
    assert.equal(result.focus, wire);
    assert.equal(result.filter, wire.componentId);
    assert.equal(result.activeWire, undefined, 'viewing a wire must not start camera guidance');
  }
  assert.equal(JSON.stringify(d), before);
});

test("clearing Blueprint selection cannot revive a previously clicked pin or select unknown power pins", () => {
  const d = design();
  const selected = {componentId: 'mrd-tf240-8p-cs', pinId: 'GND'};
  assert.equal(circuitSelection(d, {selected}).focus.componentId, 'mrd-tf240-8p-cs', 'legacy pin inspection remains');
  for (const selectedId of [null, 'missing', 'mrd-tf240-8p-cs:VCC']) {
    assert.equal(circuitSelection(d, {selectedId, selected}).focus, undefined);
  }
  const result = circuitSelection(d, {selectedId: null, selected, moduleFilter:'hc-sr04'});
  assert.equal(result.filter, 'hc-sr04');
});

test("camera guidance overrides selection with the selected variant's direct ECHO", () => {
  const d = design();
  const echo = d.wiring.find(w => w.componentPin === 'ECHO');
  const other = d.wiring.find(w => w.componentId === 'mrd-tf240-8p-cs' && w.componentPin === 'GND');
  const result = circuitSelection(d, {activeId:echo.id, selectedId:other.id, moduleFilter:'mrd-tf240-8p-cs'});
  assert.equal(result.activeWire, echo);
  assert.equal(result.focus, echo);
  assert.equal(result.filter, 'hc-sr04');
  assert.equal(result.focus.connectionKind, 'direct');
});

test("historical diagrams use their frozen pin order and header edge without borrowing live profiles", () => {
  const d = design(['hc-sr04']);
  const frozen = {modules:[{id:'hc-sr04', pins:[{id:'ECHO',x_norm:0,y_norm:0},{id:'GND',x_norm:1,y_norm:0}],
    pin_order:['GND','ECHO'],header_at_top:true,unresolved:[]}]};
  const before=JSON.stringify(frozen);
  const diagram=circuitLayout(d,undefined,frozen);
  assert.deepEqual(diagram.modules[0].pins.map(pin=>pin.id),['GND','ECHO']);
  assert.equal(diagram.modules[0].headerAtTop,true);
  assert.equal(diagram.modules[0].routes.length,2,'only pins in the historical profile are rendered');
  assert.equal(JSON.stringify(frozen),before);
  assert.equal(circuitLayout(d,undefined,{modules:[]}).modules.length,0,'a missing archived profile must not render a modern pin layout');
});
