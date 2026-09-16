# Capability ② — Wiring Guidance & Verification: Final Synthesized Architecture

*Design-only. No files under `C:\Project\PnP\board-vision` were written or modified as part of producing this design. Grounded by direct reads of `docs/api-contract.md`, `backend/app/main.py`, `backend/app/vision/interface.py`, and `profiles/boards/arduino-uno-q/board.json` (verifying every concrete fact cited below — D3's `five_volt_tolerant:false` danger warning, D7's literal HC-SR04 Trig/Echo usage example, D5/D6/D9/D10/D11/D3's fixed-500Hz PWM notes, the BOOT strap at `JANALOG` index 0, the `i2c0` dedicated-SDA/SCL vs A4/A5 caveat, and the `type`-field extensibility clause in the WS contract that already names `wiring_check` as an anticipated future value).*

Produced by a 3-way judge-panel design (tool-contract-first / runtime-state-first / spec-DSL-first) followed by a synthesis pass. Continues directly from Board Vision (capability ①, milestones M0–M7, already shipped and tested).

---

## 0. Why this synthesis

Three independent designs (A: tool-contract-first, B: runtime-state-first, C: spec/DSL-first) converged on the same module boundaries and the same "camera proves presence, serial proves function" evaluation loop, but made three different central bets. None of the three is wrong; each optimized a different axis and, in doing so, exposed a real weakness in the other two. This synthesis takes the strongest concrete decision from each and reconciles them into one design:

| Decision | Taken from | Why the other two fall short here |
|---|---|---|
| **Continuously-running `WiringWorker` + live `WiringState`** as the runtime spine, not a job spun up only when asked | **B** | A and C both treat a wiring check as computed *on request*. That means an eager AI agent polling "is it fixed yet?" every few seconds becomes the thing that repeatedly fires the disruptive electrical test — exactly the failure mode the deck's own "camera is free, GPIO/I²C is not" framing warns against. B's debounce/rate-limit/heartbeat design is the only one of the three that structurally prevents this. |
| **Declarative op-vocabulary DSL** (`pin_mode`/`digital_write`/`pulse_out`/`pulse_in`/`i2c_scan`/`analog_read`/…) as the *only* thing a `ComponentSpec.test_procedure` may contain | **C** | A and B both hardcode named test "methods" per role (`gpio_pulse_echo`, `i2c_scan_match`...) that the firmware must special-case one by one. C's closed primitive vocabulary means the firmware's dispatch table never grows when a new sensor spec is authored, and — critically for capability③ — it is safe to let an LLM *compose* a test procedure from a small interpretable primitive set, but unsafe to ask it to author arbitrary code that pokes real GPIOs. A's and B's per-role named methods don't give that guarantee. |
| **`ComponentSpec` as an independent, semver-versioned peer profile family** — not a fake `BoardProfile`, and split cleanly from the *evaluation* engine (`app/components/` vs `app/wiring/`) | **C** | A and B both put spec storage and live evaluation logic in one `app/wiring/` folder. C's split mirrors the repo's own discipline (`app/profiles/` is pure data + validation; `app/vision/` is the seam that *acts* on it) and its per-component semver (`hc-sr04@1.0.0`) gives reproducible plan instances — directly serving the deck's "可重現的專案狀態" moat item — which neither A nor B version at all. |
| **Split AI-facing surface: cheap synchronous `GET verdict` vs. explicit async `POST verify`/`POST checks`**, with WS push as a third channel | **B**'s split, **A**'s bounded-wait convenience, **C**'s ad-hoc-plan endpoint | A collapses "read current state" and "run a check" into one long-poll endpoint — defensible in isolation, but only *needs* a wait/poll story because A has no continuously-maintained state to read from. Once B's live `WiringState` exists, the read path becomes trivially synchronous (same cost as `GET /api/config`), and only the explicit force-recheck path needs to be async — which is also *forced* by implementation reality (the serial link has exactly one owner thread; a REST handler cannot execute serial I/O inline). C's `POST /api/wiring/checks` ad-hoc-plan convenience (check a pin combination that was never pre-registered) is kept as a thin wrapper over the same primitives, exactly as C designed it — not a separate code path. |
| **Per-role honesty tags** (`electrical: not_testable` for VCC/GND, distinct from `pass`/`fail`) and the **three-way diagnostic split** (`incompatible_assignment` vs `wiring_absent` vs `electrical_signature_mismatch`) | **C** | A's diagnosis enum is a good flat taxonomy but doesn't explicitly separate "vision says absent" from "vision says present but electrical disagrees" as a *named class* the way C does — and that distinction is precisely the one an LLM needs to give different remediation advice ("plug it in" vs "check for a swapped/dead wire"). |
| **Confidence decay / staleness for electrical evidence**, echoing the existing `tracking: searching\|locked\|stale` idiom already shipped in `docs/api-contract.md` §2 | **B** | Only meaningful once state is continuously live (B's premise) — A and C's per-request model has no "age" to decay, since every result is freshly computed. Adopting B's worker model pulls this in for free and it is a natural extension of a pattern the repo already ships. |
| **Firmware safety state machine**: idle tri-state, explicit pin claim, watchdog auto-release on host silence | **B**'s watchdog + **A**'s "never leave a pin driving" idle rule + **C**'s BOOT-pin cross-check | Each proposal had one piece of this; none had all three. Combined, it is the complete safety story. |
| **Board-mismatch / voltage-incompatibility rejection using existing `Pin.electrical.five_volt_tolerant`**, citing real D3 danger text | **A, B, C — unanimous** | All three independently found and used this real field. Kept as-is; it's the single cleanest proof point that the data model composes with capability① for free. |

Everything else below (module layout, wire formats, milestones) is the concrete machinery needed to make this hybrid consistent, re-verified against the real files.

---

## 1. One-paragraph overview

A new peer profile family, `profiles/components/*/component.json`, declares what a module (HC-SR04, LED, servo…) needs electrically and how to prove it, using a **closed primitive op-vocabulary** the Device Runtime test firmware implements once. `app/components/` (pure data: models, store, resolver) turns `ComponentSpec × BoardProfile × pin_assignment` into a versioned `WiringPlanInstance` — a compile-time-only step, zero hardware/camera I/O, that already catches real hazards (`ECHO→D3` rejected citing D3's actual `five_volt_tolerant:false` danger warning). A new background thread, `WiringWorker` (mirroring `VisionWorker`'s own thread-per-concern discipline), is the **third independent reader** of the existing `FrameBus`/`DetectionState` (the first two are MJPEG clients and `VisionWorker` itself) and the sole owner of the new `app/serial/` USB-serial link to the Device Runtime test firmware. It continuously maintains a live `WiringState` — cheap vision-presence checks every tick, debounced+rate-limited+heartbeat-gated electrical re-tests — and pushes changes over the **existing** `DetectionBroadcaster`, tagged with the WS `type` value `"wiring_check"` that `docs/api-contract.md` §2 already names as a reserved future extension point. An AI agent (or a human frontend) then talks to a thin, mostly-stateless REST/MCP surface that is almost entirely a read of that live state, plus an explicit, honestly-async "force a real re-test now" escape hatch.

---

## 2. Module / component breakdown

```
board-vision/
├── backend/app/
│   ├── serial/                          # NEW — Host↔Device Runtime transport (peer of app/vision/)
│   │   ├── protocol.py                  #   JSON-Lines codec, id-correlation, timeout handling
│   │   ├── link.py                      #   SerialLink (pyserial) — owns the port exclusively
│   │   ├── mock_link.py                 #   MockSerialLink — deterministic scripted replay (mirrors mock_detector.py)
│   │   └── factory.py                   #   create_serial_link(config) -> mock|serial, lazy pyserial import
│   │
│   ├── components/                       # NEW — pure data layer (peer of app/profiles/)
│   │   ├── models.py                    #   ComponentSpec, PinRole, TestStep (op DSL), Assertion — pydantic StrictModel
│   │   ├── store.py                     #   ComponentStore — jsonschema+pydantic double validation, cache by "{id}@{version}" (mirrors ProfileStore)
│   │   └── resolver.py                  #   resolve_plan(board_profile, spec, pin_assignment) -> WiringPlanInstance; suggest_assignments() for capability③'s planner hook. Pure, no I/O.
│   │
│   ├── wiring/                          # NEW — the live evaluation engine (peer of app/vision_worker.py)
│   │   ├── interface.py                 #   VisionPresenceChecker / ElectricalTestRunner Protocols — "never raise, always return a typed result", same contract discipline as BoardDetector.detect()
│   │   ├── vision_presence.py           #   reuses FrameBus + DetectionState — NOT a new CV pipeline, just a pixel-patch presence probe at pin coords already computed by ①
│   │   ├── electrical.py                #   compiles ComponentSpec.test_procedure.steps -> app/serial/protocol.py calls; applies assertions
│   │   ├── evaluator.py                 #   pure merge fn: (vision, electrical) per role -> RoleVerdict + diagnosis class
│   │   ├── state.py                     #   WiringState — thread-safe latest-value holder (mirrors vision_worker.DetectionState exactly)
│   │   ├── worker.py                    #   WiringWorker(thread) — continuous loop + debounce/rate-limit/heartbeat + force-verify queue
│   │   └── jobs.py                      #   in-memory job registry for the explicit async /verify path
│   │
│   ├── api/
│   │   ├── wiring.py                    # NEW router — /api/components/*, /api/wiring/plans, /api/wiring/verdict, /api/wiring/verify, /api/wiring/jobs
│   │   └── mcp_tools.py                 # NEW — thin 1:1 MCP shim over app/api/wiring.py's own calls, no separate logic
│   │
│   ├── main.py                          # EXTENDED — see §2.1
│   └── config.py                        # EXTENDED — see §2.2
│
├── profiles/
│   ├── boards/arduino-uno-q/board.json  # UNCHANGED
│   ├── components/
│   │   ├── hc-sr04/component.json       # NEW — §4
│   │   ├── led/component.json           # NEW
│   │   └── sg90-servo/component.json    # NEW
│   └── plans/arduino-uno-q/
│       └── demo-hcsr04.json             # NEW — a persisted, resolved plan instance
│
├── schemas/
│   ├── board-profile.schema.json        # UNCHANGED
│   └── component-spec.schema.json       # NEW — mirrors board-profile.schema.json's $defs/i18nText/additionalProperties:false style
│
└── firmware/wiring-test-fw/             # NEW, outside backend/ — §7
```

Frontend (deferred to the last milestone, per all three proposals' agreement that the AI contract is the actual deliverable): `frontend/src/components/WiringPanel.tsx` + one new branch in `wsClient.ts`'s `handleMessage()`, which today already has the comment *"Any other type (wiring_check, telemetry, ...) is intentionally ignored"* — confirmed by reading the contract doc, this is a pure addition.

### 2.1 `main.py` wiring — extends, does not restructure, the existing `build_app()`

Verified against the real file: `build_app()` already takes injected-or-lazily-built `detector`/`source`, builds `frame_bus`/`detection_state`/`broadcaster` up front, and does `state.X = _lazy_build(...)` inside `lifespan()` with a symmetric `finally:` teardown, then registers exactly four routers before the catch-all static mount. The extension follows that shape verbatim:

```python
# app/main.py — additive diff, not a rewrite
from app.components.store import ComponentStore
from app.wiring.state import WiringState
from app.wiring.worker import WiringWorker
from app.wiring.jobs import WiringJobStore

def build_app(config=None, *, detector=None, source=None, scene=None,
              profile_store=None,
              component_store=None,        # NEW — same injection seam style as detector/source
              serial_link=None) -> FastAPI: # NEW
    ...
    comp_store = component_store or ComponentStore(config.profile_dir / "components")
    wiring_state = WiringState()
    wiring_jobs = WiringJobStore()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ...  # existing source/detector/capture_service/vision_worker build, unchanged
        if state.serial_link is None:
            from app.serial.factory import create_serial_link   # lazy import, same reasoning as _build_detector's lazy vision import
            state.serial_link = create_serial_link(config.serial)

        state.wiring_worker = WiringWorker(
            bus=frame_bus,                          # SAME FrameBus, independent read cursor
            detection_state=detection_state,        # reads VisionWorker's published pins, never recomputes pose
            serial_link=state.serial_link,          # exclusive owner of the port
            plan_store=plan_store,
            wiring_config=config.wiring,
            state=wiring_state,
            jobs=wiring_jobs,
            publish=broadcaster.publish_threadsafe,  # SAME broadcaster VisionWorker already uses
        )
        state.capture_service.start()
        state.vision_worker.start()
        state.wiring_worker.start()                   # third background thread, same start/stop symmetry
        try:
            yield
        finally:
            state.wiring_worker.stop()
            state.vision_worker.stop()
            state.capture_service.stop()
            state.detector.close()
            state.serial_link.close()                 # paired with detector.close(), same teardown discipline
            broadcaster.unbind_loop()

    app.state.component_store = comp_store
    app.state.wiring_state = wiring_state
    app.state.wiring_jobs = wiring_jobs
    app.state.serial_link = serial_link

    app.include_router(api_routes.router)
    app.include_router(api_calibrate.router)
    app.include_router(api_wiring.router)      # NEW, alongside the four existing routers
    app.include_router(api_video.router)
    app.include_router(api_ws.router)
    mount_frontend(app, Path(config.frontend_dist))
```

**Thread model, decided explicitly (per B's argument, verified against the real `VisionWorker`/`CaptureService` fault-isolation pattern):** `WiringWorker` is a **new thread**, never folded into `VisionWorker._run()`. Reason: an `i2c_scan` sweeping 127 addresses or a `pulse_in` waiting up to tens of ms would stretch `VisionWorker`'s tick cadence if it shared that loop, degrading the *already-shipped, already-tested* capability① pose smoothing/tracking cadence — and `CaptureService`/`VisionWorker`'s existing `except Exception` guards are deliberately built to keep camera and detection faults from taking each other down; coupling a flaky USB-serial link into that same loop would break that isolation discipline for no benefit.

### 2.2 `config.py` additions (all default-valued — existing `config.yaml` files keep working unmodified)

```python
class SerialConfig(BaseModel):
    mode: Literal["mock", "serial"] = "mock"
    port: str = "auto"
    baud: int = 115200
    cmd_timeout_s: float = 2.0

class WiringConfig(BaseModel):
    vision_check_hz: float = 5.0            # throttled well below detection_hz=30
    debounce_s: float = 1.5                 # vision pattern must be stable this long before an electrical retest fires
    retest_min_interval_s: float = 5.0      # hard floor even if debounce logic misfires
    heartbeat_retest_s: float | None = 45.0 # slow periodic retest for "looks fine but silently died"; None disables
    electrical_confidence_half_life_s: float = 20.0
    electrical_confidence_floor: float = 0.25
    job_hard_timeout_s: float = 8.0

# AppConfig += serial: SerialConfig, wiring: WiringConfig, active_plan: str | None = None
```

`BOARDVISION_SERIAL__PORT=COM5` and `BOARDVISION_WIRING__DEBOUNCE_S=2.0` work immediately via the existing nested env-override mechanism — no new plumbing.

---

## 3. Data flow diagrams

### 3a. Electrical self-test round-trip — host ↔ Device Runtime, USB CDC serial

Consensus wire format across all three independent designs (unanimous, and matching the deck's own stated Phase-1 rationale — *"第一版採 USB Serial —— 最穩定、最容易開發與除錯"*): newline-delimited JSON, one request/response pair per line, correlated by an incrementing `id`.

```
app/serial/link.py                                Device Runtime firmware (STM32U585, USB CDC)
───────────────────                                ──────────────────────────────────────────
{"id":41,"cmd":"run","steps":[
  {"op":"pin_mode","pin":"D7","mode":"out"},
  {"op":"pin_mode","pin":"D8","mode":"in"},
  {"op":"digital_write","pin":"D7","value":0},
  {"op":"delay","ms":2},
  {"op":"pulse_out","pin":"D7","level":1,"us":10},
  {"op":"pulse_in","pin":"D8","level":1,"timeout_us":30000,
   "capture":"echo_us"}
]}\n                                   ────────►
                                        ◄────────  {"id":41,"ok":true,
                                                      "captures":{"echo_us":148},
                                                      "steps":[{"op":"pin_mode","ok":true}, ...]}\n
```

- Each `op` is one of a **closed vocabulary** (§4.2) — the firmware's dispatch table is fixed size regardless of how many `component.json` files exist.
- Each step carries its own bound (`pulse_in`'s `timeout_us`, `i2c_scan`'s fixed 1–127 sweep) — the command as a whole always replies; a single stuck step reports `"ok":false,"captures":{"echo_us":null}` for that step only, never hangs the link.
- Host-side `cmd_timeout_s` (default 2.0s) synthesizes a local `{"ok":false,"error":"timeout"}` if no reply line arrives; `SerialLink` then attempts reconnect on the next call rather than raising into `WiringWorker`'s loop.

### 3b. Combined vision + electrical evaluation loop (the `WiringWorker` continuous spine)

```
every tick, throttled to wiring.vision_check_hz:
    det = detection_state.get()                       # published by VisionWorker, NOT recomputed here
    if det.tracking == "searching":
        wiring_state.set(all-roles -> "unverified")   # board not even visible; nothing to say yet
        continue

    frame = frame_bus.get_latest(newer_than=my_cursor) # independent read cursor, same FrameBus, no contention
    for role, pin_id in plan.pin_assignment.items():
        (x, y) = det.pin(pin_id).xy                    # reused pixel coords from capability①
        vision_evidence[role] = presence_probe(frame, x, y)   # cheap, local patch heuristic

    changed = vision_pattern_changed(vision_evidence, last_stable)
    if changed:                     debounce_timer.reset()
    elif debounce_timer.elapsed() >= wiring.debounce_s
         and rate_limit_elapsed(wiring.retest_min_interval_s):
        enqueue_electrical_retest(plan)                 # the ONLY automatic trigger path
    if wiring.heartbeat_retest_s and stale_beyond(heartbeat_retest_s):
        enqueue_electrical_retest(plan)                 # catches "looks unchanged but died electrically"

    drain_force_verify_queue()   # explicit POST /verify requests, always serviced first, bypassing debounce

    verdict = evaluator.evaluate(plan, vision_evidence, electrical_cache, wiring.confidence_*)
    wiring_state.set(verdict)
    if verdict materially changed or an electrical test just completed:
        publish({"type": "wiring_check", **verdict.to_wire()})   # same DetectionBroadcaster as VisionWorker
```

Confidence decay per role (adopted from B, only meaningful because state is now continuously live):

```
vision_component     = det.pin(pin_id).confidence  if tracking != "searching" else 0
electrical_component = floor + (1-floor) * exp(-ln(2) * age_s / half_life_s)     # ages toward floor, never to 0
role_confidence       = vision_component * electrical_component
role_status:
    vision says absent                                 → fail, class="wiring_absent"
    vision present + electrical fresh-fail              → fail, class="electrical_signature_mismatch"
    vision present + electrical fresh-pass               → pass
    result exists but past freshness window               → keep old status, flag "stale": true   (same honesty idiom as WS "tracking":"stale")
    never electrically tested + spec says required        → "unverified"
    role's spec says verified_by=["indirect_via_paired_test"] or ["not_testable"] → honest non-boolean (§4.3)
```

### 3c. AI-facing interface, end to end

```
AI Agent (MCP tool-caller or plain HTTP)
   │
   ├─ 1. GET /api/components/hc-sr04              (discover required roles — cheap, static)
   ├─ 2. GET /api/boards/arduino-uno-q             (existing ① endpoint — discover real pin capabilities)
   │        (agent proposes pin_assignment itself, or calls suggest_pin_assignment — capability③'s hook)
   ├─ 3. POST /api/wiring/plans  {component_id, pin_assignment}
   │        → resolver.resolve_plan() — sync, <1ms, no hardware touched
   │        → 200 {ok:true, plan_id} or {ok:false, error:"incompatible_assignment", ...}  (same 200+ok convention as POST /api/calibrate)
   │
   ├─ 4. GET /api/wiring/plans/{plan_id}/verdict   ──────► reads app.state.wiring_state.get() directly
   │◄───────────────────────── 200, {overall, roles[], diagnosis[]}   (SYNCHRONOUS, cheap — WiringWorker already computed it)
   │        (agent may call this many times across a conversation turn at ~zero cost)
   │
   ├─ 5. (only when freshness truly matters) POST /api/wiring/plans/{plan_id}/verify
   │◄───────────────────────── 202 {job_id, status:"running", poll_url}   (ASYNC — bypasses debounce/rate-limit on purpose)
   ├─ 6. GET /api/wiring/jobs/{job_id}             (poll, or the handler internally awaits up to an optional wait_s)
   │◄───────────────────────── {status:"done", result: <same verdict shape>}
   │
   └─ (optional) subscribe /ws/detections, filter type=="wiring_check"  — same socket the frontend already uses
```

---

## 4. The wiring-plan / component-spec data model

### 4.1 `schemas/component-spec.schema.json`

Mirrors `board-profile.schema.json`'s own conventions (`$defs`, `i18nText`, `additionalProperties:false`), backed at runtime by `backend/app/components/models.py`'s `StrictModel` (extra="forbid") the same way `profiles/models.py` backs `board-profile.schema.json`.

### 4.2 The closed test-op vocabulary (the DSL, adopted from Proposal C — this is what makes "new module = spec file only, zero firmware/backend code" true)

| op | args | effect | maps to |
|---|---|---|---|
| `pin_mode` | pin, mode(`in`\|`out`\|`in_pullup`) | `pinMode()` | any digital_io pin |
| `digital_write` | pin, value | `digitalWrite()` | |
| `digital_read` | pin → capture | `digitalRead()` | |
| `pulse_out` | pin, level, us | drive pin then return to idle | trigger pulses |
| `pulse_in` | pin, level, timeout_us → capture | `pulseIn()`, `null` on timeout | echo/loopback reads |
| `analog_read` | pin → capture | `analogRead()` | ADC roles |
| `i2c_scan` | bus → capture(list) | 1–127 address sweep on the **dedicated** SDA/SCL (`i2c0`) — deliberately *not* A4/A5, per `board.json`'s own note that on this board A4/A5 map to a second, distinct STM32 I2C peripheral, not the same MCU pins as dedicated SDA/SCL | |
| `i2c_read` | bus, addr, reg, len → capture | register read | |
| `delay` | ms | `delay()` | sequencing |

A `test_procedure.steps[]` is *only* ever a sequence of these ops — the firmware's dispatch table has exactly these 8 entries regardless of how many `component.json` files exist, and this is also the safety property that lets capability③'s AI planner *compose* a test procedure without ever being trusted to write arbitrary code against real hardware.

### 4.3 `profiles/components/hc-sr04/component.json` (concrete — pin choice matches `board.json`'s own literal usage note on D7: *"超音波模組 HC-SR04 的 Trig/Echo 腳位"*)

```jsonc
{
  "schema_version": "1.0",
  "id": "hc-sr04",
  "version": "1.0.0",
  "category": "sensor",
  "vendor": "generic",
  "name": { "zh-TW": "HC-SR04 超音波測距模組", "en": "HC-SR04 Ultrasonic Distance Sensor" },

  "pin_roles": [
    {
      "role": "VCC", "function": "power_in",
      "voltage": { "nominal": 5.0, "min": 4.5, "max": 5.5 },
      "board_requirements": { "any_of": [ { "capability": { "type": "power", "rail": ["5v"] } } ] },
      "verified_by": ["indirect_via_paired_test"],
      "note": { "zh-TW": "板端無法直接量測供電；TRIG/ECHO 功能測試成功即間接證明供電存在",
                 "en": "Not directly measurable from the board side; a successful TRIG/ECHO round-trip indirectly proves power is present" }
    },
    {
      "role": "GND", "function": "ground",
      "board_requirements": { "any_of": [ { "capability": { "type": "power", "rail": ["gnd"] } } ] },
      "verified_by": ["indirect_via_paired_test"]
    },
    {
      "role": "TRIG", "function": "digital_out",
      "board_requirements": { "any_of": [ { "capability": { "type": "digital_io" } } ] },
      "verified_by": ["electrical_test"]
    },
    {
      "role": "ECHO", "function": "digital_in",
      "board_requirements": { "any_of": [ { "capability": { "type": "digital_io" } } ] },
      "electrical_constraints": { "external_signal_voltage": 5.0, "require_pin_electrical": { "five_volt_tolerant": true } },
      "compatibility_notes": [
        { "severity": "danger", "text": { "zh-TW": "ECHO 訊號為 5V — 指定的腳位必須耐 5V 輸入，否則會損壞板子",
                                            "en": "ECHO is a 5V signal — the assigned pin must be 5V-input-tolerant or the board will be damaged" } }
      ],
      "verified_by": ["electrical_test"]
    }
  ],

  "test_procedure": {
    "engine": "device-runtime-v1",
    "steps": [
      { "op": "pin_mode",      "pin_role": "TRIG", "mode": "out" },
      { "op": "pin_mode",      "pin_role": "ECHO", "mode": "in" },
      { "op": "digital_write", "pin_role": "TRIG", "value": 0 },
      { "op": "delay",         "ms": 2 },
      { "op": "pulse_out",     "pin_role": "TRIG", "level": 1, "us": 10 },
      { "op": "pulse_in",      "pin_role": "ECHO", "level": 1, "timeout_us": 30000, "capture": "echo_us" }
    ],
    "assertions": [
      { "capture": "echo_us", "op": "not_null", "on_fail": { "code": "no_echo_pulse", "severity": "danger",
          "message": { "zh-TW": "ECHO 沒有偵測到回波脈波", "en": "No echo pulse detected on ECHO" } } },
      { "capture": "echo_us", "op": "in_range", "min": 58, "max": 25000, "on_fail": { "code": "echo_out_of_range", "severity": "warning",
          "message": { "zh-TW": "有回波但長度不合理，可能是感測器故障或雜訊", "en": "Echo present but implausible duration — sensor fault or noise" } } }
    ]
  },

  "vision_presence": { "roles_checked": ["VCC", "GND", "TRIG", "ECHO"], "method": "pin_occlusion_v1" }
}
```

### 4.4 `resolve_plan()` against the real `arduino-uno-q` profile

`app/components/resolver.py` walks each `pin_role.board_requirements` against `BoardProfile.pin_by_id(assigned).capabilities` / `.electrical` — fields that **already exist** on every pin in `board.json`, no schema change needed. Two verified real outcomes:

- `{"TRIG":"D7","ECHO":"D8","VCC":"5V","GND":"GND_P1"}` → `ok:true`. D7 and D8 are plain `digital_io` pins with no PWM/SPI/UART overlap and `electrical.five_volt_tolerant:true`; D7's own `usage_examples` in `board.json` already names this exact use.
- `{"ECHO":"D3", ...}` → `ok:false`, `error:"incompatible_assignment"`, citing D3's real, already-authored danger text verbatim: *"任何模式下都不可接 5V — D3 為 TT 型 I/O，最高僅耐 3.6V"* (`electrical.five_volt_tolerant:false`). Caught before any hardware or camera is touched.

A resolved plan pins the exact `"hc-sr04@1.0.0"` it was checked against (semver — adopted from C); `ComponentStore` caches by `"{id}@{version}"`, mirroring `ProfileStore`'s per-`board_id` cache. MINOR bumps to a spec are safe to silently re-resolve against; MAJOR bumps (a required role changes) force explicit re-resolution — this reproducibility guarantee is exactly the "可重現的專案狀態" moat item, extended from boards to modules.

```jsonc
// profiles/plans/arduino-uno-q/demo-hcsr04.json
{
  "plan_id": "demo-hcsr04", "board_id": "arduino-uno-q", "component_spec": "hc-sr04@1.0.0",
  "pin_assignment": { "VCC": "5V", "GND": "GND_P1", "TRIG": "D7", "ECHO": "D8" },
  "compatibility": { "ok": true, "checked_roles": {
    "VCC": {"ok": true}, "GND": {"ok": true}, "TRIG": {"ok": true},
    "ECHO": {"ok": true, "reason": "D8.electrical.five_volt_tolerant == true"} } },
  "resolved_at_ms": 1721990000000
}
```

---

## 5. The AI-facing interface, precisely specified

### Sync vs. async — final decision

**Not one call, three cleanly separated primitives**, because the live-state worker (§3b) changes what "cheap" means for the read path:

1. **`GET /api/wiring/plans/{plan_id}/verdict` — synchronous, always fast.** It reads `app.state.wiring_state.get()`, an in-memory object `WiringWorker` maintains continuously — the same cost class as `GET /api/config` reading `app.state.config`. An agent can call this repeatedly within one reasoning turn ("did that fix it? and now?") at effectively zero marginal cost and zero hardware risk, because it never itself triggers a test.
2. **`POST /api/wiring/plans/{plan_id}/verify` — explicitly asynchronous (202 + `job_id` + poll, or an optional `wait_s` bounded-wait convenience wrapper on top).** This is the only path that bypasses the debounce/rate-limit — its entire reason to exist is "I explicitly want a fresh, guaranteed-just-now electrical test," which is inherently the slow, disruptive operation. It is *also* forced to be async by implementation reality, not just API taste: the serial port has exactly one owner thread (`WiringWorker`); a REST handler physically cannot execute the serial round-trip inline, it can only hand the request to that thread's queue and wait for the result.
3. **`POST /api/wiring/plans` and `POST /api/wiring/checks`** (ad-hoc, unregistered pin combos — C's contribution) compile down to the same two primitives: plan resolution is always synchronous (<1ms, pure data), and an ad-hoc check is just "register a throwaway plan, then call `verify`."
4. **WS push** (`type:"wiring_check"` over `/ws/detections`) is a fourth, complementary channel for anyone — human frontend or AI agent — who wants to react to changes without polling at all.

This resolves the sync/async tension that dominated all three original proposals: it isn't a single global choice, it's a property of *which* primitive is called, and the split falls directly out of adopting B's continuous worker.

### Endpoint surface

| Endpoint | Sync/async | Purpose |
|---|---|---|
| `GET /api/components` / `/{id}` | sync | discovery — spec catalog |
| `POST /api/wiring/plans` | sync | resolve+validate a `pin_assignment`; always HTTP 200 + `ok:true/false` (same convention as the existing `POST /api/calibrate`) |
| `GET /api/wiring/plans/{plan_id}/verdict` | **sync, cheap** | the primary AI read path |
| `POST /api/wiring/plans/{plan_id}/verify` | **async, job+poll** | explicit forced re-test |
| `GET /api/wiring/jobs/{job_id}` | sync | poll a verify job |
| `POST /api/wiring/checks` | sync-wrapper-over-async | ad hoc (unregistered) pin combo, `wait_ms` optional |

MCP tools (`app/api/mcp_tools.py`) are 1:1 thin wrappers over exactly these six calls — `list_component_specs`, `suggest_pin_assignment` (capability③'s hook, running `resolver.py`'s matcher in the generate direction), `create_wiring_plan`, `get_wiring_verdict`, `force_verify`, `check_wiring_adhoc` — no separate business logic, so the contract behaves identically whether the caller is MCP or plain HTTP.

### Response shape — the diagnostic core (merging A's stable-code taxonomy, B's separated vision/electrical evidence, C's three-way failure-class split)

```jsonc
// GET /api/wiring/plans/demo-hcsr04/verdict → 200
{
  "plan_id": "demo-hcsr04", "board_id": "arduino-uno-q", "component_spec": "hc-sr04@1.0.0",
  "board_tracking": "locked",
  "overall": { "status": "fail", "confidence": 0.58, "as_of_ms": 1721990401234.0, "age_ms": 180 },
  "roles": [
    { "role": "VCC", "pin_id": "5V", "status": "pass",
      "vision": { "present": true, "confidence": 0.91 },
      "electrical": { "applicable": false, "reason": "indirect_via_paired_test" } },
    { "role": "GND", "pin_id": "GND_P1", "status": "pass",
      "vision": { "present": true, "confidence": 0.89 },
      "electrical": { "applicable": false, "reason": "indirect_via_paired_test" } },
    { "role": "TRIG", "pin_id": "D7", "status": "pass", "confidence": 0.90,
      "vision": { "present": true, "confidence": 0.93 },
      "electrical": { "tested": true, "ok": true, "age_ms": 334 } },
    { "role": "ECHO", "pin_id": "D8", "status": "fail", "confidence": 0.88,
      "class": "wiring_absent",
      "diagnosis": "VISION_NOT_PRESENT",
      "vision": { "present": false, "confidence": 0.12 },
      "electrical": { "tested": true, "ok": false, "diagnostic_code": "no_echo_pulse", "captured": { "echo_us": null }, "timeout_us": 30000 },
      "message": { "zh-TW": "D8 沒有偵測到回波脈波，鏡頭在該腳位也沒看到接線 — 請確認 ECHO 線已插入 D8",
                    "en": "No echo pulse on D8, and the camera sees no wire there — check that ECHO is plugged into D8" },
      "suggested_action": { "zh-TW": "確認有一條線從感測器 ECHO 接到板子 D8。", "en": "Confirm a wire runs from the sensor's ECHO pin to board pin D8." } }
  ]
}
```

**Diagnosis taxonomy** (stable codes an LLM can branch on, adopted from A, organized by stage):

| Stage | Codes |
|---|---|
| Plan build (no I/O, <1ms) | `UNKNOWN_COMPONENT`, `MISSING_ROLE`, `PIN_CAPABILITY_MISMATCH`, `VOLTAGE_INCOMPATIBLE`, `PIN_NOT_TESTABLE` (BOOT/reset pins), `BOARD_MISMATCH` |
| Live evaluation | `VISION_NOT_PRESENT` → `class:"wiring_absent"` · `ELECTRICAL_NO_RESPONSE` / `ELECTRICAL_UNEXPECTED_LEVEL` (present-but-electrically-wrong) → `class:"electrical_signature_mismatch"` · `ELECTRICAL_DEVICE_LINK_UNAVAILABLE` |
| Job | `timeout` (job-level, not per-role) |

The **`class`** field is the load-bearing addition: `wiring_absent` (nothing there, camera agrees) vs. `electrical_signature_mismatch` (camera sees something, electronics disagree) point to *different* remediation — "plug it in" vs. "check for a dead sensor or swapped wires" — and this is precisely the "diagnostic detail, not just pass/fail" the brief asked for. `not_testable`/`indirect_via_paired_test` on VCC/GND is an honest, explicit non-boolean value — never a silently-assumed pass, and a known, stated Phase-1/2 limitation (no direct rail-current sensing) rather than a hidden gap.

---

## 6. Reuse vs. extension of the existing WS/REST surface — confirmed non-breaking

- **WS `/ws/detections`**: exactly one new `type` value, `"wiring_check"`, broadcast through the **existing** `DetectionBroadcaster.publish_threadsafe()` — verified by reading `main.py`: `broadcaster` is already constructed once and handed to `VisionWorker` as its `publish` callback; `WiringWorker` becomes its second caller, not a second broadcaster. `docs/api-contract.md` §2 (verified) already states *"`type` 欄位是擴充點：未來新增 `wiring_check`、`telemetry` 等訊息型別，前端忽略未知 type"* — this design fills in exactly the name the contract already reserved. `hello`, `detection` shapes: unchanged.
- **REST**: entirely new paths under `/api/components/*` and `/api/wiring/*`, one new router (`api_wiring.router`) registered alongside the four existing ones (`api_routes`, `api_calibrate`, `api_video`, `api_ws`), verified against the real registration order in `main.py`. `GET /api/config`, `GET /api/boards/*`, `POST /api/query`, `POST /api/calibrate`, `GET /video` all unchanged.
- **`POST /api/wiring/plans`** deliberately copies `POST /api/calibrate`'s own established convention (verified in `docs/api-contract.md` §6): real HTTP error codes reserved for malformed request bodies; every expected outcome, including validation failure, is HTTP 200 + `ok:true/false`.
- **`BoardDetector`/`FrameBus`/`DetectionState`**: untouched. `vision_presence.py` only *reads* `DetectionState.get()` and `FrameBus.get_latest(newer_than=...)` — both already built as multi-reader latest-value holders (the MJPEG endpoint is already a second independent `FrameBus` reader today), so a third reader adds no new synchronization surface.
- **88 existing backend tests**: untouched files, no existing signature changes — expected to pass unmodified; new modules ship with their own test suite using `MockSerialLink` (mirroring how `MockDetector` lets the CV-independent 88 tests run without hardware today).

---

## 7. Firmware-side architecture sketch (Device Runtime test firmware)

Target: dedicated verification image flashed to the UNO Q's STM32U585 (Arduino core over Zephyr), distinct from the user's own sketch — consistent with the deck's Device Runtime framing and with capability③ eventually owning the flash-test-flash-final cycle.

**State machine:**

```
BOOT → IDLE (all header pins high-Z; listen for one JSON line on USB CDC)
IDLE ── {"cmd":"hello"} ──────────────────────────► reply identity/version → IDLE
IDLE ── {"cmd":"run","steps":[...]} ──────────────► EXECUTING
EXECUTING: for each step, dispatch by `op` (§4.2 vocabulary only);
           each op has its own internal bound (pulse_in's timeout_us,
           i2c's Wire timeout) so no single step can hang the command
        → reply {"id","ok","captures","steps":[...]} → IDLE
On re-entering IDLE after any command: all pins touched by that command
are forced back to INPUT/high-Z — a test never leaves a pin actively
driving after it completes (never fight a sensor or short something).
Watchdog: if the host goes silent > 10s, force all claimed pins to
high-Z regardless — protects against a crashed backend or a yanked
USB cable leaving pins in an unsafe drive state indefinitely.
```

**Safety cross-check, belt-and-suspenders with `resolver.py`'s compile-time gate:** the firmware independently refuses `pin_mode`/`digital_write` against any pin whose role in the real `board.json` is `boot` or `reset` — concretely, the `BOOT` pin at `JANALOG` index 0 (capability `type:"boot"`, `board.json`'s own danger warning: *"開機/重置期間請勿拉高此腳，否則 MCU 會進入系統 bootloader"*) — so a malformed or adversarial plan can never reach the wire even if the host-side check were somehow bypassed.

Explicitly deferred (v1 scope, matching the deck's own stated USB-Serial-first choice): SPI/UART/OTA ops, Wi-Fi transport, running the user's real sketch concurrently with the test image (that unification is capability③'s territory, not this design's).

---

## 8. Milestones

Continuing the numbering after Board Vision's completed **M0–M7** (capture/MJPEG shell → pin DB/reference → mock detector/overlay → real CV static pose → temporal tracking → capability card/filter/NL query → demo polish → `POST /api/calibrate` guided real-board calibration). Each milestone below is independently demoable and builds strictly on top of, never duplicates, M0–M7.

**M8 — Device Runtime firmware + host serial link (Phase 1, no camera)**
Deliver `firmware/wiring-test-fw/` implementing the §4.2/§7 op set and state machine; `app/serial/{protocol,link,mock_link,factory}.py`.
*Acceptance:* real UNO Q flashed with the test firmware — `hello` round-trips a real version string; jumpering two digital pins and issuing `pulse_out`/`pulse_in` correctly detects presence/absence of the jumper deterministically; `i2c_scan` on the dedicated bus finds a real device address. `MockSerialLink` reproduces identical response shapes so all 88 existing backend tests remain green and new unit tests need no hardware.

**M9 — Component spec + resolver (Phase 3 data model, still no live state)**
Deliver `app/components/{models,store,resolver}.py`, `schemas/component-spec.schema.json`, real `profiles/components/hc-sr04/component.json`, `GET /api/components[/​{id}]`, `POST /api/wiring/plans`.
*Acceptance:* `resolve_plan("hc-sr04", <real arduino-uno-q profile>, {"ECHO":"D3",...})` deterministically returns `ok:false, error:"incompatible_assignment"`, citing D3's real `five_volt_tolerant:false` danger text; `{"ECHO":"D8",...}` resolves `ok:true`. Zero hardware, zero camera — pure data, curl-demoable against the running backend.

**M10 — `WiringWorker` continuous live state (Phase 2, the runtime-state-first core)**
Deliver `app/wiring/{state,vision_presence,electrical,evaluator,worker,jobs}.py`, wired into `main.py`'s lifespan alongside M8's `MockSerialLink`/M9's resolved plan.
*Acceptance:* simulating "vision presence at ECHO's pixel location disappears" flips that role to `fail` within one vision tick (<200ms) **without triggering any additional serial call** (assert mock-link call count unchanged). Simulating "presence returns and stays stable past `debounce_s`" triggers **exactly one** electrical retest (call count +1, not +N). A WS test client subscribed to `/ws/detections` receives interleaved `detection` and `wiring_check` messages without altering the existing `detection` message rate or shape — full existing 88-test suite stays green.

**M11 — AI-facing REST/MCP surface**
Deliver `app/api/wiring.py`'s full endpoint set (§5), `app/api/mcp_tools.py`, `docs/api-contract.md` §7 addition.
*Acceptance:* a scripted fake-agent harness lists components, resolves and registers a plan, reads `verdict` synchronously multiple times with no measurable extra latency or hardware calls, calls `verify` and correctly observes the 202→poll→done lifecycle, and gets a correctly `ok:false`-with-diagnosis result for an ad-hoc unregistered pin combo via `POST /api/wiring/checks`.

**M12 — End-to-end demo circuit (headline capability② demo)**
Real HC-SR04 wired to `5V/GND_P1/D7/D8` on a physical UNO Q running M8's firmware.
*Acceptance script:* nothing wired → `unverified`; power+ground only → `partial`, `diagnosis` names the missing TRIG/ECHO roles specifically; TRIG+ECHO connected → after one debounce window, `pass` with rising confidence; mid-demo, physically unplug only the ECHO wire → vision flips that role to `fail` within one tick, followed by an electrical retest that confirms it independently; swap TRIG/ECHO wires instead of unplugging → vision stays `present` on both but electrical flips to `fail`/`electrical_signature_mismatch` — a **visibly different** diagnosis than the unplugged case, proving the three-way split earns its keep.

**M13 — AI-agent consumption validation**
*Acceptance:* against the live M12 rig, deliberately break one wire; ask a real function-calling LLM "why isn't my ultrasonic sensor working?" through the M11 tool contract. Its answer must correctly name the specific broken role and cite evidence consistent with the returned `class`/`diagnosis` (e.g., correctly distinguishing "it's unplugged" from "it's plugged in but not responding") — empirically validating the AI-Agent-native contract, not just asserting it by construction. This is the concrete, testable satisfaction of the "consumable by an AI model" requirement.

**M14 (stretch) — `WiringPanel.tsx`**
Reuses the existing SVG pin-overlay machinery, colors pins by live role/verdict, subscribes to `wiring_check`. Explicitly last and optional — per all three original proposals' agreement, the AI-facing contract (M11–M13) is the actual moat deliverable; the UI is polish, not proof.

---

## 9. Explicit tradeoffs and rejected alternatives

**1. Rejected: fold wiring evaluation into `VisionWorker._run()` instead of a new thread.**
Simpler at first glance — no new `FrameBus` reader to reason about — but the serial round-trip (`i2c_scan`'s 127-address sweep, `pulse_in`'s up-to-30ms timeout) stretching between `detector.detect()` calls would directly degrade the *already-shipped, already-tested* capability① pose smoothing/tracking cadence, and would break the deliberate fault isolation `CaptureService`/`VisionWorker` already have (camera errors and detection errors don't take each other down today; coupling a flaky USB link into the same loop would undo that).

**2. Rejected: fully synchronous AI interface — every `check_wiring` call runs a real electrical test inline, no continuous state at all.**
The most intuitive design. Rejected because it directly reintroduces the abuse case the deck's own "camera is free, electrical test is not" framing warns against: an AI agent that asks "is it fixed now?" every few seconds becomes, under this design, a source of repeated disruptive electrical pokes. It also throws away the free signal that `VisionWorker` is running at 30Hz regardless of whether anyone asks — a lapsed wire between two queries would go unnoticed until the next query, whereas the adopted design's `WiringWorker` proactively pushes the change the moment it's detected.

**3. Rejected: per-role, hardcoded named test "methods" (`gpio_pulse_echo`, `i2c_scan_match`, ...) instead of a generic op-sequence DSL.**
Simpler to write a first spec, but every new sensor category would require new backend/firmware special-casing, defeating the "new module = spec file only" goal, and — more importantly for the stated future — it is unsafe to hand an LLM planner (capability③) the ability to invent arbitrary named test methods that map to arbitrary firmware code paths. A small, closed, interpretable primitive vocabulary is safe to let an AI *compose from*; it is not safe to let an AI *extend*.

**4. Rejected: model `ComponentSpec` as a variant `BoardProfile` reusing `board.json`'s schema.**
`BoardProfile` carries board-specific concepts a module doesn't have (camera reference image, board-mm outline, a single `schema_version`) and lacks independent per-module semver, which is needed for reproducible plan instances. A sibling, independently-versioned family keeps both models honest.

**5. Rejected: binary/protobuf framing for the serial link.**
Negligible throughput benefit at these command rates (single digits per second), adds a codegen toolchain on both firmware and host, breaks the plain-JSON convention the rest of the system already uses (`docs/api-contract.md`, `POST /api/calibrate`'s response envelope), and loses "read it with a plain serial terminal" debuggability — which is the deck's own explicitly stated reason for choosing USB Serial first. Kept as a clean seam in `app/serial/protocol.py` should raw waveform streaming ever be needed later.

**6. Rejected: a second, dedicated WS endpoint (e.g. `/ws/wiring`) instead of reusing `/ws/detections`.**
Cleaner schema separation on paper, but `docs/api-contract.md` §2 already designed the `type` field as exactly this extension point and explicitly pre-named `wiring_check`; the frontend's reconnect/backoff state machine is written for "one connection, many types," and `wiring_check` events are low-frequency (event-driven, not 30Hz) so there's no bandwidth argument for splitting the channel.

**Known, stated gap carried forward honestly (not a rejected alternative — a real Phase-1/2 limitation):** VCC/GND roles have no direct electrical proof (no rail-current sensing primitive) and are reported `electrical.applicable:false / reason:"indirect_via_paired_test"` rather than a silent `pass`. A future `analog_read`-based rail-sense primitive (resistor divider into a spare ADC pin) could close this later without changing the response schema — `not_testable`/`indirect_via_paired_test` is a distinct, already-reserved value, not a hidden assumption.

**Phase 4 extension point (explicitly not designed in depth here):** full breadboard hole-grid + wire-endpoint tracing will replace `vision_presence.py`'s pixel-patch heuristic with a real electrical-node-identity graph. Nothing else changes: `evaluator.py`, `WiringWorker`'s loop, and the AI-facing `verdict` shape are stable — the `class` taxonomy simply grows a new value (e.g. `wrong_node`, distinguishing "connected to the wrong breadboard rail" from today's binary "connected/not connected").
