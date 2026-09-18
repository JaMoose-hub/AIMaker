# Board Vision — AI Maker 與視覺化接線引導

鏡頭即時辨識 Raspberry Pi 5、HC-SR04 與 MRD-TF240，顯示板框、GPIO／Pin、
接線步驟，並整合 Codex 作品設計、雲端照片檢查與 Pi 部署。
保留原有板卡 Profile 與開發工具，支援繁體中文／English。

作品接線預設為 **HC-SR04+ 寬電壓版、3.3V 供電**（Pi 實體 Pin 1），不再使用 ECHO 分壓電阻。
僅適用於確認可輸出 3.3V ECHO 的版本，不適用標準 5V HC-SR04；視覺模型不變。
接線對照與舊作品備份方式見 [3.3V 版本說明](docs/hcsr04-plus-3v3.md)。

## 從 GitHub 下載後首次啟動

需要 Python 3.12、uv、Node.js 22+ 與 npm。以下為 Windows PowerShell，
預設使用一般 webcam 與 CPU 推論；不會附帶原作者的相機設定、登入狀態或密碼。

```powershell
git clone https://github.com/JaMoose-hub/AIMaker.git
cd AIMaker
Copy-Item backend/config.example.yaml backend/config.yaml
cd frontend
npm ci
npm run build
cd ../backend
uv sync --no-default-groups --group dev
uv run --no-default-groups --group dev uvicorn app.main:app --host 127.0.0.1 --port 8100
```

開啟 <http://127.0.0.1:8100/>。請依相機調整 `backend/config.yaml` 的
`camera.device_index`；這份本機設定已由 `.gitignore` 排除。
**已有本機設定時不要重新複製範例覆蓋它。** NVIDIA CUDA 安裝與設定見
[CUDA 推論](docs/cuda-inference.md)。

Pi 5 的兩個模型、HC-SR04 與 MRD-TF240 模型共約 **43.5 MiB**，已隨 repository
提供，不需要下載訓練資料或使用 Git LFS；詳見 [模型清單](models/README.md)。
Codex 功能需在自己的電腦安裝 Codex CLI 並登入自己的 ChatGPT 帳號；bridge 不附金鑰。
Pi 部署也必須設定自己的主機與帳密。上傳範圍與敏感資料檢查見
[Repository 發布說明](docs/repository-publishing.md)。

## 快速開始

2026-09-16：目前作品與即時辨識使用 **Pi 5＋HC-SR04＋TFT**，HW-123 已退出零件選單、接線、部署與模型載入。
舊作品會在頁面啟動時先備份再轉換，保留剩餘接線紀錄。歷史模型／訓練資料僅供離線回放，不再載入；詳見 [HW-123 移除紀錄](docs/hw123-retirement.md)。

**R1＋Eye 智慧眼鏡**已整合至「智慧眼鏡」：彩色串流、解析度／FPS／降噪三項控制，
共用接線引導目前的 YOLO 模型，直接投影藍色板框、GPIO／Pin 與步驟高亮；退出恢復原相機。
預設 1080p30＋標準降噪，使用方法、API 與目前驗證結果見 [智慧眼鏡 MVP](docs/smart-glasses-eye.md)。

Pi 5＋HC-SR04＋TFT 已加入可切換的 [即時追蹤試版](docs/realtime-tracking.md)：
獨立快速追蹤＋同幀影像／Pin 標記；不改動原本接線與電氣驗證。

接線遮擋時，Pi 可用既有實拍參考圖的特徵匹配恢復有方向的板面座標，
再沿用原本的藍色板框及 GPIO／Pin 投影。模型框只限定搜尋範圍，不直接生成腳位；
已撤掉額外的綠色本體框。固定接線擺位的實測與限制見[9/13 工作單](docs/exhibition-session-2026-09-13.md)。

Pi 5 現在提供 **AI 作品工作台：生成作品組裝圖片 → Blueprint → 原有鏡頭 Pin 引導 → 部署與測試**。Blueprint 專注接線圖、材料導購與製作步驟；作品接線引導使用全寬鏡頭，不放對話側欄，保留「AI 檢查本步」。需要 AI 修改時返回設計頁；設計與部署階段保留雲端對話。電子模組固定；可加入輪子、銅柱、壓克力板等被動配件，圖片與改圖沿用 Codex 管理的 ChatGPT 登入。
使用方式、Codex 登入、支援邊界與驗收紀錄見 [AI Maker 工作台](docs/ai-maker.md)。
作品接線引導新增「AI 檢查本步」：本機只定位與裁切相機照片，由所選雲端模型判讀外觀，不自動確認接線或部署。詳見 [雲端接線照片檢查](docs/cloud-wiring-check.md)。

```powershell
# Demo 模式（build 前端 → 起後端 → 開 Edge 無邊框視窗）
.\scripts\demo.ps1

# 實體 UVC 相機 + 真實 CV pipeline（預設使用目前的 1920x1080 相機 index 1）
.\scripts\camera.ps1

# YOLO Pose + 板卡 Profile 幾何定位（模型缺少時自動退回原 pipeline）
.\scripts\camera-yolo.ps1

# 指定其他相機索引
.\scripts\camera.ps1 -DeviceIndex 0

# 開發模式（後端 hot-reload + Vite dev server）
.\scripts\dev.ps1
```

原開發環境的本機 `backend/config.yaml` 使用 **C920 實體相機 + Raspberry Pi 5 hybrid 辨識**
（1920×1080、FFmpeg MJPEG），並同時啟用兩個零件模型：
**HC-SR04、MRD-TF240-8P-CS**。一般 `demo.ps1`、`dev.ps1`、
`camera.ps1` 與直接啟動後端都會讀取這份設定，不必另外帶零件啟用參數。
`camera-yolo.ps1` 保留各模型的啟動覆寫選項；光敏電阻不在預設清單內。

原開發環境的三個主辨識模型使用 **ONNX Runtime CUDA / RTX 4070（device 0）**；
縮放、補邊與輸入格式轉換也透過 CuPy CUDA＋GPU I/O binding 執行。
LK／ORB 與幾何計算仍使用 CPU，排針靜止檢查改為局部 ROI，OpenCV 池預設 2 條執行緒。
相機重啟會依已保存的 UVC 設定套用並讀回；C920 的原生屬性路徑不另開 OpenCV 影像串流，詳見[相機啟動設定](docs/camera-startup-controls.md)。
CUDA 無法使用時會明確回退；僅前處理失敗時保留 CUDA 模型。
`GET /api/inference/status` 可分開查模型、前處理的實際後端與回退原因；
安裝、切換方式與量測限制見 [CUDA 推論](docs/cuda-inference.md)。

需要無硬體的合成展示時，在啟動終端明確設定
`BOARDVISION_CAMERA__SOURCE=synthetic`、`BOARDVISION_DETECTOR=mock`、
`BOARDVISION_COMPONENT_VISION__ENABLED=false`；一般辨識請勿使用這組測試覆寫。
可透過 `GET /api/config` 確認 `component_vision.enabled` 為 `true`，
且 `component_vision.components` 包含上述兩個 ID。切換模式：

| 情境 | 設定 |
|---|---|
| 合成畫面 + 真實 CV 管線（自我驗證） | `detector: pipeline` |
| 真實 webcam + 真實 CV 管線（正式） | `camera.source: device`, `detector: pipeline` |
| YOLO 四點 + Profile 幾何，特徵管線 fallback | `camera.source: device`, `detector: hybrid` |
| 環境變數覆寫（不改檔） | `BOARDVISION_DETECTOR=pipeline`, `BOARDVISION_CAMERA__DEVICE_INDEX=1` |

正式相機路徑預設要求低延遲 UVC buffer（`camera.buffer_size: 1`）；這是
DirectShow 的 best-effort 設定，驅動不支援時會繼續運作但不會假裝已降低延遲。
真實驗證前請執行：

```powershell
cd backend
.venv\Scripts\python.exe ..\tools\profile_preflight.py --strict
```

若影像尺度不足，wire pipeline 會清空端點候選並在 UI 顯示 uncertain，避免低解析度
畫面被誤當成接線成功。

## 真實板子上線步驟（一次性）

目前 checked-in 的 `profiles/boards/arduino-uno-q/` 已含一張可重現的真實
1280x720 參考影像，但目前約 4 px/mm，仍低於實體準確度 gate。要對真實板子
跑 pipeline 並達到實體驗證尺度：

1. 用固定式 UVC 相機拍一張 UNO Q 的**垂直俯拍**照，目標為 1920x1080、腳距
   約 20--25px（8--10 px/mm），光線均勻、對焦清楚、LED matrix 熄滅、霧面中灰背景。
   相機要固定在支架上，並確認串流實際 delivered resolution，不只看設定值。
2. 執行校正（依提示依序點擊 4 個安裝孔：左上→右上→右下→左下）：
   ```powershell
   cd backend
   .venv\Scripts\python.exe ..\tools\calibrate_reference.py `
     --photo ..\profiles\boards\arduino-uno-q\reference_photo.jpg
   ```
   工具會更新 `board.json` 的 reference 區塊、快取特徵、輸出 `calibration_overlay.png` 供目視驗收（32 腳應全部套準）
3. 先執行 `..\tools\profile_preflight.py --strict`；通過尺度與相機標定 gate
   後，再把 `config.yaml` 改為 `camera.source: device` + `detector: pipeline`，重啟後端

（可選）鏡頭內參校正提升斜角精度：`tools/calibrate_camera.py`（ChArUco 板）。

## Pi 5 範例程式與一鍵部署

選擇 Raspberry Pi 5 後，右側會顯示「Pi 部署」面板：

1. 編輯內建光敏 Python 範例；草稿會自動保存在目前瀏覽器。
2. 按「連線 Pi」。目標預設為 `pet@192.168.50.174`，帳密由後端設定提供。
3. 按「部署並執行」，在下方查看每秒更新的輸出與獨立的程式執行狀態。

範例腳位來自既有光敏接線 Profile：VCC → 3.3V / Pin 1、GND → Pin 6、
AO → GPIO17 / Pin 11。每 200ms 讀取 HIGH/LOW；這不是 ADC 或光照強度量測。
部署不依賴相機辨識或接線勾選。看到 GPIO 值只證明程式讀取了 GPIO，
實際光敏反應仍需接好電路後遮光／放開驗證。

首次部署在 Pi 建立 `/home/pet/Desktop/Pi_deployer`，包含 `main.py`、
`run.log`、`.venv`（`--system-site-packages`，沿用 Pi 的 gpiozero/lgpio）。
程式經 SFTP 傳送，以 Pi 的 Python 檢查語法，然後替換專用的
`boardvision-pi.service` 使用者服務。語法／環境檢查失敗不停止舊程式。
新程式的 runtime exception 與輸出都會出現在面板；重新部署只保留一個執行實例。

SSH 或筆電關閉後程式仍執行；服務不設開機啟動，也不自動重啟崩潰程式。
Pi 重開機後再按部署。需要從 SSH 停止時，執行
`systemctl --user stop boardvision-pi.service`。

連線設定位於 `backend/config.yaml` 的 `pi_deploy`；也可使用
`BOARDVISION_PI_DEPLOY__HOST`、`BOARDVISION_PI_DEPLOY__USERNAME`、
`BOARDVISION_PI_DEPLOY__PASSWORD` 覆寫。更新後端依賴需先在 `backend` 執行 `uv sync`。
第一版支援單台 Pi、單檔 Python，沒有額外套件安裝 UI。

API：`POST /api/pi/connect`、`POST /api/pi/deploy`（JSON `code`）、
`GET /api/pi/status`。部署在背景執行，status 回傳部署階段、程式狀態、PID、
退出碼與最近最多 1,000 行／128 KiB 輸出；帳密不包含在回應中。

## 測試

```powershell
cd backend
.venv\Scripts\python.exe -m pytest tests -q        # backend regression suite
cd ..\frontend
npm run build                                       # TS 嚴格模式檢查 + 打包
```

視覺管線驗收（合成場景已知真值）：鎖定 <10 幀、腳位誤差中位數 ≤5px@720p、
180° 方向辨識、遮擋 60% 進入 STALE 不閃爍、靜置抖動 <1px。

## 架構

```
相機(裝置/合成) → FrameBus(單槽最新幀) ┬→ MJPEG /video ──────────→ <img>
                                      └→ VisionWorker → BoardDetector
                                          (mock | pipeline | hybrid)│
   pipeline: ROI閘門 → ORB特徵比對參考圖 → RANSAC → solvePnP(IPPE)   │
             → LK光流追蹤 → One-Euro姿態濾波 → 狀態機 → 投影32腳     ▼
                                      WS /ws/detections (座標JSON, ≤30Hz)
                                                                    │
   React SPA: <img>底層 + SVG overlay疊加 ←──letterbox轉換──────────┘
              CapabilityCard · FilterBar · QueryBox · StatusBar (zh-TW/en)
```

- 關鍵設計：**6-DoF 姿態 + 3D 腳位地圖（z=8.5mm 排針座高）**，不是 2D 投影 —
  相機傾斜時腳位標記才不會偏移到隔壁腳（詳見 `docs/api-contract.md` §5 與計畫文件）
- 腳位資料庫 `profiles/boards/arduino-uno-q/board.json`：由 `tools/gen_pin_table.py`
  生成（幾何座標取自官方 UNO R3 Eagle 板檔，能力對照官方 UNO Q 文件），
  新增板卡 = 新增 profile 資料夾，程式碼零修改
- 前後端契約見 `docs/api-contract.md`；CV 模組介面見 `backend/app/vision/interface.py`
- VLM prototype：`POST /api/vlm/validate` 驗證外部模型 JSON，`POST /api/vlm/ask` 可選擇
  呼叫 Ollama OpenAI-compatible endpoint；輸出同時通過 Pydantic 與
  `schemas/scene-understanding.schema.json`，authority 固定為 `advisory_only`，不會改寫
  GPIO snapping、guidance 或 Rule Engine 結果
- YOLO/Profile hybrid：`detector: hybrid` 使用 OpenCV DNN 載入
  `models/board-pose.onnx`，四個語意角點解出 6-DoF 後由 `board.json` 投影全部 GPIO；
  模型缺失或定位不可信時回退現有 ORB/SIFT pipeline。資料收集與訓練見
  `docs/yolo-board-pose.md`
- 未來接縫：WS 訊息帶 `type` 欄位（`wiring_check`/`telemetry` 可直接擴充）、
  QueryService 預留 LLM adapter、`DetectionResult` 帶 6-DoF 姿態供接線驗證使用

## 目錄

MRD_TFT240_8P_CS（ILI9341）接線、Pi 套件與首次亮屏驗收：見 [TFT 指南](docs/mrd-tft240-ili9341.md)。
軟體支援 RGB 測試圖與距離顯示；3.3V 模組相容性及 BLK 留空時的背光狀態仍須核對／實测，不能由照片或程式測試推定通過。

```
backend/    FastAPI + CV（Python 3.11+, uv, .venv 已含相依）
frontend/   Vite + React 18 + TypeScript（strict）
profiles/   板卡資料庫（board.json + 參考圖 + 特徵快取）
schemas/    board profile JSON Schema
tools/      pin 表生成、參考圖渲染、實照校正工具
scripts/    dev.ps1 / demo.ps1
docs/       api-contract.md
```
