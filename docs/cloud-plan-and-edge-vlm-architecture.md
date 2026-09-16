# Capability ③ — 雲端 GuidancePlan 產生 + 邊緣 VLM 即時旁述：三層信任架構設計

延續 [api-contract.md](api-contract.md)（既有 REST/WS 契約）、[wire-recognition-design.md](wire-recognition-design.md)（HSV 分色管線 + snap_endpoint）、[wiring-verification-architecture.md](wiring-verification-architecture.md)（能力②：WiringWorker、ComponentSpec DSL、診斷分類法，M8–M14）、[color-agnostic-wire-and-guidance-design.md](color-agnostic-wire-and-guidance-design.md)（Stage A' + GuidanceStep/evaluate_guidance_step 純古典打勾引擎，M20–M24）。

本文件回答使用者的兩個新需求，並把它們接進既有系統：

1. **雲端**：由 LLM 為使用者設計接線引導計畫（GuidancePlan 產生）
2. **邊緣 VLM**：即時觀看直播畫面、提供互動式旁述/提示效果

Design-only：撰寫本文件時未修改或建立 `board-vision` 下任何程式檔案。

---

## 0. 三層信任/延遲模型（本設計的憲法，所有後續決策由此推導）

| | **Tier 0 — 古典幾何** | **Tier 1 — 邊緣 VLM** | **Tier 2 — 雲端 LLM** |
|---|---|---|---|
| 執行者 | VisionWorker（~30Hz）、WireTraceWorker（~2Hz）、guidance 引擎、（能力②）WiringWorker | VLMWorker（新，本文件 §4）+ 本機 VLM runtime | 雲端 Plan Service（新，本文件 §3） |
| 延遲 | 毫秒級 | 次秒到數秒（GPU 4B 約 1.5–3s/幀；CPU-only 只允許使用者主動觸發）| 數秒（含驗證重試可到 ~20s） |
| 權威性 | **唯一權威**。打勾/打叉（`correct`/`wrong_pin`）、wire endpoint、電氣 verdict 全部只由這層決定 | **純 advisory**。輸出永遠標示 `authority:"advisory"`，**在任何條件下都不能改寫 Tier 0 的判定**（§4.5 硬規則） | **從不被信任**。輸出是「候選計畫」，必經本地 deterministic PlanValidator（§3.4）全數通過才允許執行 |
| 看得到什麼 | 每一張即時影格 | 本機 FrameBus 的 keyframe（**影像不出這台 PC**） | **永遠看不到即時影像**。只收文字（goal、board_id、pin 表、ComponentSpec 全文）；唯一例外是使用者明確按下「拍照辨識」送出的單張靜態照片 |
| 離線 | 完全可用（既有性質，保持不變） | 完全可用（本機推論） | 不可用 → 降級為 cached/pre-authored plans（§6） |

**證據基礎（既定約束，不重議）**：麵包板線材路徑追蹤最佳模型 71%（arXiv 2605.15672）；局部視覺差異偵測最佳 recall 40.7%（DiffSpot, arXiv 2605.29615）；本專案本週實測 A/B：手機 VLM 自信宣稱藍線插在 5V，實際變焦查證 5V 插座是空的——自信、錯誤、不可追溯。而 `snap_endpoint()` 的幾何答案精確、免費、已在真實板子上驗證。雲端側同理：HWE-Bench 顯示板級設計靜態規則檢查最佳也只有 77.73% 通過率、完全正確率 <10%（arXiv 2603.18102），但失敗型態（幻覺腳位、電壓違規、一腳多用）**恰好全部落在確定性 lint 的射程內**（CircuitLM, arXiv 2601.04505）。所以三層架構的哲學跟本專案既有設計完全同一句話：**LLM 生成、機器驗證、advisory 與 authoritative 欄位在 schema 層面就分開、never guess。**

---

## 1. 一段話總覽

雲端 Plan Service 用 constrained-decoding structured output 把「goal 文字 + board.json pin 表 + ComponentSpec 全文（精確查表，不用向量 RAG）」變成一份 **GuidancePlan** JSON；本地 **PlanValidator**（純程式、零模型）逐項檢查 schema、腳位存在性、電氣安全（直接引用 `board.json` 的 `electrical.five_volt_tolerant` 等機讀事實）、能力匹配，任何一項不過就整份拒收並附具名理由。通過的計畫交給新的 **PlanRuntime** 狀態機，逐步把 `steps[]` 餵進 M22 已設計好的 `evaluate_guidance_step()`（純古典、字串比較）執行，`correct` 穩定兩個 tick 自動推進，並持續回頭核對已完成步驟的腳位仍被佔用；進度以新 WS 訊息 `plan_progress` 推播。同時，新的 **VLMWorker** 以 WireTraceWorker 的既有 pattern（自己的 thread、自己的節奏、FrameBus 第五個獨立 reader、永不阻塞幾何管線）連接本機 OpenAI 相容 VLM runtime（llama-server/Ollama；Snapdragon 上 GenieX），在四類觸發條件下產生 `vlm_insight` advisory 訊息與 M24 規格的 `ai_hint`——但**沒有任何一條資料流允許 VLM 輸出改變 guidance status、wire endpoint 或 plan 驗證結果**。即時影像預設永遠不離開這台 PC。

---

## 2. GuidancePlan：一種計畫格式，同時服務導引（能力③）與電氣驗證（能力②）

### 2.1 設計原則

- `steps[]` 的每一步就是一個 M22 `GuidanceStep`（`step_id`/`expected_pin_id`/`expected_role`/`component_id`/`hint_color`）加上兩個純顯示欄位——雲端只是「作者」，本地古典引擎才是「執行者」。
- **兩種信任等級在 schema 裡就分開**：`expected_pin_id`/`terminal` 是機器驗證的契約欄位；`tutorial_text`/`why`/`hint_color` 是給人看的 advisory 文字（信任等級同 `ai_hint`，驗證器不檢查其內容真偽，UI 也不得把它當判定依據）。
- **與能力②共用詞彙**：`component_id@version` 就是 `wiring-verification-architecture.md §4` 的 ComponentSpec 身分；`terminal` 就是 ComponentSpec 的 `pin_roles[].role`。PlanValidator 從 `steps[]` 確定性推導出 `pin_assignment`（`{"hc-sr04": {"VCC":"5V","GND":"GND_D","TRIG":"D7","ECHO":"D8"}}`），這個推導結果**就是**能力② `resolve_plan()` 的輸入——同一份 GuidancePlan，導引階段餵 `evaluate_guidance_step()` 逐步打勾，接完之後可直接註冊成能力②的 WiringPlanInstance 做電氣驗證，不需要第二種格式、不需要轉換器。`pin_assignment` 刻意**不存**在 plan JSON 裡（單一事實來源 = `steps[]`，避免兩處分歧）。
- schema 刻意扁平、小（<30 欄位）、無遞迴、無數值約束——取 Anthropic/OpenAI/Gemini 三家 constrained decoding 的交集（Anthropic 不支援 `minimum`/`maximum` 且 SDK 會靜默剝除；ExtractBench 顯示寬 schema 急遽退化）。範圍檢查一律下沉到本地驗證器。

### 2.2 GuidancePlan JSON schema（正式契約，`schemas/guidance-plan.schema.json`）

```jsonc
{
  "schema_version": "1.0",
  "plan_id": "plan-hcsr04-distance-01",       // 雲端給的 slug；本地匯入時若衝突自動加後綴
  "board_id": "arduino-uno-q",                 // 必須等於執行中後端的 config.board
  "goal": "接超音波感測器並顯示距離",            // 原始需求，追溯用
  "locale": "zh-TW",
  "component_specs": { "hc-sr04": "1.0.0" },   // id → semver，身分同能力② ComponentStore 的 "{id}@{version}"
  "origin": {                                   // provenance——「可重現的專案狀態」moat 的延伸
    "kind": "cloud",                            // "cloud" | "pre_authored" | "cached"
    "model": "claude-sonnet-4-5",
    "board_profile_version": "…",               // 產生當下引用的 board.json 版本
    "generated_at_ms": 1721990000000
  },
  "steps": [
    {
      "step_id": "step-1-gnd",
      "expected_pin_id": "GND_D",     // ★ 契約欄位：必須存在於 board.json，Tier0 唯一比對依據
      "expected_role": "GND",         //   顯示用（同 GuidanceStep.expected_role）
      "component_id": "hc-sr04",      //   串接 ComponentSpec（同 GuidanceStep.component_id）
      "terminal": "GND",              // ★ 契約欄位：必須存在於該 ComponentSpec 的 pin_roles
      "hint_color": "brown",          //   advisory：教學文案建議顏色，絕不參與比對（GuidanceStep 既有語意）
      "tutorial_text": { "zh-TW": "先把黑色或棕色線從感測器 GND 接到板上 GND（數位排針側）。" },  // advisory
      "why": { "zh-TW": "先接地是接線安全慣例，可避免訊號線先通電時的浮動電位。" }               // advisory
    },
    { "step_id": "step-2-vcc",  "expected_pin_id": "5V",  "expected_role": "VCC",  "component_id": "hc-sr04", "terminal": "VCC",  "hint_color": "red",    "tutorial_text": {"zh-TW": "…"}, "why": {"zh-TW": "…"} },
    { "step_id": "step-3-trig", "expected_pin_id": "D7",  "expected_role": "TRIG", "component_id": "hc-sr04", "terminal": "TRIG", "hint_color": "yellow", "tutorial_text": {"zh-TW": "…"}, "why": {"zh-TW": "D7 為一般 GPIO，3.3V 輸出對 Trig 足夠"} },
    { "step_id": "step-4-echo", "expected_pin_id": "D8",  "expected_role": "ECHO", "component_id": "hc-sr04", "terminal": "ECHO", "hint_color": "green",  "tutorial_text": {"zh-TW": "…"}, "why": {"zh-TW": "ECHO 是 5V 訊號，D8 為 5V-tolerant 腳位"} }
  ]
}
```

執行時每個 step 一對一映射成 M22 的 `GuidanceStep(step_id, expected_pin_id, expected_role, component_id, hint_color)`——`terminal`/`tutorial_text`/`why` 留在 PlanRuntime 層供 UI 與能力②使用，不進入 `evaluate_guidance_step()`。

### 2.3 多步驟計畫狀態機（PlanRuntime，新檔 `backend/app/vision/plan_runtime.py`）

不新增 thread：PlanRuntime 掛在 WireTraceWorker 既有 tick 的尾端（M22 的 guidance 評估已經在那裡，成本 <1ms 量級），只是把「單一 step」升級成「step 序列 + 進度簿記」。

**狀態**：plan 層 `active | completed | paused_regression | aborted`；step 層 `pending | current | done | broken`。

**推進規則（決斷，不是選項單）**：
- 預設 **auto-advance**：current step 的 `GuidanceResult.status == "correct"` **連續 2 個 tick**（0.5s tick ≈ 1 秒穩定）→ step 標 `done`、把 `expected_pin_id` 加入 `baseline_pin_ids`（M22 既有機制：下一步的「新端點」差集才會正確）、推進下一步、發 `plan_progress`。單一 tick 不算——防一幀吸附抖動造成假推進。
- `config: guidance.advance_mode: "auto" | "confirm"`（預設 `"auto"`）。`"confirm"` 模式下 `correct` 穩定後 step 進入 `awaiting_confirm` 子狀態，等 `POST /api/plans/current/advance`。教學情境（講師逐步解說）用 confirm，demo 用 auto。
- 使用者永遠可用 `POST /api/plans/current/advance` 帶 `{"action":"skip"}` 跳過卡住的步驟（例如手上元件跟計畫不同，見 §7 失敗模式）——skip 的 step 標 `done` 但 `skipped:true`，誠實記錄，不假裝驗證過。

**回頭核對（re-check）已完成步驟**：每個 tick，PlanRuntime 對所有 `done` 且非 `skipped` 的 step 檢查 `expected_pin_id ∈ occupied_now`（來自 WireTraceResult 的既有集合，字串比較，免費）。條件：只在 `board_tracking == "locked"` 時核對（`stale`/`searching` 時凍結判斷，不亂降級——手進畫面遮擋是常態，約束 #3）。某 `done` step 的腳位**連續 2 個 tick**不在 `occupied_now` → 該 step 標 `broken`、plan 轉 `paused_regression`、current step 暫停，UI 引導使用者先修復；腳位重新出現並穩定 2 個 tick → `broken` 回 `done`、plan 回 `active` 繼續原本的 current step。

**誠實聲明**：re-check 依賴 wire trace 對已插好線的持續可見性——線被手或元件本體長時間遮擋會造成假 `broken`。2-tick debounce + `locked` 前置條件是緩解不是解決；M27 驗收（§8）要求實測這個場景並記錄假 regression 頻率。

### 2.4 WS 訊息 `plan_progress`（新 type，沿用既有擴充點與 latest-only 語意）

```jsonc
{
  "type": "plan_progress",
  "board_id": "arduino-uno-q",
  "plan_id": "plan-hcsr04-distance-01",
  "ts_ms": 1721990401234.0,
  "plan_status": "active",              // "active" | "completed" | "paused_regression" | "aborted"
  "current_step_id": "step-3-trig",
  "completed": 2, "total": 4,
  "steps": [
    { "step_id": "step-1-gnd",  "status": "done",    "expected_pin_id": "GND_D", "skipped": false },
    { "step_id": "step-2-vcc",  "status": "done",    "expected_pin_id": "5V",    "skipped": false },
    { "step_id": "step-3-trig", "status": "current", "expected_pin_id": "D7" },
    { "step_id": "step-4-echo", "status": "pending", "expected_pin_id": "D8" }
  ]
}
```

- 只在狀態變化時發布（step 推進/regression/完成），不是每 tick——事件驅動、低頻，跟 `wiring_check` 同一個理由。
- 與 `detection`/`wire_trace`/`guidance_check` 共用同一個 per-client 單槽 latest-only 佇列：慢連線上 `plan_progress` 可能被下一則 `detection` 蓋掉——**因此權威進度永遠可從 `GET /api/plans/current/progress` 同步讀回**（同 verdict 的讀取成本量級），WS 只是推播便利，不是唯一通道。
- 逐步的勾/叉細節仍走既有 `guidance_check` 訊息（M22 形狀不變）；`plan_progress` 只管計畫層簿記。前端對未知 type 本來就忽略，純加法。

---

## 3. Tier 2：雲端 Plan Service

### 3.1 部署形態（決斷）

一個獨立的小型雲端服務（FastAPI，內部雲或任何 HTTPS 端點），**瀏覽器永遠不直接碰它**——只有本地後端的 `PlanAuthorClient`（`httpx.AsyncClient`，outbound-only）呼叫它。理由：(1) API key 只存在雲端服務，不落地到每台 PC；(2) prompt 模板/模型選擇可集中演進；(3) privacy 邊界清楚——能離開 PC 的資料種類由 `PlanAuthorClient` 一處白名單控制。

模型與方法（依據研究 B，決斷）：三家 API 皆可（schema 小、都在能力範圍內），首選 Anthropic `output_config.format` structured output；schema 取三家交集（無遞迴、無數值約束）。靜態前導（系統提示 + board.json pin 表）用 prompt caching（實測省 30–50% input token）。**Grounding 是精確查表不是 RAG**：單次 plan 涉及 1–5 個元件、材料 <10K token，board profile + 相關 ComponentSpec 全文直接進 context，按 `component_id` 精確取回；不用向量檢索（唯一效果是引入「檢索錯元件」這種新失敗模式）、不 fine-tune（目錄會演化、燒進權重的知識無法附版本驗證）。

### 3.2 雲端端點

**`POST /v1/plans/generate`**
```jsonc
// req
{ "goal": "接超音波感測器並顯示距離",
  "board_id": "arduino-uno-q",
  "board_profile": { …board.json 原文… },          // 本地後端隨附權威版本，雲端不自備
  "component_specs": [ { …hc-sr04 component.json 原文… } ],
  "constraints": { "reserved_pins": ["D0","D1"], "locale": "zh-TW" } }
// res（一律 200 + ok）
{ "ok": true, "plan": { …GuidancePlan… },
  "provenance": { "model": "…", "prompt_version": "…" } }
// 或 { "ok": false, "error": "generation_failed" | "goal_unsupported" | "unknown_component", "message": "…", "violations": [ … ] }
```
雲端內部也跑一份同款 lint（generate→validate→違規回饋重試，**最多 2 次**，仍失敗就 `ok:false` + violations——驗證回饋迭代收斂有實證，arXiv 2606.27757）。這是省 round-trip 的禮貌，**不是信任來源**：本地 PlanValidator（§3.4）無論如何都會完整重跑，雲端驗證通過與否對本地閘門沒有任何效力。

**`POST /v1/components/identify`**（Phase 1，選配）
```jsonc
// req: 使用者在 UI 明確按「拍照辨識」才會送出的單張靜態照片——不是串流
{ "photos": ["<base64 jpeg>"], "hint_text": "藍色的超音波模組" }
// res
{ "ok": true, "needs_confirmation": true,
  "candidates": [ { "component_id": "hc-sr04", "confidence": 0.86,
                    "evidence": { "silkscreen_read": ["HC-SR04","VCC","Trig","Echo","GND"] } } ] }
```
VLM/LLM 在此只做**對 50–500 筆已知目錄的封閉分類**，必經使用者點選確認；**計畫中的腳位映射永遠來自策展過的 ComponentSpec，絕不來自照片**（CircuitLM 實證：接地到已驗證元件庫後 library compliance 近滿分，但這靠的是查表+驗證，不是模型記憶）。目錄沒有的模組走明確的 `ok:false, error:"unknown_component"`「不支援/請提供規格」路徑，不退化成看照片猜腳位。

### 3.3 本地端點（沿用 200+ok 慣例；真 HTTP 錯誤碼只留給請求格式錯誤）

| 端點 | 同步性 | 用途 |
|---|---|---|
| `POST /api/plans/generate` `{goal, component_ids[], constraints}` | **async job**（雲端呼叫 5–20s，比照能力② verify 的 job pattern）→ `200 {ok:true, job_id}` | 後端組稿→呼叫雲端→**本地 PlanValidator**→通過才入庫 |
| `GET /api/plans/jobs/{job_id}` | sync | `{status:"running"}` → `{status:"done", plan_id}` 或 `{status:"failed", error, violations[]}` |
| `POST /api/plans` `{plan: {…GuidancePlan…}}` | sync | **直接匯入**一份計畫 JSON（pre-authored / 離線快取 / 手寫）——走完全相同的 PlanValidator，這就是離線故事的入口（§6） |
| `GET /api/plans` / `GET /api/plans/{id}` | sync | 已入庫（= 已通過驗證）計畫列表/單筆，含 `validation.checks[]` |
| `DELETE /api/plans/{id}` | sync | 移除 |
| `POST /api/plans/{id}/activate` | sync | 設為 current，PlanRuntime 從 step 1 開始（內部逐段呼叫既有 `POST /api/guidance/step` 的同一套邏輯，含 baseline 快照） |
| `POST /api/plans/current/advance` `{action:"confirm"\|"skip"\|"back"\|"abort"}` | sync | confirm 模式推進 / 跳過 / 回上一步 / 中止 |
| `GET /api/plans/current/progress` | sync, cheap | 與 `plan_progress` WS 同形狀——權威讀取路徑 |
| `POST /api/components/identify` | async job | 代理雲端 identify（照片由前端明確上傳，非串流截圖） |

計畫存放：`profiles/plans/arduino-uno-q/*.plan.json`（能力②已規劃的同一目錄家族），連同 `validation` 結果與 `origin` provenance 一起落盤——重開服務後 cached plans 直接可用。

### 3.4 PlanValidator（本地、確定性、純程式——雲端永不被信任）

新檔 `backend/app/plans/validator.py`。輸入：候選 GuidancePlan + 已載入的 BoardProfile + ComponentStore。輸出：`ValidationReport { passed: bool, checks: [...], violations: [...] }`。**任何一條 reject 級違規 → 整份計畫拒收**（`ok:false`），violations 陣列附具名代碼；驗證器**永不放寬，寧可明確失敗**。

| 代碼 | 級別 | 檢查內容（全部查表/字串比較，零模型） |
|---|---|---|
| `SCHEMA_INVALID` | reject | pydantic StrictModel（`extra="forbid"`）對原始 schema 重新驗證——防禦縱深，補上三家 constrained decoding 都不保證的長度/範圍約束 |
| `BOARD_MISMATCH` | reject | `plan.board_id != config.board` |
| `PIN_NOT_FOUND` | reject | 任一 `expected_pin_id` 不存在於 `board.json pins[]`——HWE-Bench/CircuitLM 都實測到的「幻覺腳位」型態，這裡 100% 攔截 |
| `UNKNOWN_COMPONENT` / `UNKNOWN_TERMINAL` | reject | `component_id@version` 不在 ComponentStore，或 `terminal` 不在該 spec 的 `pin_roles[]` |
| `VOLTAGE_INCOMPATIBLE` | reject | 逐 step 比對 ComponentSpec `electrical_constraints.external_signal_voltage` vs pin 的 `electrical.five_volt_tolerant` / `voltage`。實例（規則直接來自 `board.json` 機讀事實，不是硬編碼）：ECHO(5V)→A0 拒收，引用 A0 真實 danger 文字「3.3V 邏輯 — 接上 5V 訊號會永久損壞板子」（`five_volt_tolerant:false`）；ECHO→D3 拒收（D3 上限 3.6V）；ECHO→D8 通過（`five_volt_tolerant:true`） |
| `CAPABILITY_MISMATCH` | reject | terminal 的 `board_requirements`（需要 `pwm`/`digital_io`/`power.rail` 等）不被指定 pin 的 `capabilities[]` 滿足——「要 PWM 就必須是 PWM 腳」 |
| `RESERVED_PIN` | reject | 指到 BOOT/reset 類腳位（能力② `PIN_NOT_TESTABLE` 同一批），或 `constraints.reserved_pins` |
| `PIN_CONFLICT` | reject | 同一 `expected_pin_id` 被兩個 step 使用（一腳一線） |
| `TERMINAL_INCOMPLETE` / `TERMINAL_DUPLICATED` | reject | 某 component 的必要 terminal 沒有對應 step，或同一 terminal 出現兩次 |
| `STEP_ID_DUPLICATED` | reject | `step_id` 重複（會毀掉 guidance 簿記） |
| `GND_ORDER` | **warning** | GND step 不在該元件訊號線之前——好慣例但不是安全問題，不值得整份拒收 |
| `HINT_COLOR_UNKNOWN` | **warning** | `hint_color` 不在已知色名——advisory 欄位，降級為 warning 並照實回報 |

最後一步：推導 `pin_assignment` 並（當對應 ComponentSpec 存在時）呼叫能力②的 `resolve_plan()` 做交叉驗證——**同一套 resolver、同一套診斷分類法（`incompatible_assignment` 等），是共用詞彙不是平行實作**。這保證「導引時被 PlanValidator 放行的計畫」與「接完後 WiringWorker 拿去電氣驗證的計畫」在相容性判斷上不可能分歧。

---

## 4. Tier 1：VLMWorker（邊緣 VLM 即時旁述層）

### 4.1 Worker 形態——逐字沿用 WireTraceWorker pattern

新檔 `backend/app/vlm_worker.py`。與 `wire_worker.py` 同構：自己的 `threading.Thread`（`name="vlm-worker"`, daemon）、`start()/stop()` 用 Event 而非 sleep、FrameBus 的**第五個**獨立 reader（MJPEG、VisionWorker、WireTraceWorker、規劃中的 WiringWorker 之後；`FrameBus.get_latest(newer_than=cursor)` 已文件化 multi-reader-safe，零改動）、`except Exception` 包住每個 tick 的推論呼叫（VLM 掛掉絕不拖垮幾何管線）、透過**同一個** `DetectionBroadcaster.publish_threadsafe()` 發布（不是第二個 broadcaster、不是新 WS route）。

**為什麼自己的 thread**：跟 WireTraceWorker/WiringWorker 被否決折入 VisionWorker 的理由完全同款、且更強——一次 VLM 推論是 1.5–6 秒不是 45–90ms，任何共用 loop 的方案都直接摧毀 30Hz 姿態追蹤。

**VLM runtime 是獨立行程，不是 in-process binding**（研究 A 的結論照單全收）：後端用 `httpx.AsyncClient`（worker thread 內以同步 client 等價使用）打 OpenAI 相容 HTTP API（`POST /v1/chat/completions`，image 走 base64 `image_url`）。開發/demo 用 Ollama（`127.0.0.1:11434`）、出貨形態換隨附 `llama-server` subprocess（MIT、鎖版本、離線單目錄；**部署前必須驗證 mmproj 有 GPU offload——llama.cpp issue #22582 的 CPU BF16 encoder 一張圖 82 秒是真實踩過的坑**）、Snapdragon X ARM64 換 Qualcomm GenieX endpoint——**同一份 client code 不改，只換 URL**。模型：Qwen3-VL-8B Q4（<8GB VRAM 機器自動降 4B，同家族 prompt 不用改）；此為研究 A 的 primary 決斷，不再開選項。

### 4.2 觸發類別（四類，各自獨立的 single-slot 佇列）

| trigger | 觸發條件 | 節奏 | 輸出 |
|---|---|---|---|
| `periodic` | `vlm.periodic_hz` 定時 keyframe 場景旁述（「板子已鎖定，畫面裡有一條紅線從 5V 出發…」） | 預設 **0.2Hz**（GPU 機器）；**CPU-only 機器預設關閉**——研究 A 實測 CPU 端到端 15–40s/幀，連續 narration 不成立，這正好吻合 advisory-only 設計 | `vlm_insight(kind="narration")` |
| `guidance_timeout` | M24 既有規格原封不動：`status=="pending"` 連續超過 `guidance.ai_fallback_after_s`（5.0s）且 Stage A+A' 兩通道都無候選、且該 step 本次 pending 未觸發過（每 step 最多一次） | 事件驅動 | 裁切 `expected_pin_id` 周邊小 crop 的二元問題 → 回填 `GuidanceResult.ai_hint`，由 guidance 引擎發後續 `guidance_check`（**不**重複發 `vlm_insight`——M24 契約不動，VLMWorker 只是它的執行載體） |
| `scene_change` | **不做像素幀差**（color-agnostic 設計已論證背景相減對「板子會動、手會入鏡」結構性失效，約束 #3）——改訂閱 Tier0 既有狀態轉變：`tracking` searching→locked、`wire_trace` 線數增減、plan step 推進/regression | 事件驅動，10s debounce | `vlm_insight(kind="narration"` 或 `"anomaly")`，例：偵測到新線但兩端 floating 持續 →「畫面中央似乎有一條線還沒插到任何腳位」 |
| `user_question` | `POST /api/vlm/ask {"text":"這顆藍色模組是什麼?"}` | 使用者主動；CPU-only 機器**唯一**開放的觸發類別 | `vlm_insight(kind="answer")`，附當下 keyframe；問元件時用 JSON mode 出 `structured.candidates`（封閉目錄分類，同 §3.2 identify 的語意，需人工確認） |

**Latest-only 語意照搬 WS queue 的做法**：每個 trigger class 一個單槽——上一次推論還在跑時，新觸發**覆蓋**槽內未處理的請求而不排隊；推論完成時若槽內 keyframe 已老於 `vlm.max_frame_age_s`（預設 10s）直接丟棄結果不發布（畫面早就不是那樣了，發出來就是誤導）。`user_question` 例外：不丟棄，但回覆附上 `frame_age_ms` 誠實標示。優先序：`user_question` > `guidance_timeout` > `scene_change` > `periodic`。

Streaming：v1 **不做** token-level 串流轉發——latest-only 單槽 WS 佇列跟部分更新語意互相打架，narration 完整生成後一次發布（60–100 token、3–6s，可接受）；SSE 逐 token 转发列為 future work，不是本設計範圍。

### 4.3 WS 訊息 `vlm_insight`（新 type）

```jsonc
{
  "type": "vlm_insight",
  "board_id": "arduino-uno-q",
  "ts_ms": 1721990401234.0,
  "frame_id": 18234,                    // 本 insight 依據的 keyframe
  "frame_age_ms": 2400,                 // 發布時該 keyframe 的年齡——誠實標示延遲
  "trigger": "periodic",                // "periodic" | "guidance_timeout" | "scene_change" | "user_question"
  "kind": "narration",                  // "narration" | "anomaly" | "answer" | "component_guess"
  "text": "板子已鎖定。一條紅線從 5V 出發，另一端尚未接到任何腳位。",
  "structured": null,                   // component_guess 時: {"candidates":[{"component_id":"hc-sr04","confidence":0.86,"evidence":{"silkscreen_read":[…]}}]}
  "model": "qwen3-vl-4b-q4",
  "latency_ms": 2350,
  "authority": "advisory"               // 常數，永遠 "advisory"——前端必須以視覺上明確區隔於 Tier0 勾叉的樣式呈現
}
```

同一 per-client latest-only 單槽佇列；低頻（≤0.2Hz + 事件），被 `detection` 蓋掉的機率語意同 `wire_trace`，既定行為非新 bug。

### 4.4 新增本地端點

```
GET  /api/vlm/status  → 200 { "enabled": true, "runtime": "llama-server", "model": "qwen3-vl-4b-q4",
                              "reachable": true, "last_latency_ms": 2350, "periodic_hz": 0.2 }
POST /api/vlm/ask     { "text": "…" } → 200 { "ok": true }（答案走 WS vlm_insight）
                       VLM 不可用時 → 200 { "ok": false, "error": "vlm_unavailable", "message": "…" }
```

`config` 新增：`vlm: { enabled: bool = false, endpoint: "http://127.0.0.1:8080/v1", model: str, periodic_hz: float = 0.2, request_timeout_s: float = 30.0, max_frame_age_s: float = 10.0 }`——全部有預設值，既有 config.yaml 不動即可跑（`enabled:false` 時 VLMWorker 根本不啟動）。

### 4.5 硬規則：VLM 輸出永遠不能改變 guidance status

**架構層面強制，不是紀律約定**：VLMWorker 對 `GuidanceState`/`WireTraceState`/`PlanRuntime`/`PlanValidator` **沒有任何寫入路徑**——它唯二的輸出是 (a) `publish()` 一則 `vlm_insight`、(b) 回填 `GuidanceResult.ai_hint`（M24 已定義的獨立欄位，`evaluate_guidance_step()` 的決策路徑讀不到它）。`status` 的四值（`pending/correct/wrong_pin/uncertain`）只由字串/集合比較產生，函式簽名裡沒有 ai_hint 參數，型別系統上就寫不進去。

**為什麼這條線是鐵的（COMMON 約束 #1 證據，逐條）**：麵包板路徑追蹤最佳 71%（arXiv 2605.15672）——十次錯三次的訊號不配碰判定；局部 diff 偵測最佳 recall 40.7%、且 recall 與視覺顯著度無關 r=-0.08（DiffSpot, arXiv 2605.29615）——「線很明顯」不保證看得到；本專案本週活體 A/B：VLM 自信宣稱藍線插在 5V、實際 5V 插座是空的——自信且錯、不可追溯。反之 `snap_endpoint()` 精確、免費、已驗證（紅線吸附 15.8px、floating 289.6px 的實測數字）。VLM 做它擅長的（OCR 絲印、場景敘事、封閉分類），幾何做判定——各安其位。

---

## 5. 部署圖（ASCII）與資料邊界

```
┌─ Browser (React TS) ────────────────────────────────────────────┐
│  <img src="/video">  ·  WS /ws/detections  ·  REST /api/*       │
│  （detection / wire_trace / guidance_check / plan_progress /    │
│    vlm_insight 五種 type，未知 type 忽略——既有擴充點）           │
└────────────────────────────┬────────────────────────────────────┘
                  127.0.0.1:8100（localhost only，不變）
┌─ Windows PC ───────────────┴────────────────────────────────────┐
│  FastAPI backend                                                │
│    Camera ─► CaptureService ─► FrameBus（單槽，多 reader）       │
│      ├─ reader① MJPEG encoder            (Tier0)                │
│      ├─ reader② VisionWorker ~30Hz       (Tier0, 姿態+32 pins)  │
│      ├─ reader③ WireTraceWorker ~2Hz     (Tier0, 線+snap)       │
│      │     └─ guidance 引擎 + PlanRuntime + plan_progress       │
│      ├─ reader④ WiringWorker（能力②，已設計）(Tier0, 電氣)      │
│      └─ reader⑤ VLMWorker（NEW）          (Tier1)               │
│            │  base64 keyframe，HTTP，只走 loopback              │
│            ▼                                                    │
│    本機 VLM runtime（獨立行程：llama-server / Ollama /          │
│    Snapdragon 上 GenieX——OpenAI 相容 API，崩潰不拖垮幾何）      │
│                                                                 │
│    PlanValidator（Tier0 閘門）◄─ PlanAuthorClient ──────┐       │
│    profiles/plans/*.plan.json（cached，離線可用）        │       │
└──────────────────────────────────────────────────────────┼──────┘
                              HTTPS，outbound only          │
┌─ Cloud ─────────────────────────────────────────────────┴──────┐
│  Plan Service（LLM structured output + 禮貌性 lint）            │
│   POST /v1/plans/generate  ·  POST /v1/components/identify      │
└─────────────────────────────────────────────────────────────────┘

跨邊界資料：
  Browser ↔ PC     ：MJPEG、WS JSON、REST——全部 localhost，不出機器
  PC → VLM runtime ：keyframe JPEG（loopback，不出機器）
  PC → Cloud       ：goal 文字、board_id、board.json pin 表、ComponentSpec 全文、
                     （僅使用者明確按「拍照辨識」時）單張靜態照片
  Cloud → PC       ：GuidancePlan JSON 候選、identify candidates
  ★ 永遠不跨到雲端：即時影像/MJPEG/任何 FrameBus 影格、WS 串流、攝影機畫面。
    這是 pitch 的隱私底線：桌面直播只存在於這台 PC。identify 的照片是唯一例外，
    且必須是使用者主動、單張、可在送出前預覽的動作——不是系統自動截圖。
```

---

## 6. 離線故事與降級表

系統的核心性質不變：**Tier0 CPU-only、零訓練、可完全離線**。兩個新層都是可拆卸的加法。

| 情境 | Tier0 幾何 | Tier1 VLM | Tier2 雲端 | 實際體驗 |
|---|---|---|---|---|
| 全配（GPU 筆電 + 網路） | ✅ | ✅ 0.2Hz 旁述 + ai_hint + 問答 | ✅ 即時生成計畫 | 完整 |
| 無網路 | ✅ | ✅（本機推論不受影響） | ❌ `POST /api/plans/generate` → `ok:false, error:"cloud_unreachable"` | **cached/pre-authored plans 全功能**：`POST /api/plans` 匯入的計畫與先前生成落盤的計畫照常 activate/執行/打勾——PlanRuntime 與 PlanValidator 都是本地的，離線導引體驗與線上生成的計畫零差異 |
| 無 VLM runtime（未安裝/`vlm.enabled:false`/行程掛掉） | ✅ | ❌ `vlm_insight` 缺席、`ai_hint` 永遠 null（M24 本來就定義為選配欄位）、`/api/vlm/ask` → `ok:false, error:"vlm_unavailable"` | ✅ | 導引打勾、計畫生成完全不受影響——`ai_hint` 是 advisory，缺席不缺功能 |
| 無雲端 + 無 VLM | ✅ | ❌ | ❌ | = 今天的系統 + PlanRuntime 跑內建/匯入計畫。純 Tier0，demo 底線形態 |
| CPU-only 機器 | ✅（本來就是 CPU-only） | ⚠️ 只開 `user_question`（periodic 預設關——15–40s/幀做不了連續旁述，誠實不硬撐） | ✅ | 打勾即時、旁述改為問答式 |

降級全部是**運行時自動**的：`GET /api/vlm/status` 與 generate 的 `ok:false` 讓前端知道現在在哪一格，UI 隱藏對應功能而不是報錯。

---

## 7. 誠實失敗模式對照表

| 失敗模式 | 行為 | 為什麼這樣設計 / 誠實限制 |
|---|---|---|
| 雲端不可達/逾時 | generate job → `failed, error:"cloud_unreachable"`；已入庫計畫完全不受影響 | 雲端只在「authoring 時刻」被需要，執行期零依賴 |
| 雲端回傳 schema 合法但語意錯誤的計畫（如 ECHO→A0） | PlanValidator 拒收，`ok:false` + `violations:[{code:"VOLTAGE_INCOMPATIBLE", step_id:"step-4-echo", detail:"A0.five_volt_tolerant==false", board_text:"3.3V 邏輯 — 接上 5V 訊號會永久損壞板子"}]`；雲端側帶違規清單重試 ≤2 次後放棄 | 這正是 benchmark 實測的主要錯誤型態（腳位級語意正確率 ~72–78%、全對 <10%），也正是確定性 lint 100% 攔得住的類別——**驗證器永不放寬** |
| 雲端捏造不存在的腳位/元件 | `PIN_NOT_FOUND` / `UNKNOWN_COMPONENT` 拒收 | 幻覺腳位 = CircuitLM/HWE-Bench 都記錄的高頻型態；查表攔截，免費 |
| VLM 幻覺（自信誤述接線狀態，如本週 5V 事件） | 傷害被架構圍堵：輸出只能進 `vlm_insight`/`ai_hint`，UI 強制與勾/叉視覺分離並標示 advisory；`status` 型別層面寫不進去 | 緩解呈現、不緩解幻覺本身——VLM 還是會錯，我們只是讓錯的話**說不進判定** |
| VLM 延遲尖峰（首 token 2–5s 常態，尖峰更久） | latest-only 單槽覆蓋 + `max_frame_age_s` 過期丟棄；`user_question` 不丟但附 `frame_age_ms` | 寧可沉默也不發「三十秒前畫面」的旁述誤導使用者 |
| VLM runtime 行程崩潰 | worker 的 tick 級 `except` 吃掉、`reachable:false`、指數退避重連（llama-server subprocess 由後端 supervise 重啟）；幾何管線零感知 | 行程隔離是選 HTTP 而非 in-process binding 的主因 |
| 計畫-現實分歧（使用者手上元件跟計畫不同 / 想接別的腳位） | 該 step 永遠 `pending` 或 `wrong_pin`（誠實：Tier0 只回報看見的）；出口是 `advance {action:"skip"}`（標記 skipped，不假裝驗證過）或重新 generate | 系統不猜「使用者其實想幹嘛」；skip 記錄在 progress 裡，能力②電氣驗證時 skipped step 對應 terminal 誠實回報 `unverified` |
| 已完成步驟的線被手長時間遮擋 | re-check 需 `board_tracking=="locked"` + 連續 2 tick 缺席才標 `broken`；仍可能假 regression | 已知限制，M27 驗收要求實測記錄頻率，不預先宣稱解決 |
| 慢 WS 連線上 `plan_progress`/`vlm_insight` 被 `detection` 蓋掉 | 既定 latest-only 語意；權威狀態走 `GET /api/plans/current/progress`、insight 遺失即遺失（advisory 本來就可丟） | 與 `wire_trace` 被蓋掉同一件事，不是新 bug |
| 黑線在黑桌墊（Tier0 兩通道全盲） | `guidance_timeout` 觸發 ai_hint——但 DiffSpot recall <41%：hint 更常「沒看到」而非「看錯」 | 緩解不是解決（color-agnostic 設計原話），UI 文案不得暗示「AI 幫你確認過了」 |

---

## 8. Milestones（延續 M0–M24，新增 M25–M30；驗收一律真實硬體、誠實驗證）

**M25 — GuidancePlan schema + PlanValidator（純資料，零雲端、零 VLM、零相機）**
交付 `schemas/guidance-plan.schema.json`、`app/plans/{models,validator,store}.py`、`POST /api/plans`、`GET /api/plans[/{id}]`。
*驗收*：手寫一份 ECHO→A0 的計畫 `POST /api/plans` → 確定性回 `ok:false, violations` 含 `VOLTAGE_INCOMPATIBLE`，並逐字引用 A0 在 `board.json` 裡的真實 danger 文字；ECHO→D3 同樣拒收（3.6V 上限）；PWM terminal 指到非 PWM 腳 → `CAPABILITY_MISMATCH`；捏造腳位 `D99` → `PIN_NOT_FOUND`；合法的 `GND_D/5V/D7/D8` 版本 → `ok:true` 且推導出的 `pin_assignment` 與能力② `resolve_plan()` 結論一致。curl 可全程演示。

**M26 — PlanRuntime 多步驟狀態機 + `plan_progress` WS（pre-authored 計畫，離線）**
交付 `app/vision/plan_runtime.py` 接進 WireTraceWorker tick、`activate/advance/progress` 端點、WS 新 type。
*驗收（真實 UNO Q + 真實杜邦線）*：activate 內建 HC-SR04 四步計畫；依序插 GND→5V→D7，每步 `correct` 穩定 ~1s 後 WS 收到 `plan_progress` 推進且 `completed` 遞增；故意把第 4 步插到 D7（已佔用）→ 停在 `wrong_pin` 不推進；**拔掉已完成的 GND 線** → 2 tick 內 plan 轉 `paused_regression`、step-1 標 `broken`，插回後自動恢復 `active`；全程斷網執行（證明離線故事）。既有 88+ 測試不受影響。

**M27 — 雲端 Plan Service + 本地 generate 整合**
交付雲端 `POST /v1/plans/generate`（structured output + 禮貌 lint + ≤2 重試）、本地 `PlanAuthorClient` + generate job 端點。
*驗收*：對真實雲端以 goal「接超音波感測器並顯示距離」生成 → 本地 PlanValidator 通過 → activate → 在真板子上走完全程打勾；**對抗測試**：修改雲端 prompt 誘導它產出 ECHO→A0 的計畫（或 replay 一份錄下的壞回應），斷言本地 validator 拒收、job 回 `failed` + violations——證明「雲端永不被信任」是可執行的斷言不是口號；斷網後 generate 回 `ok:false, cloud_unreachable` 而 M26 的離線計畫照常可用。同場景實測記錄「手遮擋已完成步驟」的假 regression 次數（§2.3 誠實聲明的補測）。

**M28 — VLMWorker 骨架 + `vlm_insight`（periodic + user_question，先 mock 後真）**
交付 `app/vlm_worker.py`、`MockVlmClient`（鏡照 MockDetector/MockSerialLink 慣例：確定性腳本回覆，讓測試零 GPU）、真實 runtime 接 Ollama `qwen3-vl:4b`、`/api/vlm/status`、`/api/vlm/ask`。
*驗收*：真實畫面（板子+一條紅線）上 `POST /api/vlm/ask`「畫面裡有什麼」→ WS 收到 `vlm_insight(kind="answer")`，`latency_ms` 誠實記錄實測值（不預先宣稱數字）；periodic 0.2Hz 開啟時，斷言 `detection` 訊息頻率與 VisionWorker tick 週期**無可測變化**（VLM 推論不阻塞幾何——本設計的硬性質，要量測不要假設）；`kill` VLM runtime 行程 → `status.reachable:false`、幾何管線與打勾完全正常、重啟後自動恢復。

**M29 — `guidance_timeout` ai_hint 經 VLMWorker 落地（實作 M24 契約）+ scene_change**
交付 M24 規格的裁切二元判斷路由到 VLMWorker、Tier0 事件驅動的 scene_change 觸發。
*驗收（沿用 M24 驗收並加嚴）*：刻意用一條同時逃過色相與 ridge 的線（黑線黑桌墊），`pending` 超過 5s 後斷言**恰好一次**VLM 呼叫、結果只出現在 `ai_hint`、`status` 全程未被改寫——用測試斷言 `evaluate_guidance_step()` 的輸入輸出型別中不存在 ai_hint 寫入路徑；scene_change：把板子從畫面拿走再放回（searching→locked 轉變）→ 收到一則對應 `vlm_insight`，且 10s debounce 內重複轉變不重複觸發。

**M30 — 端到端三層 demo + 降級演練（headline 能力③ demo）**
*驗收腳本（真實硬體，一鏡到底）*：(1) 使用者輸入 goal → 雲端生成計畫 → validator 通過 → 逐步導引，每步打勾推進，VLM 同步旁述；(2) 中途拔網路線 → 旁述照常（本機）、既有計畫照常、generate 誠實失敗；(3) 關掉 VLM runtime → 打勾照常、`ai_hint` 缺席、UI 不報錯只收起旁述面板；(4) 全關 → 純 Tier0 導引仍完整走完四步。四格降級表（§6）逐格現場兌現，才算通過。

---

## 9. 明確決策與被否決的替代方案

1. **否決：前端直連雲端 Plan Service。** API key 落地每台 PC、privacy 白名單失去單點控制、且 validator 必須在後端（需要權威版 board.json/ComponentSpec）——proxy через 後端是唯一一致的形狀。
2. **否決：VLM 判定「這一步插對了沒」哪怕只當 tie-breaker。** 證據見 §4.5；`uncertain` 就是 `uncertain`，讓 40.7% recall 的訊號參與判定等於把「自信且錯」重新請回決策路徑——本專案已經為此付過學費（5V 事件）。
3. **否決：像素幀差做 scene_change 觸發。** color-agnostic 設計已論證背景相減對本專案結構性失效（板子會動、手會入鏡）；Tier0 狀態轉變是免費、語意化、已 debounce 的事件源。
4. **否決：GuidancePlan 內同時存 `steps[]` 與 `pin_assignment`。** 兩處事實必然分歧；`pin_assignment` 由 validator 確定性推導，能力②拿推導結果，單一事實來源。
5. **否決：`plan_progress` 走新的專用 WS route。** `type` 擴充點就是為此設計的（api-contract §2 原文），低頻事件無頻寬論點，同能力②否決 `/ws/wiring` 的理由。
6. **否決：v1 做 VLM token 串流轉發。** 與 latest-only 單槽佇列語意衝突，完整發布的 3–6s 延遲對 0.2Hz 旁述可接受；留作 future work。
7. **誠實不確定性（不假裝已解決）**：(a) Qwen3-VL 對「maker 模組小字絲印、反光、手遮擋」的實際 OCR 表現無公開 benchmark——M28 用真實模組實測，數字以實測為準；(b) 雲端計畫的 `tutorial_text` 品質（教學文案好不好讀）無機器驗證手段，只能人工抽查——它是 advisory 欄位，錯了不傷安全但傷體驗；(c) GenieX 是 developer preview，Snapdragon 路徑是戰略展示不是 primary（研究 A 原話照登）。

---

## 引用來源

- 本專案既有檔案：`docs/api-contract.md`、`docs/wire-recognition-design.md`、`docs/wiring-verification-architecture.md`、`docs/color-agnostic-wire-and-guidance-design.md`、`backend/app/wire_worker.py`、`backend/app/capture/sources.py`、`profiles/boards/arduino-uno-q/board.json`
- VLM 判定路徑禁令證據：arXiv 2605.15672（路徑追蹤最佳 71%）、DiffSpot arXiv 2605.29615（局部 diff recall 40.7%）、本專案 2026-07 live A/B（5V 誤報事件）
- 雲端結構化生成：Anthropic Structured Outputs 文件、OpenAI Structured Outputs、Gemini Controlled Generation、Requesty 244 模型實測、arXiv 2604.25359（Structured Output Benchmark）、arXiv 2602.12247（ExtractBench）、arXiv 2603.18102（HWE-Bench）、arXiv 2601.04505（CircuitLM/DMCV）、EMNLP 2023 From Words to Wires、arXiv 2606.27757（symbolic feedback 迭代精煉）
- 邊緣 VLM runtime：Ollama multimodal engine、llama.cpp libmtmd（PR #12898、issue #22582/#14527）、Qualcomm GenieX / NexaSDK / OmniNeural-4B、Qwen3-VL 4B/8B 基準、arXiv 2606.11257（Snapdragon prefill/decode 實測）


---

# 附錄 A：地端 VLM Runtime 與模型調研（研究原文）

# Edge VLM Runtime 與模型現況調查(Windows 本地端,2026 年中狀態)

> 說明:任務指定「February 2026 state of the art」,以下內容以 2026 年 2 月為基準、並納入至 2026 年 7 月已可查證的更新(有標註)。所有效能數字凡屬推估均明確標示「估計」。VLM 僅用於 component ID / 場景敘事 / anomaly flag / advisory-only ai_hint,不進入 pin-level 判定路徑(既定約束,不重議)。

---

## 1. Windows 本地 Runtime 現況(vision 支援為準)

| Runtime | Vision 支援 | 硬體 | 成熟度 / 備註 |
|---|---|---|---|
| **Ollama** | ✅ 成熟。自研 multimodal engine(2025/5 起),支援 Qwen2.5-VL、Qwen3-VL、Gemma 3、Llama 3.2-Vision、MiniCPM-V 等 | Windows x64 原生安裝(CUDA/Vulkan/ROCm);**Windows ARM64 已有原生 build(2026),但只走 CPU,不碰 Snapdragon GPU/NPU** | 生產可用度最高的「零運維」選項;`ollama pull qwen3-vl:4b` 即可跑 |
| **llama.cpp(libmtmd)** | ✅ 成熟。2025/4 起以 libmtmd 統一 multimodal;`llama-server` 已支援 vision(PR #12898);需 model GGUF + mmproj 兩個檔 | x64 CUDA/Vulkan/CPU;ARM64 CPU;另有 Qualcomm fork 供 Hexagon 路徑 | 最大控制權、可嵌入出貨;注意 issue #22582:某些版本 llama-server 的 vision encoder 落在 CPU BF16,一張圖 slice 要 ~82 秒 —— 部署前必須驗證 mmproj 有 GPU offload、鎖版本 |
| **LM Studio** | ✅ 支援 vision 模型(Qwen2.5-VL 等),圖片經 chat 或 OpenAI 相容 API 傳入 | Windows x64 **與 ARM64(Snapdragon X Elite)皆有官方 build**(CUDA/Vulkan);ARM64 上同樣不用 NPU | GUI 佳、適合 demo/評測;授權為閉源 app,嵌入產品出貨較不合適 |
| **ONNX Runtime GenAI + DirectML** | ⚠️ 可用但模型面窄:官方僅 Phi-3/3.5-vision、Phi-4-multimodal 有現成 ONNX;DirectML 路徑 `onnxruntime-genai-directml` | x64 任何 DX12 GPU(NVIDIA/AMD/Intel iGPU);另有 QNN EP 走 Snapdragon NPU(需為 NPU 重 build 模型資產) | Microsoft 官方棧,但 VLM 目錄更新慢,自轉模型工程量大 |
| **Windows AI Foundry / Foundry Local** | ❌ **目前 catalog 沒有 vision 模型**(chat + Whisper 而已;CLI 0.10.0 public preview)。OpenAI 相容 API、自動選 NPU/GPU/CPU 的架構很好,但今天幫不上 VLM | x64 + ARM64,NPU 自動偵測 | 值得持續觀察 —— 一旦上 VLM,會是 Windows 上阻力最低的 NPU 路徑 |
| **Qualcomm GenieX(AI Hub)** | ✅ **明確支援 VLM(Qwen3-VL 已列名)**,Hexagon NPU / Adreno GPU / CPU;**developer preview** | **Snapdragon X(Windows ARM64)**、8 Elite、Dragonwing | 提供 CLI、**Python SDK、OpenAI 相容 server** —— 對 FastAPI 是 drop-in;NPU 路徑用 AI Hub 預編譯 bundle 或 llama.cpp Q4_0 |
| **NexaSDK(現掛在 qualcomm GitHub org 下)** | ✅ 支援 Qwen3-VL、Gemma-3n 等 VLM 跨 NPU/GPU/CPU;自有 NPU 原生模型 **OmniNeural-4B**(text+image+audio) | Snapdragon X Elite NPU 實測可用(XDA 實測:圖片理解「decently well」、NPU 使用率 >95%) | 今天就能在 Snapdragon NPU 上跑多模態的最短路徑 |

另外:Build 2026 發表的 WSL 3 GPU/NPU passthrough(含 Snapdragon X Elite)未來可讓 Ollama/llama.cpp 在 ARM64 上吃到加速,但這是剛發表的能力,不宜當依賴。

---

## 2. 7B 級以下候選模型(誠實評級)

| 模型 | 參數 | 量化後記憶體 | 速度(實測/估計) | 對本案的誠實能力評級 |
|---|---|---|---|---|
| **Qwen3-VL-8B-Instruct** | 8B | Q4_K_M ~6.1 GB,建議 12 GB VRAM | RTX 3090 約 80–120 tok/s;RTX 4060 Laptop 估 35–60 tok/s(估計) | 同級最強:DocVQA 96.1、OCRBench 89.6、ScreenSpot 94.4。元件辨識(HC-SR04 這種有絲印文字的)+場景敘事:**好**;anomaly flag:**中上** |
| **Qwen3-VL-4B-Instruct** | 4B | Q4_K_M ~3.3 GB,6 GB VRAM 可跑 | 比 8B 快約 1.5–2×(估計) | DocVQA ~91、OCRBench ~85 —— 損失小、換到可在 8 GB VRAM 筆電和 iGPU 上舒服跑。**本案甜蜜點** |
| **Qwen2.5-VL-7B** | 7B | Q4 ~6 GB | 同 8B 級 | 上一代 workhorse(DocVQA 95.7),生態最熟;被 Qwen3-VL 全面取代中 |
| **MiniCPM-V 4.5 / 4.6** | 8B | int4/GGUF ~5–6 GB | 手機 CPU 上 6–8 tok/s(前代實測),PC GPU 同 8B 級 | 主打 edge:llama.cpp/Ollama 官方支援、視訊 token 96× 壓縮。場景敘事**好**;OCR 略遜 Qwen3-VL |
| **Gemma 3 4B(QAT)** | 4B(SigLIP-400M encoder) | **int4 僅 2.6 GB**(12B=6.6 GB,可跑 8 GB RTX 4060 Laptop) | 4B 在 iGPU/CPU 皆輕 | 通用視覺理解**中**(MMMU 48.8),OCR 弱於 Qwen;優勢是 4 GB 級硬體也能跑、Google QAT 品質好 |
| **Moondream 3 (preview)** | 9B MoE(**2B active**) | 未有官方 GGUF 主線;HF weights,另有 Moondream Station | 推論成本近 2B 模型 | 特化技能:**pointing / counting / open-vocab detection / segmentation**(RefCOCO+ 79.1 mIoU)。對「元件在哪、有幾個」這類 grounded 問題同級最強;自由敘事較弱;工具鏈(transformers/自家 runtime)較非主流 |
| **Phi-4-multimodal** | 5.6B | ONNX int4 約 4–5 GB(估計) | DirectML/QNN 路徑 | vision+audio+text、128K context;MS 官方 ONNX/NPU 資產齊 —— 是 ONNX Runtime/QNN 路線的預設選擇,但視覺基準遜於 Qwen3-VL |
| **OmniNeural-4B** | 4B | NPU 專用格式 | Snapdragon X Elite NPU 實測可跑、圖片理解「decently well」(定性) | **唯一為 Hexagon NPU 原生設計的多模態模型**;能力級別低於 Qwen3-VL-4B,但「跑在我們自己 NPU 上」的敘事價值高 |
| **SmolVLM2-2.2B / FastVLM** | 0.5–2.2B | ~2 GB | 極快、可 CPU | 場景粗描述**可**、精細辨識**弱**;只當資源下限的保底 |

(2606 系列 arXiv 佐證你們既有結論不變:pin-level 精度沒有任何 7B 級模型能做,本調查所有模型都只夠格做 component-level 與敘事層。)

---

## 3. Latency reality check(每張 keyframe 的端到端秒數)

- **(a) 中階筆電 GPU(RTX 4060 Laptop 8GB 級)**:7–8B VLM Q4 的**首 token 延遲典型 2–5 秒**(標準單圖),之後 decode 數十 tok/s;CUDA 上 vision encoder 一個 image slice 約 **170 ms**(llama.cpp 實測數據)。一段 60–100 token 的敘事,**端到端約 3–6 秒/幀**;4B 模型約 **1.5–3 秒/幀**(估計)。→ 0.2–0.5 Hz 舒適,1 Hz 要用 4B + 短輸出 + 丟幀策略。
- **(b) CPU-only(x64)**:decode 僅 **2–15 tok/s**,且 vision encode 是大頭(行動級 CPU 上 clip encode 實測曾達 ~18 秒;桌面 CPU 較好但仍以秒計)。7–8B 模型**端到端 15–40 秒/幀(估計)**,不符 0.2 Hz;Gemma 3 4B / 2B 級**約 5–15 秒/幀(估計)**,勉強及格。**CPU-only 機器上 VLM 只能做「使用者主動觸發」的 ai_hint,不能做連續 narration** —— 這正好符合你們 advisory-only 的設計。
- **(c) Snapdragon X NPU(Hexagon 45 TOPS;X2 Elite 已宣布 80 TOPS)**:NPU 的強項是 prefill——實測 **786.7 tok/s prefill(GPU 同機僅 25.2)**,所以「一張圖+短 prompt」的 TTFT 可壓到 1 秒級(AI Hub 8B 級模型卡:TTFT 0.21–6.77 秒);但 decode 受記憶體頻寬限制,8B 級約 **10 tok/s**、4B 級更快。4B 多模態**端到端估 3–8 秒/幀(估計;OmniNeural-4B 僅有定性實測)**。可參照數量級:Qualcomm 自家 48 TOPS 平台宣稱 512×512 vision model **~1.7 秒**、3B LLM 45 tok/s。→ 0.2–0.5 Hz 可行,且功耗遠優於 GPU。

---

## 4. FastAPI 整合模式

四條路收斂成同一種寫法:**Ollama、llama-server、LM Studio、GenieX 全都提供 OpenAI 相容 HTTP API**(`POST /v1/chat/completions`,image 以 base64 `image_url` 傳入,`stream: true` 走 SSE)。因此:

- 後端新開一個 `VlmWorker`(比照 WireTraceWorker 的獨立 reader thread / async task),從 FrameBus 取 keyframe(0.2–1 Hz)、JPEG 編碼、用 `httpx.AsyncClient` 打 `http://127.0.0.1:11434/v1/chat/completions`(Ollama)或 `:8080`(llama-server)。
- **latest-only 語意照搬你們 WS queue 的做法**:上一張還在推論就丟棄新 keyframe,永遠只排最新一張 —— VLM 秒級延遲下這是必須的。
- Streaming:narration 用 SSE token stream 轉發到你們的 WS(新 message type 如 `ai_narration`,與 `detection`/`wire_trace` 並列);ai_hint 則等完整 JSON(用 Ollama 的 `format: json` / llama.cpp grammar 强制 schema)再進 GuidanceResult 的 advisory 欄位。
- Ollama 另有原生 `/api/chat`(`images` base64 陣列)與官方 python client;llama.cpp 也可用 python binding 內嵌,但 subprocess + HTTP 隔離性較好(VLM 崩潰不拖垮 pose tracking)。
- Snapdragon 上:GenieX 的 OpenAI 相容 server / Python SDK 讓**同一份 client code 不改**,只換 endpoint。

---

## 5. 決斷建議

**主路徑(primary):Qwen3-VL(8B Q4;8 GB VRAM 以下機器自動降 4B)+ llama.cpp 系 runtime,經 OpenAI 相容 API 接入 FastAPI。** 開發/demo 用 Ollama(零運維、`qwen3-vl` 官方庫、Windows 原生),出貨形態換成隨附的 `llama-server` subprocess(MIT 授權、可控版本、離線單目錄部署)。理由:(1) 同尺寸下 OCR/文件/grounding 最強,元件絲印("HC-SR04")辨識直接吃 OCR 能力;(2) GGUF+mmproj 生態最成熟、x64 CUDA/Vulkan/CPU 全覆蓋,保住「零雲端、可離線」的既有部署性質;(3) 4B→8B 同家族可依硬體分級,prompt 不用改。

**備援/戰略路徑(fallback):Snapdragon X ARM64 機器上改用 Qualcomm GenieX(或 NexaSDK + OmniNeural-4B / Qwen3-VL)跑 Hexagon NPU,同樣走 OpenAI 相容 endpoint。** 理由:今天唯一真正把 VLM 放上 Snapdragon NPU 的實證路徑(Ollama/LM Studio 在 ARM64 只用 CPU;Foundry Local 尚無 vision catalog);TTFT 佔優、功耗低,而且直接兌現「在 NPU AI PC 上跑」的 pitch 賣點。風險要照實講:GenieX 是 developer preview、OmniNeural-4B 只有定性評測 —— 所以它是 fallback / 戰略展示,不是 primary。

不選的理由備忘:Foundry Local(無 vision 模型)、ONNX Runtime GenAI 直用(僅 Phi 系 vision、自轉模型成本高)、Moondream 3(能力誘人 —— 若日後要「指出元件位置」的 grounded pointing,值得單獨評測 —— 但 runtime 非主流且 9B MoE 部署鏈不齊)。

---

## Sources

- Ollama multimodal engine: https://ollama.com/blog/multimodal-models ; vision 模型庫: https://ollama.com/search?c=vision ; minicpm-v4.5/4.6: https://ollama.com/openbmb/minicpm-v4.5:8b
- llama.cpp multimodal (libmtmd): https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md ; server vision PR: https://github.com/ggml-org/llama.cpp/pull/12898 ; FOSDEM 2026 talk: https://fosdem.org/2026/schedule/event/LRZJEH-llama-cpp-multimodal/ ; CPU-encode 82s issue: https://github.com/ggml-org/llama.cpp/issues/22582 ; CUDA 170ms/slice、Metal 5s: https://github.com/ggml-org/llama.cpp/issues/14527 ; 行動 CPU encode 18s: https://github.com/ggml-org/llama.cpp/issues/11856
- LM Studio Snapdragon/ARM64: https://lmstudio.ai/snapdragon ; system requirements: https://lmstudio.ai/docs/app/system-requirements ; Qwen2.5-VL: https://lmstudio.ai/models/qwen/qwen2.5-vl-7b
- ONNX Runtime GenAI Phi vision (DirectML): https://onnxruntime.ai/docs/genai/tutorials/phi3-v.html ; https://huggingface.co/microsoft/Phi-3.5-vision-instruct-onnx ; Snapdragon NPU 模型資產: https://onnxruntime.ai/docs/genai/howto/build-models-for-snapdragon.html
- Foundry Local(無 vision catalog、OpenAI 相容、NPU 自動偵測): https://github.com/microsoft/Foundry-Local ; AMD NPU + Windows ML: https://www.amd.com/en/developer/resources/technical-articles/2026/ai-model-deployment-using-windows-ml-on-amd-npu.html
- Qualcomm GenieX(LLM+VLM、Snapdragon X Windows ARM64、Python SDK、OpenAI 相容 server、developer preview): https://github.com/qualcomm/GenieX ; https://geniex.aihub.qualcomm.com/en/get-started/what-is-geniex
- NexaSDK / OmniNeural-4B: https://github.com/qualcomm/nexa-sdk ; https://www.qualcomm.com/developer/blog/2025/09/omnineural-4b-nexaml-qualcomm-hexagon-npu ; Snapdragon X Elite NPU 實測: https://www.xda-developers.com/these-llms-run-locally-snapdragon-x-elite-npu-surprisingly-good/
- Snapdragon X Elite NPU prefill/decode 實測(786.7 vs 25.2 tok/s): https://arxiv.org/html/2606.11257v1 ; AI Hub 8B 模型卡 TTFT/tok/s: https://huggingface.co/qualcomm/Allam-7B ; X2 Elite 80 TOPS(CES 2026): https://futurumgroup.com/insights/qualcomm-unveils-future-of-intelligence-at-ces-2026-pushes-the-boundaries-of-on-device-ai/ ; 48 TOPS 平台 vision ~1.7s: https://www.techpowerup.com/350061/qualcomm-announces-snapdragon-reality-elite-platform
- Qwen3-VL 4B/8B 基準與 VRAM: https://codersera.com/blog/qwen3-vl-4b-vs-qwen3-vl-8b-benchmarks-vram-guide/
- 本地 vision 模型總覽(GPU tier、tok/s、首 token 2–5s、CPU 2–15 tok/s): https://insiderllm.com/guides/vision-models-locally/
- MiniCPM-V(edge 部署、手機 6–8 tok/s): https://github.com/openbmb/MiniCPM-V ; Nature Communications: https://www.nature.com/articles/s41467-025-61040-5
- Gemma 3 QAT(2.6/6.6/14.1 GB int4、SigLIP、RTX 4060 Laptop): https://developers.googleblog.com/en/gemma-3-quantized-aware-trained-state-of-the-art-ai-to-consumer-gpus/
- Moondream 3 preview(9B MoE/2B active、grounding 技能): https://moondream.ai/blog/moondream-3-preview ; https://huggingface.co/moondream/moondream3-preview
- Phi-4-multimodal(5.6B、text+vision+audio、128K): https://techcommunity.microsoft.com/blog/educatordeveloperblog/welcome-to-the-new-phi-4-models---microsoft-phi-4-mini--phi-4-multimodal/4386037 ; https://ai.azure.com/catalog/models/Phi-4-multimodal-instruct
- WSL 3 GPU/NPU passthrough(Build 2026): https://www.techtimes.com/articles/317598/20260602/wsl-3-build-2026-near-native-gpu-npu-passthrough-brings-local-ai-windows.htm
- FastVLM/SmolVLM2 效率比較: https://arxiv.org/html/2412.13303v2

---

# 附錄 B：雲端 LLM 結構化接線計畫生成調研（研究原文）

# 雲端 LLM 生成結構化接線引導計畫(GuidancePlan)— 現況與建議(2026 年中)

## 1. Structured output 可靠性:語法層已解決,語意層沒有

**三大 API 現況(皆為 constrained decoding,非 prompt 祈禱):**

- **Anthropic**:Structured Outputs 於 2025-11 以 beta 推出(`output_format` + `structured-outputs-2025-11-13` header),2026 GA 移至 `output_config.format`,並有 `strict: true` 的 strict tool use 可對 tool input 做 schema 保證。實作方式是把 JSON Schema 編譯成 grammar 在解碼時逐 token 約束(首次編譯有延遲,快取 24h)。**官方文件明白警告:保證 schema 合規,不保證語意正確**。限制:不支援遞迴 schema、不支援數值約束(`minimum`/`maximum`)與字串長度約束——這些會被 SDK 靜默剝除,只留在 description 裡([官方文件](https://platform.claude.com/docs/en/docs/build-with-claude/structured-outputs)、[Tessl 報導](https://tessl.io/blog/anthropic-brings-structured-outputs-to-claude-developer-platform-making-api-responses-more-reliable/))。
- **OpenAI**:2024-08 起 `response_format: json_schema` + `strict: true`,官方宣稱其複雜 schema 內部評測從 prompt-only 的 <40% 提升到 100% schema 合規([OpenAI 公告](https://openai.com/index/introducing-structured-outputs-in-the-api/))。
- **Google Gemini**:`responseSchema` + `responseMimeType: "application/json"`,schema 是 OpenAPI 3.0 子集,常用關鍵字可用、進階 JSON Schema 特性不完整([Google 開發者部落格](https://developers.googleblog.com/en/mastering-controlled-generation-with-gemini-15-schema-adherence/))。
- **跨供應商實測**(2026-05,244 個模型、23 家供應商):約 82%(199/244)通過全部 structured output 測試;三家 API 形狀互不相容;Anthropic 拒收遞迴 `$ref` 而 OpenAI/Google 接受([Requesty 實測](https://www.requesty.ai/blog/structured-outputs-across-llm-providers-the-compatibility-mess))。

**還會失敗的部分(對本案最重要):**

- **語意錯誤藏在合法 schema 裡**:The Structured Output Benchmark 發現前沿模型 schema validity 普遍 >90%,但 field-level 值正確率顯著更低;失敗型態包括「格式合法但憑空捏造的值」、部分抽取、語意類別錯置([arXiv 2604.25359](https://arxiv.org/pdf/2604.25359))。對我們而言:`expected_pin_id: "D13"` 完全合法地通過 schema,即使 D13 電氣上完全錯誤。
- **schema 寬度退化**:ExtractBench 顯示 schema 欄位數增加時前沿模型急遽退化,369 欄位的 schema 上有效輸出掉到 0%([arXiv 2602.12247](https://arxiv.org/html/2602.12247v2))。GuidancePlan 的 schema 很小(<30 欄位),不在危險區,但這是「保持 schema 扁平小巧」的硬理由。
- **約束解碼可能損傷推理品質**:有研究指出格式限制會降低推理表現([arXiv 2408.02442](https://arxiv.org/pdf/2408.02442)),也有反駁指出 schema 設計得當時效應近乎消失([dottxt 反駁](https://blog.dottxt.co/say-what-you-mean.html));2026 的評測仍觀察到 GPT-5/Gemini 系列在某些任務上 instruction-following 的欄位值準確率高於 API 約束生成([FutureAGI 評測](https://futureagi.com/blog/evaluating-llm-structured-output-modes-2026/))。另見 [JSONSchemaBench](https://arxiv.org/pdf/2501.10868)(10K 真實 schema,各約束引擎覆蓋率/效率差異)。

**結論**:parse 錯誤在 2026 已是已解決問題,直接用即可;但 schema 合規對本案的價值只到「省掉 retry 迴圈」為止。**語意層(腳位選對沒有)百分之百要靠驗證層**——這正是 Anthropic 自家文件的建議。

## 2. 驗證層 pattern:先例充分,且硬體領域的錯誤型態正好是確定性檢查抓得到的那種

**通用先例(generate-then-validate 是成熟 pattern):**

- 古典 planning 領域用 **VAL** 對 LLM 產生的 PDDL 計畫做確定性驗證(逐 action 檢查 precondition、回報第一個失敗點)已是標準做法,且驗證回饋餵回 LLM 可迭代收斂([formal methods 案例研究 arXiv 2510.03469](https://arxiv.org/html/2510.03469v2)、[symbolic feedback 迭代精煉 arXiv 2606.27757](https://arxiv.org/pdf/2606.27757))。
- Function calling 界的標準評測 **BFCL** 本身就是用 AST 確定性比對函式名/參數合法性——等於整個行業承認 LLM 的結構化呼叫必須事後機器驗證([BFCL](https://gorilla.cs.berkeley.edu/leaderboard.html))。

**硬體/接線領域的直接證據(比想像中多,但沒有一個是「maker 接線教學步驟」的 dedicated benchmark——這點誠實承認):**

- **From Words to Wires**(EMNLP 2023 Findings):最接近本案的先行研究。PINS100 測元件腳位知識、MICRO25 測 Arduino 生態系電路+程式生成;GPT-4/Claude-V1 在完整裝置生成拿 60–96% Pass@1(人工驗證)([論文](https://aclanthology.org/2023.findings-emnlp.864.pdf))。即最佳情況下也是「三步錯一步」量級——單步驟錯誤在多步接線計畫裡會複利。
- **HWE-Bench**(2026):300 個板級設計任務、2,914 份 datasheet。靜態規則檢查平均通過率 71.84%(最佳 Claude Sonnet 4.5 為 77.73%);動態 SPICE 模擬掉到 58.65%;**完全正確的設計最佳只有 8.15%**。主要錯誤型態:pin multiplexing 衝突(把互斥功能派到同一腳)、模組間角色混淆、對語意不明顯的腳位名(非 CLK/RST 這類)表現更差([arXiv 2603.18102](https://arxiv.org/html/2603.18102))。它的驗證器設計(pin-locking、先靜態規則後模擬)就是我們 board-profile lint 的學術先例。
- **CircuitLM**(2026):多代理框架 + DMCV 驗證(確定性檢查:pin 存在性、net assignment、schema 合規;加 LLM 評審)。關鍵發現:**經檢索接地(grounded)到已驗證元件庫後,library compliance 接近滿分(~9.9/10),但電氣邏輯仍變異大**;模型會幻覺出不存在的腳位、漏掉限流電阻([arXiv 2601.04505](https://arxiv.org/html/2601.04505v1))。
- 觀察到的錯誤型態(幻覺腳位、多工衝突、無視電壓限制)**正好全是確定性 lint 可以 100% 攔截的類別**——這是驗證層 pattern 在本案特別划算的原因。

## 3. Grounding 策略:這不是 RAG 問題,是精確查表問題

對 50–500 個元件的目錄,決策很清楚:

- **board profile + 相關 ComponentSpec 全文放 in-context,用 ID 精確查表取回,不用向量 RAG,不 fine-tune。**
- 理由:單次 plan 只涉及 1–5 個元件;每份 ComponentSpec 約 1–2KB,board.json 也就幾 KB——單次請求的接地材料遠低於 10K token。2026 年的共識是總量 <100K token 直接進 context、跳過檢索([決策指南](https://niteagent.com/blog/llm-context-2026-rag-vs-long-context/)、[生產決策框架](https://tianpan.co/blog/2026-04-09-long-context-vs-rag-production-decision-framework)、[token 成本比較研究 arXiv 2606.20898](https://arxiv.org/pdf/2606.20898))。向量 RAG 在這個規模只會引入一種新的失敗模式(檢索錯元件),而目錄本來就有結構化 ID,語意檢索毫無必要。
- **CircuitLM 的實證直接支持這個方向**:接地到已驗證元件資料庫讓 library compliance 近乎滿分——換句話說,幻覺腳位問題主要靠「把正確 pin 表放進 context」+「事後驗證」解決,不靠模型記憶。
- **不 fine-tune** 的理由:目錄會演化、500 筆規模太小不值得、且燒進權重的知識無法在 runtime 附版本驗證(provenance 斷裂);HWE-Bench 顯示即使給 datasheet,模型對冷門料件依然不可靠,所以重點是驗證器而非模型記憶。
- 成本面:靜態前導(系統提示 + board.json pin 表)用 prompt caching,實測可省 30–50% input token 成本([2026 快取比較](https://technspire.com/en/blog/prompt-caching-2026-real-cost-wins))。

## 4. 多模態進件:VLM 認模組——只能當提案者,不能當權威(證據誠實地薄)

**誠實結論:截至 2026 年中,沒有針對「maker 生態模組照片辨識 + 絲印腳位標籤判讀」的公開 benchmark。** 最接近的旁證:

- **AMSbench**:MLLM 對電路圖感知/分析/設計約 8,000 題,結論是現有 MLLM 在電路感知與複雜推理上有「顯著限制」,離全自動流程很遠([arXiv 2505.24138](https://arxiv.org/pdf/2505.24138))。
- **FPIC**(PCB 光學保障資料集):絲印標示是判定元件功能的關鍵訊號,結合絲印文字可顯著提升元件識別——證明「讀絲印」這條路資訊上成立([arXiv 2202.08414](https://arxiv.org/pdf/2202.08414));[UniPCB](https://arxiv.org/pdf/2601.19222) 也在做 VLM 的 PCB 開放式檢測。
- 通用 VLM OCR 在文件類影像上很強([多模態 OCR 模型總覽](https://huggingface.co/blog/prithivMLmods/multimodal-ocr-vlms)),但模組絲印是小字、低對比、反光、常被手指遮擋的另一個 regime,無直接測評數據——**未知,就說未知**。
- 本專案自己的既有證據(走線追蹤最佳 71%、DiffSpot 召回 40.7%、實測 VLM 自信誤報 5V 插線)已經確立:VLM 在此領域會「自信且錯」。

**因此設計上比照既有 `ai_hint` 的先例:VLM 是提案者,目錄是權威。** VLM 的輸出是「候選 catalog ID + 信心值 + 證據(讀到的絲印字串)」,交使用者確認;**計畫中使用的腳位映射永遠來自策展過的 ComponentSpec,絕不來自照片**。辨識也不是開放問題——是對 50–500 筆已知目錄的封閉分類,VLM 做這件事遠比開放場景可靠。目錄沒有的模組走明確的「不支援/請提供規格」路徑,不退化成照片推腳位。

## 5. 建議的 API 形狀(決斷版)

兩階段,驗證層放在**服務端、LLM 之後、使用者之前**。沿用既有 `200 + ok:true/false` 慣例。

**Phase 1(僅有照片時)`POST /api/design/components/identify`**

```json
// req: { "photos": ["<base64>"], "hint_text": "藍色的超音波模組" }
// res: { "ok": true, "needs_confirmation": true,
//   "candidates": [ { "component_id": "hc-sr04", "display_name": "HC-SR04 超音波測距",
//                     "confidence": 0.86, "evidence": { "silkscreen_read": ["HC-SR04","VCC","Trig","Echo","GND"] } } ] }
```

使用者在 UI 點選確認 → 得到已確認的 `component_ids`。VLM 在此只做封閉目錄分類,結果必經人工確認。

**Phase 2 `POST /api/design/plan`**

```json
{ "goal": "接超音波感測器並顯示距離",
  "board_id": "arduino-uno-q",
  "component_ids": ["hc-sr04"],
  "constraints": { "reserved_pins": ["D0","D1"], "locale": "zh-TW" } }
```

服務端管線:

1. **組稿**:prompt-cached 靜態前導 + `board.json` 完整 pin 表 + 按 `component_id` 精確查表取回的 ComponentSpec 全文。
2. **LLM 呼叫**:Anthropic `output_config.format`(或等價 OpenAI/Gemini)產出 GuidancePlan——這一步只保證 parse 得動,別的什麼都不保證。schema 保持扁平、不放數值約束(反正 Anthropic 不支援 `minimum`/`maximum`,SDK 會剝掉)。
3. **確定性驗證鏈(純程式,無模型參與)**:
   - a. pydantic StrictModel 對**原始 schema** 重新驗證(防禦縱深:補上約束解碼不支援的數值/長度限制);
   - b. **引用存在性**:每個 `expected_pin_id` 必須存在於 board profile;每個 `terminal` 必須存在於該 ComponentSpec 的 roles;
   - c. **電氣 lint**(規則直接來自 `board.json`):電壓相容(A0/A1 絕不容 5V、D3 上限 3.6V)、能力匹配(要 PWM 就必須是 PWM 腳)、一腳一線衝突、電源預算;
   - d. **計畫級 lint**:每個 terminal 恰好接一次、GND 先於訊號線的排序、無懸空步驟。
4. **失敗處理**:把機器可讀的違規清單餵回 LLM 修復,**最多重試 2 次**,仍失敗就回 `ok:false` + violations 陣列。**驗證器永不放寬,寧可明確失敗。**(驗證回饋迭代收斂有實證支持,見 §2 的 symbolic feedback 文獻。)

回應:

```json
{ "ok": true,
  "plan": { "plan_id": "…", "board_id": "arduino-uno-q",
    "steps": [ { "step_id": 1, "component_id": "hc-sr04", "terminal": "TRIG",
                 "expected_pin_id": "D7", "expected_role": "TRIG",
                 "tutorial_text": "把 Trig 腳接到 D7…", "why": "D7 為一般 GPIO,3.3V 輸出對 Trig 足夠" } ] },
  "validation": { "passed": true,
    "checks": [ { "check": "pin_exists", "ok": true },
                { "check": "voltage", "ok": true, "detail": "ECHO→D8: five_volt_tolerant==true" } ] },
  "provenance": { "model": "…", "board_profile_version": "…", "component_spec_versions": { "hc-sr04": "…" } },
  "warnings": [] }
```

**設計要點(對齊既有架構):**

- `steps[]` 逐條直接餵進既有的 `POST /api/guidance/step`(`expected_pin_id` + `expected_role`)——雲端計畫是本地古典打勾引擎的**上游輸入**,權威的 correct/incorrect 判定仍完全留在本地幾何管線,約束 #1 不動。
- `tutorial_text`/`why` 是給人看的 advisory 文字(信任等級同 `ai_hint`);`expected_pin_id` 是經過機器驗證的合約欄位——兩種信任等級在 schema 裡就分開。
- 驗證放服務端而非客戶端的理由:驗證器需要 board.json 與 ComponentSpec 的權威版本(provenance 可追溯);客戶端只會收到已通過驗證的計畫,`validation.checks` 隨附是為了透明與除錯。
- 模型選擇上三家皆可(schema 小,都在能力範圍內);差異只在 schema 方言,故 schema 設計取三家交集(無遞迴、無數值約束),範圍檢查一律下沉到驗證器。

**一句話總結**:2026 年的實證格局是——schema 合規靠 constrained decoding 已可視為免費;腳位級語意正確在最好的 benchmark 上仍只有 ~72–78% 單項檢查通過率、<10% 全對率;而失敗型態(幻覺腳位、電氣違規)恰好全部落在確定性驗證器的射程內。所以正確架構就是本專案已在別處驗證過的同一個哲學:**LLM 生成、機器驗證、advisory 與 authoritative 欄位分離、never guess**。

**主要來源**:[Anthropic Structured Outputs 文件](https://platform.claude.com/docs/en/docs/build-with-claude/structured-outputs) · [OpenAI Structured Outputs](https://openai.com/index/introducing-structured-outputs-in-the-api/) · [Gemini Controlled Generation](https://developers.googleblog.com/en/mastering-controlled-generation-with-gemini-15-schema-adherence/) · [Requesty 244 模型實測](https://www.requesty.ai/blog/structured-outputs-across-llm-providers-the-compatibility-mess) · [Structured Output Benchmark](https://arxiv.org/pdf/2604.25359) · [ExtractBench](https://arxiv.org/html/2602.12247v2) · [JSONSchemaBench](https://arxiv.org/pdf/2501.10868) · [格式限制與推理](https://arxiv.org/pdf/2408.02442) · [HWE-Bench](https://arxiv.org/html/2603.18102) · [CircuitLM/DMCV](https://arxiv.org/html/2601.04505v1) · [From Words to Wires](https://aclanthology.org/2023.findings-emnlp.864.pdf) · [BFCL](https://gorilla.cs.berkeley.edu/leaderboard.html) · [LLM 計畫形式化驗證](https://arxiv.org/html/2510.03469v2) · [Symbolic feedback 迭代精煉](https://arxiv.org/pdf/2606.27757) · [AMSbench](https://arxiv.org/pdf/2505.24138) · [FPIC](https://arxiv.org/pdf/2202.08414) · [UniPCB](https://arxiv.org/pdf/2601.19222) · [RAG vs 長上下文決策框架](https://tianpan.co/blog/2026-04-09-long-context-vs-rag-production-decision-framework) · [Token 成本研究](https://arxiv.org/pdf/2606.20898) · [Prompt caching 成本](https://technspire.com/en/blog/prompt-caching-2026-real-cost-wins)
