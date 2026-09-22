# Board Vision — API 契約（前後端 / CV 模組共同依據）

版本：1.1（改動需同步 frontend `src/lib/types.ts`、backend `app/api/`、本文件）

## 1. HTTP 端點（後端 `127.0.0.1:8100`）

### `GET /api/tracking/frame?after=<seq>`（Pi 即時追蹤試版）

回傳同幀 JPEG data URL（`image`）、`detection`、`components`、`seq`、`frame_id`、
`ts_ms`、`runtime_revision`、`board_id`、`processing_ms`、`display_only: true`。
Pi、HC-SR04、HW-123、MRD-TF240-8P-CS 的顯示座標與 JPEG 同幀；
每個目標有獨立追蹤與失效狀態，均只從可靠的同幀模型姿態初始化。
可靠追蹤為 `tracking: locked`、`pose_quality.stability: optical_flow`；
局部支持不足但仍有有效平面匹配時，只回傳 `tracking: stale`、`pins: []`，
並以 `pose_quality.stability: optical_flow_partial`、`outline_only: true`、
`support_ratio` 與 `reason` 標示外框專用狀態。這不是精準 Pin 或接線驗證。
失去匹配時不回傳舊座標；`flow_lost` 的 `interrupted: true` 表示曾追到，
`recovering` 表示尚在有限時間內嘗試接回，不表示目前仍有有效定位。
效能診斷欄位：`timing_ms: {gray, objects: {board, ...component_ids}, jpeg}`
均為毫秒；`recovery_searches` 為本幀 ORB 擴大搜尋次數（0 或 1），
`recovery_deferred` 為受到每目標冷卻或全幀搜尋排程限制的 ID 清單。
排程延後不會沿用舊座標；一般局部匹配仍可在當幀恢復。
其餘模組沿用原模型，只顯示淡化參考。
無新幀回 204；停用或非 Pi 回 404。僅供顯示，不更改既有 WS／接線驗證資料。
`GET /api/config` 的 `realtime_tracking` 表示目前控制器能否使用試版。
時效、遮擋處理與限制見 [即時追蹤](realtime-tracking.md)。

#### 語義腳位參考恢復（2026-09-13 16:33）

Pi 的 `yolo_pose.pi_reference_recovery_model_path` 僅用於ROI，校準板型參考的SIFT對應才決定GPIO座標。
HW的 `reference_pose` 則保存已核對實拍圖與語義角序。兩者都沿用原 `outline`／`pins`，不是額外框。
原始消息的 `pose_quality.reference_recovery` 包含 `accepted`、`reason`、`matches`、`inliers`、
`inlier_ratio`、`coverage`、`error_px`、`ms`；同步消息在 `pose_quality.model_source.quality` 保留來源證據。
Pi取得新參考姿態時 `pose_quality.path` 為 `reference_sift`；目前匹配成功不代表導通或接線正確。

#### 本體辨識（歷史可選診斷，現行綠框已移除）

目前 `body_fallback_model_path: null`，下述獨立Pi本體工作線停用；現行UI不渲染body。

四目標新增可選 `body`，與 `tracking`／`outline`／`pins` 的語義定位獨立。
原始 component WS 僅提供當次模型 `box: [x1,y1,x2,y2]`、`confidence`、`source`，
不直接在快速影像上畫舊框。同步端點中的 `body` 另含
`outline`（當前 JPEG 座標）、`frame_id`、`source_frame_id`、`age_ms`、`partial`、
`display_only: true`。原 `box` 是模型來源幀的框；顯示應使用同步後的 `outline`。
`body: null` 表示沒有當前本體影像支持。即使本體存在，`tracking: searching`、
`pins: []` 仍可成立，不可把本體框當作GPIO投影或接線檢查結果。

Pi 本體工作線獨立於 Hybrid 的特徵搜尋，預設最多2.86Hz、CUDA device0，
使用 `yolo_pose.body_fallback_model_path`（可設null停用）。三模組重用原模型觀察，
在腳位方向判定前擷取物件框。LK以同一來源圖片初始化、運送至當前畫面，
來源超過650ms或匹配失敗即隱藏；不延長舊框、不外推、不另做ORB擴大搜尋。
相機影格倒退／解析度或runtime revision變更會清除本體追蹤。
`GET /api/inference/status` 的 `body_fallback` 列出實際provider、次數與最大頻率。

### `GET /video`
MJPEG 串流（`multipart/x-mixed-replace; boundary=frame`）。前端用 `<img src="/video">` 顯示。
影像為「來源影像」：所有偵測座標都在這個像素空間（`video_size`）。

### `GET /api/config`
```json
{
  "board_id": "arduino-uno-q",
  "runtime_revision": 1,
  "default_locale": "zh-TW",
  "video_size": [1280, 720],
  "detector": "mock",
  "camera_source": "synthetic",
  "accuracy": {
    "status": "warning",
    "physical_gate_ready": false,
    "pitch_px": 10.3,
    "px_per_mm": 4.06,
    "min_pitch_px": 18.0,
    "min_px_per_mm": 8.0,
    "camera_calibrated": false,
    "camera_quality_ok": false,
    "camera_quality_status": null,
    "camera_rms_reprojection_error_px": null,
    "camera_max_view_rms_px": null,
    "camera_coverage_fraction": null,
    "feature_count": 0,
    "warnings": ["camera.json is absent; pose uses the FOV fallback"]
  }
}
```
`accuracy` 是唯讀的 profile preflight 快照；`status:"ready"` 才代表尺度、相機校正品質與參考特徵快取都達到實體驗證門檻。它不代表辨識結果本身已通過真實標註資料驗收。

### `GET /api/controllers`、`POST /api/controllers/select`

`GET /api/controllers` 回傳目前可切換的 Controller、各自的模型狀態與 runtime revision：

```jsonc
{
  "current_board_id": "raspberry-pi-5",
  "runtime_revision": 1,
  "controllers": [{
    "board_id": "raspberry-pi-5",
    "name": {"zh-TW":"Raspberry Pi 5","en":"Raspberry Pi 5"},
    "active": true,
    "pose_landmarks": 8,
    "wiring_guide_available": true,
    "electrical_verification_available": false,
    "model": {
      "path": "models/board-pose-pi5-handheld-v2.onnx",
      "ready": true,
      "keypoint_count": 4,
      "preferred_8pt_path": "models/board-pose-pi5-8kpt.onnx",
      "preferred_8pt_ready": false,
      "fallback_active": true
    }
  }]
}
```

`POST /api/controllers/select` 接收 `{"board_id":"arduino-uno-q"}`。後端會先完整載入
Profile、模型、Query Service 與板卡專屬 worker，全部成功後才原子切換；相機與 `/video`
不重啟。成功回傳 `ok`、`changed`、`board_id`、遞增後的 `runtime_revision` 與
`guide_was_active`。失敗回傳穩定的 `error_code + params`，舊 Controller 繼續運作。

### `GET /api/boards/{board_id}`
回傳完整 board profile（`board.json` 驗證後原樣序列化，含 `pins[]`、`buses[]`、`groups{}`）。
前端啟動時抓一次，之後 capability card / filter 全部本地查詢。

### `GET /api/boards/{board_id}/pins/{pin_id}`
單一 pin 物件（結構同 profile 內的 pin）。404 = 不存在。

### `POST /api/query`
```json
// request
{ "text": "哪支腳可以接 servo?", "locale": "zh-TW" }
// response
{
  "answer": "可以用 D3、D5、D6、D9、D10、D11（支援 PWM）。注意：UNO Q 為 3.3V 邏輯。",
  "pin_ids": ["D3","D5","D6","D9","D10","D11"],
  "group": null,            // 或 bus/group id，例如 "i2c0"
  "matched": true            // false = 沒聽懂，answer 為建議提示
}
```

### `GET /`
服務 `frontend/dist` 靜態檔（SPA）。

## 2A. Wiring candidate and safety checks

幾何管線只輸出候選；電氣安全由獨立 Rule Engine 檢查，VLM 不得覆寫結果。

### `GET /api/components`

回傳目前 profile 目錄裡可用的固定模組規格（目前包含 `hc-sr04`、`led`、
`sg90-servo`）。`GET /api/components/{component_id}` 回傳單一原始規格；找不到時
仍回 `200` + `ok:false`。

### `POST /api/wiring/plans`

```json
{
  "component_id": "hc-sr04",
  "pin_assignment": { "VCC": "5V", "GND": "GND_D", "TRIG": "D7", "ECHO": "D8" }
}
```

回應固定包含 `ok`、`status`、`roles`、`issues`。`issues` 會明確列出缺腳、未知
board pin、重複占用、電壓風險、PWM/digital 能力不符、UART/I²C 角色對調，以及
`VCC/GND/common ground` 錯誤。這個端點是純資料檢查，不會碰 GPIO 或相機。

### `POST /api/wiring/check`

request 在上述欄位外可帶 `observations[]`：

```json
{
  "component_id": "hc-sr04",
  "pin_assignment": { "VCC": "5V", "GND": "GND_D", "TRIG": "D7", "ECHO": "D8" },
  "observations": [
    { "module_pin": "ECHO", "board_pin": "D8", "status": "candidate", "confidence": 0.82 }
  ]
}
```

觀測只能降低幾何計算的確定性；它不能把不安全的 electrical plan 升級成安全。

## 2. WebSocket `WS /ws/detections`

連線後先收到一則 hello：
```json
{ "type": "hello", "board_id": "arduino-uno-q", "runtime_revision": 1,
  "video_size": [1280, 720] }
```

之後以 ≤`detection_hz` 頻率收到偵測訊息（**只送最新狀態，不排隊**）：
```json
{
  "type": "detection",
  "board_id": "arduino-uno-q",
  "runtime_revision": 1,
  "frame_id": 18234,
  "ts_ms": 1721990000123.5,
  "tracking": "locked",          // "searching" | "locked" | "stale"
  "confidence": 0.94,
  "pose_mode": "hybrid_4pt",  // "pnp_8pt" | "hybrid_4pt" | "feature_fallback"
  "pose_landmarks_visible": 4,
  "video_size": [1280, 720],
  "geometry": { "pitch_px": 20.4, "px_per_mm": 8.03 },
  "pose_quality": { "path": "track", "inliers": 52, "reproj_px": 0.84,
                    "inlier_board_area_frac": 0.31 },
  "outline": [[812.1,201.4],[1104.9,214.0],[1096.3,431.8],[805.2,418.7]],  // 板框四角，可為 null
  "pins": [
    { "id": "D3", "x": 512.4, "y": 233.1, "c": 0.97, "v": true }
  ]
}
```

語意：
- Controller 切換成功時會先發布
  `{"type":"runtime_changed","board_id":"...","runtime_revision":2}`。前端必須丟棄
  revision 小於目前值的 detection，避免舊板卡 Pin 在切換後殘留。
- `searching`：找不到板子。`pins` 為空。前端顯示「請將 UNO Q 放入畫面」。
- `locked`：正常追蹤。前端全量渲染標記。
- `stale`：短暫遮擋/品質差。`pins` 為最後一次好姿態的凍結值 — 前端將 overlay 淡化至 ~40%，不移除。
- `v:false` 的 pin 在畫面外，前端不畫。
- `pose_quality.path` 為 `detect`/`track`/`stale` 時代表特徵管線，`yolo` 代表
  YOLO 四點定位後由板卡 Profile 幾何解出姿態；兩條路徑輸出的 pin 座標契約相同。
- 座標在 `video_size` 像素空間。前端須經 letterbox 轉換映射到顯示座標（見 §3）。
- `geometry` 是從目前已投影 pin lattice 算出的來源影像尺度，不是獨立的實體量尺。
  `pitch_px` 是同排相鄰腳位的推算腳距；J8 依奇偶實體腳號分排，避免把兩排距離或
  對角線當成腳距。`px_per_mm` 供 physical framing gate 使用，投影本身錯誤時此值
  也可能失真，不能單憑數值升高宣稱實體精度達標。
- `pose_quality` 是診斷用的幾何證據，不是另一個安全判定：`inliers` 是支撐姿態的
  特徵/追蹤點數，`reproj_px` 是其平均重投影誤差，`inlier_board_area_frac` 是這些點
  在 reference board 上的 convex-hull 覆蓋比例，`path` 表示本幀來自完整偵測、LK
  追蹤或暫存姿態。它用來識別「confidence 看似高但證據太少/太集中」的情況；沒有
  這些欄位的 mock/舊 client 仍屬合法訊息。
- Pi 5 未校正四點模式另提供選填 `image_motion_px`（相對最後接受影像的特徵位移
  p90）、`image_support`（通過前後向追蹤檢查的特徵數）、`pin_motion_px`（最終
  腳位候選相對上一組位置的位移 p90）。`deadband` 可能由新影像特徵證實靜止而保持
  原座標；缺乏影像證據時不使用這條捷徑，仍走既有遮擋／重新定位規則。這些值
  不代表逐孔對位或電氣驗證。更大的 Pin 更新需跨影格一致，與板框檢查分開處理。
- `pose_mode:"pnp_8pt"` 表示已用 C920 內參、四個板角與至少兩個 J8 點完成
  `solvePnPRansac + solvePnPRefineLM`，40 支 GPIO 由 `projectPoints` 直接投影；
  `hybrid_4pt` 表示四角 Homography；Pi 5 未校正時使用 J8 局部修正、不套用估算
  的高度視差，已校正時才可使用高度補償；
  `feature_fallback` 表示 YOLO 不可用時沿用特徵定位。
- `type` 欄位是擴充點：未來新增 `wiring_check`、`telemetry` 等訊息型別，前端忽略未知 type。

同一條 WS 連線上，另一個獨立執行緒（`WireTraceWorker`，見
`docs/wire-recognition-design.md`）以自己的節流頻率（預設 0.5s，非每偵測影格）
發布第三種 `type`，沿用同一個擴充點、同一個 `DetectionBroadcaster`（不是新
route、不是第二個 broadcaster）：

```jsonc
{
  "type": "wire_trace",
  "board_id": "arduino-uno-q",
  "frame_id": 18234,
  "ts_ms": 1721990000123.5,
  "board_tracking": "locked",
  "wires": [
    {
      "wire_id": 0, "color": "red", "confidence": 0.87, "ambiguous": false,
      "path": [[520.1,240.2],[540.5,238.9],[601.2,235.0]],
      "endpoint_a": { "kind": "pin", "pin_id": "5V", "confidence": 0.9 },
      "endpoint_b": { "kind": "floating", "px": [700.1,190.4], "confidence": 0.0 }
    }
  ]
}
```

`wire_trace` 也會附帶與來源影像同一幀的幾何遙測，供前端 debug、回放工具與
下游候選判斷使用：

```jsonc
{
  "video_size": [1280, 720],
  "geometry": {
    "pitch_px": 17.8,
    "px_per_mm": 2.54,
    "snap_radius_px": 27.6,
    "snap_radius_over_pitch": 1.55
  },
  "wires": [
    {
      "endpoint_a": {
        "kind": "pin",
        "pin_id": "D7",
        "confidence": 0.91,
        "distance_px": 3.2,
        "margin_px": 8.1,
        "snap_margin_px": 8.1,
        "normalized_px": [0.402, 0.335]
      },
      "endpoint_b": {
        "kind": "floating",
        "px": [700.1, 190.4],
        "confidence": 0.0,
        "normalized_px": [0.547, 0.264]
      },
      "connection": {
        "status": "candidate",
        "confidence": 0.48,
        "endpoints": [
          { "object_id": "arduino-uno-q", "pin": "D7", "kind": "pin", "position": [0.402, 0.335] },
          { "object_id": null, "pin": null, "kind": "floating", "position": [0.547, 0.264] }
        ]
      }
    }
  ]
}
```

欄位約定：`pitch_px` 是相鄰 header pin 的影像像素間距；`snap_radius_px` 由
`clip(1.55 * pitch_px, 8, 26)` 得出，因此換相機解析度或距離時，吸附尺度會跟著
畫面幾何調整。`snap_margin_px` 是最近與次近 pin 距離的差值；值小或缺失時，前端
必須顯示為 uncertain，不得升級成確定接線。`normalized_px` 和
`connection.endpoints[].position` 是 `[x / width, y / height]`，方便不同解析度
的回放與 UI 使用；對 `kind: "pin"` 的 endpoint，兩者指向該影格即時投影的
pin 中心，而不是線材骨架停止的像素。`floating`／`ambiguous_tie` 才以實際觀測到
的線材端點為座標；原始 `px`/`path` 仍保留在來源影像像素空間。

語意：
- `board_tracking`：跟 `detection` 訊息的 `tracking` 同一組值（`searching`/`locked`/`stale`）——這是產生這批 wire trace 時，板子姿態當時的追蹤狀態，不是 wire tracing 自己的狀態機。`board_tracking=="searching"` 時 `wires` 必為空（沒有已知腳位可吸附，直接跳過整個 tick，不產生假的空列表訊息）。
- `wires[].endpoint_a`/`endpoint_b` 的 `kind` 三選一，絕不猜測填補：
  - `"pin"` — 吸附到唯一一個已知腳位：`{ "kind": "pin", "pin_id": "5V", "confidence": 0.9 }`（無 `px`）。
  - `"floating"` — 沒有任何腳位在吸附半徑內：`{ "kind": "floating", "px": [700.1,190.4], "confidence": 0.0 }`（無 `pin_id`）。
  - `"ambiguous_tie"` — 2 個以上腳位等距，不亂猜：`{ "kind": "ambiguous_tie", "px": [...], "candidates": ["D7","D8"], "confidence": 0.0 }`（`candidates` 取代 `pin_id`）。
- `ambiguous`（整條線層級）代表 trace 過程中經過至少一個骨架交叉點，用最小曲率啟發式續接，不是幾何保證的路徑——即使兩端都 resolve 到具體 pin，UI/AI 回應仍應降級措辭。
- `suppressed_reason:"scale_below_minimum"` 代表板子姿態雖然是 `locked`，但實際 delivered stream 的相鄰 header pitch 低於 18px；此 tick 不發布任何 wire，避免低解析度影像產生假 endpoint。導引同步回 `uncertain`，`reason:"scale_unready"`。
- 導引判定對與目標或本步驟新端點相關的 `ambiguous` wire 會回 `uncertain`（`reason:"wire_path_ambiguous"`），不會因 endpoint 恰好吸附到目標 pin 而打勾；已存在於 baseline 且與本步驟無關的交叉線不會阻塞其他步驟。
- `color` 只是輔助資訊（HSV 分色結果），不是接線正確性的判斷依據。
- 前端對未知 `type` 已是「忽略」（本節開頭已述）：純加法，不影響既有 `hello`/`detection` 訊息的形狀或既有客戶端行為。
- 兩種訊息共用同一個 per-client 單槽佇列（見 `app/api/ws.py` 的「latest-only」設計）：佇列裡永遠只留「最新一則」，不分 type。正常情況下 client 消費速度遠快於兩者的發布頻率，不構成問題；在真的很慢的連線上，`wire_trace` 有機會被緊接著發布的 `detection` 覆蓋掉（反之亦然）——跟現有「slow client 只拿得到最新狀態、不排隊」的既定語意一致，不是新引入的 bug。

啟用導引步驟（§8）時，`WireTraceWorker` 的同一個 tick 會再發布第四種
`type`（同一擴充點、同一 broadcaster；沒有作用中的步驟時完全不發）：

```jsonc
{
  "type": "guidance_check",
  "board_id": "arduino-uno-q",
  "step_id": "step-1-d7",
  "frame_id": 18234,
  "ts_ms": 1721990000123.5,
  "board_tracking": "locked",
  "expected_pin_id": "D7",
  "status": "wrong_pin",        // "pending" | "correct" | "wrong_pin" | "uncertain"
  "actual_pin_id": "D8",        // 僅 status=="wrong_pin" 時出現
  "source_wire_id": 3,           // verdict 使用的 wire provenance；可選
  "source_endpoint": "a",       // "a" | "b"；可選
  "confidence": 0.61,
  "reason": "endpoint_ambiguous", // status=="uncertain" 時可選；供 UI 說明原因
  "ai_hint": null                // M24/M29 的 advisory 欄位；目前恆為 null
}
```
語意（design doc：`docs/color-agnostic-wire-and-guidance-design.md` §2.2）：
- `status` 四值刻意不是布林：`pending`（還沒偵測到新端點，不是錯）、`correct`
  （目標腳位上有吸附端點）、`wrong_pin`（恰好一個**新**端點吸附到別的腳位，
  誠實點名 `actual_pin_id`）、`uncertain`（證據衝突：目標腳位落在某端點的
  `ambiguous_tie` 候選中、同一 tick 冒出 2+ 個新端點、或板子姿態 `searching`
  ——絕不硬猜成勾或叉）。
- 「新端點」= 相對步驟啟用當下快照的 `baseline_pin_ids` 的差集——啟用步驟前
  已插好的線永遠不會被指認為這一步的 `wrong_pin`。
- 判定 100% 由字串/集合比較產生（Stage D 已解析的 `pin_id`）；`ai_hint` 是
  輸出限定的 advisory 欄位，判定函式讀不到它。
- 權威狀態隨時可用 `GET /api/guidance/state` 同步讀回；WS 只是推播便利。

## 3. 前端座標轉換（letterbox）

`<img>` 以 `object-fit: contain` 顯示 `video_size = [vw, vh]` 的串流，元素實際尺寸 `[ew, eh]`（`getBoundingClientRect`）：
```
scale = min(ew/vw, eh/vh)
offx  = (ew - vw*scale) / 2
offy  = (eh - vh*scale) / 2
display_x = x * scale + offx
display_y = y * scale + offy
```
SVG overlay 與 `<img>` 完全重疊（同一個定位容器），viewBox 用元素座標或直接算好的 display 座標皆可，但 hover 命中半徑以 CSS px 計（≥24px）。

## 4. CV 模組介面（backend 內部）

`app/vision/interface.py` 的 `BoardDetector` Protocol / `DetectionResult`。規則：
- `detect()` 永遠回傳 `DetectionResult`（找不到就 `tracking="searching"` + 空 pins），不回傳 None
- pin 座標 = 來源影像像素空間
- `mock` / `pipeline` 由 `config.yaml: detector` 選擇；兩者對後端完全同形

## 5. Board profile

格式由 `backend/app/profiles/models.py`（runtime 真理）與 `schemas/board-profile.schema.json`（文件/CI）定義。
座標慣例：board 座標系原點 = 俯視圖 PCB 左上角（USB-C 朝左），x 向右、y 向下、z 垂直向上；
排針孔開口在 `z = board.header_top_z_mm`（≈8.5mm），**不是 z=0**。
`reference.mm_to_px` 為 board-mm → 參考圖像素的 3×3 homography。

Pi 5 profile 可選擇提供順序固定的 `pose_landmarks[]`：`board_TL`、`board_TR`、
`board_BR`、`board_BL`、`J8_P1`、`J8_P2`、`J8_P40`、`J8_P39`。板角使用 `z=0`；
J8 點可用 `pin_id` 引用 `pins[].pos_mm`，並取排針高度。舊 Profile 省略或提供空陣列時，
自動保留四板角契約。

## 6. `POST /api/calibrate` — 新增/校正板型

不是「每個使用者」的動作，而是「新增/取代某個板型的官方參考影像」— 一次性的目錄（Hardware
Capability Graph）維護動作，對應「校正板型」面板：前端把 dashed guide 矩形（依目前 board profile
的 `board.outline_mm` 長寬比）疊在即時影像上，指示使用者把板子外框對齊、USB-C 朝左、正面朝鏡頭；
使用者點「拍攝並登錄」時，guide 矩形四個角的螢幕座標本身就是板角對應點（不需再手動點孔位），連同
當前影格一起送出。

同一時間每個執行中的後端實例只服務一片板子（`config.board`）；沒有 `board_id` 參數 —
端點永遠(重新)校正目前這片已載入的板子，成功後熱替換掉正在跑的偵測器。

### Request

```json
{ "corners_px": [[x0,y0],[x1,y1],[x2,y2],[x3,y3]] }
```
- 恰好 4 個點，`[x, y]` 數字，座標系 = **來源影像像素空間**（與 WS 偵測 pin 座標、目前攝影機影格同一空間），**不是**顯示/CSS 像素。
- 順序：使用者對齊後的板子外框 TL、TR、BR、BL，依序對應 board-mm 角點 `(0,0)`、`(W,0)`、`(W,H)`、`(0,H)`（`W,H = profile.board.outline_mm`）。

### Response

任何情況（成功或預期內的失敗）一律回 **HTTP 200**，內容為以下兩種形狀之一：

成功：
```json
{
  "ok": true,
  "detector": "pipeline",
  "reference_features": 842
}
```

預期失敗：
```json
{
  "ok": false,
  "error_code": "corners_invalid",
  "params": {},
  "error": "corners_invalid"
}
```
`error_code` 為以下之一；`error` 暫時保留為舊客戶端相容別名。API 不回傳固定語言
`message`，前端依目前 locale 翻譯 `error_code + params`：
- `corners_invalid` — 不是恰好 4 個有限數值的 `[x,y]`，或四點（依 TL,TR,BR,BL 順序）不構成簡單凸四邊形，或其面積超出畫面面積的 `[1%, 95%]` 範圍。
- `no_frame` — 目前沒有可用的攝影機影格（等待 ~1 秒後仍無畫面）。
- `board_not_found` — 找不到目前設定的板型（正常執行中不應發生；防禦性錯誤碼）。
- `insufficient_scale` — 參考影像中的相鄰 header 腳位間距低於 physical gate（預設至少 18 px、8 px/mm）；會一併回傳 `pitch_px`、`px_per_mm` 與門檻，且**不會**寫入/覆蓋任何既有 profile 檔案。
- `insufficient_features` — 篩選到板子範圍內（含 8% 邊界容差）的特徵點數 < 200，判定該次拍攝不可用；**不會**寫入/覆蓋任何既有的 `board.json`、參考影像或 `features.npz`。

只有「請求本身格式錯誤」（JSON 形狀不對，例如欄位缺失或型別不對）或「真正未預期的伺服器錯誤」才使用真正的 HTTP 錯誤碼（400/422/500）；其餘一律是 200 + `ok:false`。

### 行為備註

- 成功時：以四個角點算出 board-mm → 影格像素的 homography，用目前影格重新計算參考特徵（ORB+SIFT），
  只保留落在板子輪廓 + 8% 邊界內的特徵點（濾掉使用者肉眼對齊時可能帶入的背景雜訊），備份既有的
  `board.json` 與參考影像（`<name><ext>.bak-<timestamp>`，與 `tools/calibrate_reference.py` 相同慣例），
  寫入新的參考影像、更新 `board.json` 的 `reference` 區塊、重算並覆寫 `features.npz`，然後用新設定
  重新載入 board profile、建立新的 `pipeline` 偵測器，熱替換掉執行中 VisionWorker 手上的偵測器
  （下一輪偵測立即生效，不需重啟服務）。
- `reference_features` = 過濾後、實際寫入 `features.npz` 的特徵點數。
- 成功回應也會回傳 `pitch_px` 與 `px_per_mm`，讓校正紀錄能直接確認本次影像尺度；這兩個值不是取代 checkerboard 相機內參校正的證據。

## 7. `GET /api/cameras`、`POST /api/cameras/select` — 攝影機列舉與即時切換

### Windows 裝置身分切換（2026-09-22 更新）

Windows 實體 OpenCV／FFmpeg 來源現在優先使用 DirectShow 裝置中繼資料，不為列舉而開啟攝影機。
清單包含 `index`、`device_id`、`name`、`selectable`、`available`、`is_current`，並回傳
`refreshable:true` 允許前端每兩秒重新整理。`selectable` 只表示能嘗試開啟，不表示已取得影像；
`available` 與縮圖只依目前來源兩秒內的新畫面。尚未選用的鏡頭不因缺縮圖而禁止選擇。

選擇請求傳 `{ "index": 1, "device_id": "<清單中的裝置身分>" }`，後端重新列舉後依
`device_id` 找裝置，不依可能改變的編號猜測。缺少或過期身分回 `camera_changed`；
健康的目前鏡頭回 `same_as_current`，沒有新畫面時允許重新連接。

依新鏡頭支援的 MJPEG 模式選解析度／FPS，暫停擷取與推論後更換來源，清除舊畫面和追蹤狀態，
確認三張時間遞增、非黑畫面才回 `ok:true`。不覆寫設定檔、不沿用前顆鏡頭的 UVC 控制或校正。
失敗會嘗試還原原來源：`restored:true` 也必須有新的有效畫面；原鏡頭已拔掉時不能假稱恢復成功。
不支援的格式回 `camera_modes_unavailable`，不猜測格式或反覆開啟驅動。
智慧調整、解析度與鏡頭切換共用互斥鎖，衝突回 HTTP 409；裝置列舉失敗回 HTTP 503。

### 舊版／其他來源的編號切換

以下保留非 Windows 或注入式來源的既有契約；Windows 實體攝影機以上方裝置身分契約為準。

背景：這台機器上有多個攝影機裝置（例如編號 0 是筆電內建、朝向使用者臉部的前置攝影機；編號 1
才是實際朝向桌面 Arduino 板子的外接/俯視攝影機）。Windows 上 OpenCV 無法可靠取得裝置的人類可讀
名稱，唯一能分辨的方式是實際抓一張畫面來看。這兩個端點讓使用者在 app 內直接試看、切換，不需要
手動設定環境變數再重啟整個後端服務。

只有 `config.camera.source == "device"` 時才有意義（沿用 `GET /api/config` 的
`camera_source` 欄位所代表的同一個狀態，未另外新增旗標）；`source == "synthetic"` 時：
- `GET /api/cameras` 回傳 `{ "cameras": [] }`。
- `POST /api/cameras/select` 回傳 `ok:false, error:"not_applicable"`。

### `GET /api/cameras`

探測裝置編號 `0..config.camera.max_probe_index`（預設 4；目前使用中的編號若超出此範圍，仍會
額外納入，確保永遠看得到目前這一台）。**目前使用中的編號不會被重複開啟第二個 `cv2.VideoCapture`**
——在 Windows 上，對一個已被本程式佔用的攝影機編號再開一次會衝突/失敗（開發過程中已實測驗證）；
該編號的縮圖改為直接取用執行中 `CaptureService` 已在讀取的 `FrameBus` 最新畫面。其他編號才會短暫
開啟、讀一張畫面、立即釋放，產生縮圖（縮小至約 160×90、JPEG、base64）；開啟或讀取失敗的編號回報
為不可用（不含縮圖）。每個「其他編號」的探測都有逾時（預設 1.5 秒），避免某個編號存在但驅動卡住時
整個端點被卡死。

一律 HTTP 200：

```jsonc
{ "cameras": [
    { "index": 0, "available": true, "is_current": false, "width": 1280, "height": 720, "thumbnail_b64": "<jpeg base64>" },
    { "index": 1, "available": true, "is_current": true,  "width": 1280, "height": 720, "thumbnail_b64": "<jpeg base64>" },
    { "index": 2, "available": false, "is_current": false }
] }
```
An unavailable device that opened but returned an all-black frame may include
the additive diagnostic field `signal_status: "black"`; it is not considered
usable by the picker or the capture switch path.

### `POST /api/cameras/select`

```json
{ "index": 1 }
```

實際嘗試切換到該編號（開啟裝置、套用跟啟動時相同的 width/height/fps/MJPG/自動對焦關閉設定、
讀一張畫面確認可用）——這個嘗試本身就是可用性檢查，不會另外重複開一次來「先驗證」。切換一旦成功，
立即對所有下游生效（MJPEG `/video`、`WS /ws/detections`、`WireTraceWorker` 都只是持續讀同一個
`FrameBus`，不需要重啟任何 worker）。

成功：
```json
{ "ok": true, "index": 1, "width": 1280, "height": 720 }
```

預期失敗（一律 HTTP 200）：
```json
{ "ok": false, "error_code": "open_failed", "params": {},
  "error": "open_failed" }
```
`error_code` 為以下之一；`error` 是相容別名，UI 只使用 `error_code + params`：
- `invalid_index` — `index` 超出 `0..max_probe_index` 範圍。
- `open_failed` — 該編號無法開啟，或開啟後讀不到畫面；此時**原本的攝影機完全不受影響**，
  持續正常供應畫面（切換失敗會 rollback，不會讓 app 沒有攝影機可用）。
- `same_as_current` — 指定的編號就是目前使用中的編號。
- `not_applicable` — 目前是 `synthetic` 模式，沒有實體攝影機可切換。

只有請求本身格式錯誤（例如 `index` 缺失或不是整數）才使用真正的 HTTP 錯誤碼（422）。

## 8. `POST /api/guidance/step`、`GET /api/guidance/state`、`DELETE /api/guidance/step` — 導引式打勾（M22）

沿用 §6/§7 的慣例：預期中的結果一律 `200` + `ok:true/false`，真 HTTP 錯誤碼只留給格式錯誤的請求。

### `POST /api/guidance/step`

啟用（或替換）當前導引步驟，同時對 `WireTraceState` 目前的已占用腳位拍快照存成
`baseline_pin_ids`（「這一步驟新冒出的端點」的比對基準）。

```jsonc
// 請求
{ "expected_pin_id": "D7",            // 必填；必須存在於 board profile
  "expected_role": "TRIG",            // 選填，純顯示
  "component_id": "hc-sr04",          // 選填，串接 ComponentSpec
  "hint_color": "yellow",             // 選填，教學文案建議色，絕不參與比對
  "step_id": "plan-x-step-3",         // 選填；未給則自動產生
  "advance_mode": "confirm" }         // "confirm"（預設 L2）| "auto"（L3）

// 成功
{ "ok": true, "step_id": "step-1-d7", "advance_mode": "confirm",
  "baseline_pin_ids": ["5V"] }

// 腳位不存在（預期中的失敗，200）
{ "ok": false, "error_code": "unknown_pin",
  "params": {"pin_id":"D99","board_id":"arduino-uno-q"},
  "error": "unknown_pin" }
```

`advance_mode:"auto"` 只有在 profile 通過 physical accuracy gate 時才接受；
否則回 `200 {"ok":false,"error_code":"physical_gate_unready","params":{"warnings":[...]}}`，
且不會啟用 step。這個 gate 只證明尺度、相機校正品質與特徵快取可用，仍不等同
於已完成標註資料集的真實準確率驗收。

### `GET /api/guidance/state`

同步、便宜（讀最新快照）。權威讀取路徑——WS `guidance_check`（§2）是推播便利，
在慢連線上可能被其他訊息覆蓋，此端點永遠可靠。

```jsonc
{ "active": true,
  "step":   { "step_id": "step-1-d7", "expected_pin_id": "D7", "expected_role": null,
              "component_id": null, "hint_color": null, "advance_mode": "confirm" },
  "result": { "step_id": "step-1-d7", "expected_pin_id": "D7", "status": "correct",
              "actual_pin_id": null, "confidence": 0.83, "as_of_ms": 1721990000123.5,
              "ai_hint": null } }    // 尚無評估結果時 result 為 null
// 無作用中步驟：{ "active": false, "step": null, "result": null }
```

### `DELETE /api/guidance/step`

停用導引（清除步驟、基準快照與最新判定）。恆回 `{ "ok": true }`。

## 9. `GET/POST /api/camera/focus`、`POST /api/camera/focus/sweep` — 即時對焦控制與輔助對焦

沿用 §6–§8 的慣例：預期中的結果一律 `200` + `ok:true/false`。三個端點都只在
`config.camera.source == "device"` 時有意義（其他 source 回
`ok:false, error:"not_a_device_camera"`）。

**為什麼需要這組端點**：`config.camera.focus` 只在冷啟動時套用，所以調整對焦
原本得「改檔案 → 重啟 → 看 → 再猜一個數字」。而手動對焦值是一個沒有人類意義
的驅動程式數字——不量測的話無法知道 10 是對的、50 是廢的。

### `GET /api/camera/focus`

```jsonc
{ "ok": true,
  "manual": true,              // 是否為手動對焦模式
  "configured_focus": 10.0,    // 本程式設定的值（重連後會自動重套）
  "read_back": 10.0,           // 驅動程式回報的實際值
  "autofocus_raw": 2.0,        // 驅動程式的 autofocus 原始值（C920 關閉後回報 2）
  "camera_open": true }
```

### `POST /api/camera/focus`

```jsonc
// 手動指定（C920 實測範圍 0–250，步進 5）
{ "value": 10 }
// 或交還自動對焦
{ "auto": true }

// 回應
{ "ok": true, "accepted": true, "read_back": 10.0, "mode": "manual", "requested": 10.0 }
```
`accepted` 是驅動程式對 `set()` 的回答（`false` = 驅動拒絕，誠實回報而非假裝成功）。
**設定值會存在 source 上**，所以 USB 暫時斷線重連後對焦鎖不會靜默消失——
`config.camera.focus` 只管冷啟動，這一點對精度 session 很重要。

### `POST /api/camera/focus/sweep` — 輔助對焦（掃描找峰值）

逐步改變對焦值、對**真實影格**取樣、用 Laplacian variance 評分，回傳整條曲線
與峰值，並預設把相機留在峰值。

```jsonc
// 請求（預設 0→60 步進 5，涵蓋 C920 實測峰值區間並留出兩側落差）
{ "start": 0, "end": 60, "step": 5, "apply_best": true }

// 回應
{ "ok": true,
  "best_focus": 10.0, "best_sharpness": 1067.6,
  "peak_at_edge": false,        // true = 峰值落在掃描範圍邊緣，真正的最佳值可能在範圍外
  "applied_focus": 10.0,        // apply_best:false 時為 null 且還原原設定
  "roi": ["board"],             // 評分區域：追蹤到板子用板子範圍，否則 "centre"
  "curve": [ {"focus":0,"sharpness":303.0,"samples":5}, … ],
  "persist_focus_value": 10.0,
  "metric": "laplacian_variance_within_sweep_only" }
```

語意與刻意的設計：
- **回傳整條曲線，不只贏家**：人看形狀就能分辨「真的有峰」與「平坦/雜訊」，
  單一數字會把這個資訊藏起來。實測 C920：focus 10 得 1067.6、focus 60 只有
  63.8（17 倍落差），峰形明確。
- **`peak_at_edge`**：峰值落在掃描邊緣時如實標示——那可能不是真正的最佳值，
  而不是靜靜把端點當成最佳解回傳。
- **評分區域優先用追蹤到的板子**：對著沒有特徵的桌面對焦沒有意義，桌面的
  variance 只會用雜訊淹掉訊號。板子未鎖定時退回畫面中央三分之一。
- **每步取最大值而非平均**：單一張動態模糊或 rolling-shutter 的影格不該懲罰
  一個其實很銳利的對焦位置。
- **度量的誠實限制**：Laplacian variance 是 per-pixel 二階導數，**跨解析度或
  跨 ROI 都不可比**（本專案曾因此誤判「720p 比 1080p 清晰」，見
  `docs/accuracy-improvement-plan.md` §1.2）。同一次掃描內有效（解析度與 ROI
  固定、只有對焦在變）；**絕不可拿不同次掃描的分數互比**。
- 掃描期間相機持續串流（不佔用 source 鎖跑完整段），成本約 24 秒（13 步）。
