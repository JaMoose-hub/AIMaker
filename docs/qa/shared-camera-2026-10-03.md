# 共用 Webcam／手機來源驗證 — 2026-10-03

## 範圍

只替換 FrameSource；桌面共用 FrameBus、YOLO workers、MotionOverlayWorker、VideoView、GPIO 與拍照證據路徑。保留另一工作對話新增的三檢視工具列與來源選單，未覆蓋 Pi 連線選單等既有改動。

## 自動驗證

本輪自動測試共執行 80 次（含針對性重跑），全部通過；未跑完整大套件。另有 4 次 TypeScript／production build，皆成功，保留既有大 bundle 警告。

- `test_mobile_recognition.py` + `test_camera_modes.py`：23。
- `test_phone_live_source.py` 初版 7 項 + `test_mobile_rtc.py`：33。
- `test_debug_capture.py` 新鮮影像、來源拒絕／切換、TFT 取樣限制相關：8。
- 新來源 API loopback／世代／相機鎖 2 項，及 shared preview、原手機定位重跑 2 項：4。
- `phone_live_source.test.mjs` + `camera_tools.test.mjs`：12。

新測試涵蓋 latest-only adapter、過期／外來／旋轉影格拒絕、既有 worker／模型保留、來源回復、同張影格顯示、手機來源拍照 metadata、3 Hz 狀態回饋不阻塞全速串流。素材與模型均為測試替身；RTC 套件包含本機合成影像 peer 測試，不使用真手機或相機。

## 瀏覽器驗證

使用隔離 `gpio-photo-preview.mjs?tracking=1&lang=zh-TW`，沒有代理至真後端，沒有 Pi 或付費 AI 操作。

- 主畫面有三檢視與單一來源選單。
- 選手機後，同一 VideoView 顯示同步 frame ID、Pi／模組 GPIO；手機主 viewer 建立次數為 0。
- 設定中的同一「即時追蹤」開關可開關；關閉時回既有 `/video` 流程。
- 手機 → 接線圖 → 即時 → 接線照片 → 即時，仍是手機，來源 POST 只有第一次 1 次。
- 斷流清除影像／舊框，拍照停用。重連新 generation 後恢復同步畫面；最後觀察 frame 674、hidden=false、errors=[]。
- 切回 Webcam 恢復既有鏡像設定與追蹤影格，errors=[]，不另開手機 viewer。
- 檢查過程修正 `.video-hint` 的 pointer-events 繼承問題，讓重新連線按鈕可按；測試 fixture 也補上 generation 不符時拒絕旧串流的行為。
- 已保存 `shared-camera-initial.png`、`shared-camera-phone.png`、`shared-camera-final.png`；已關閉本輪瀏覽器與隔離伺服器。

## 不宣稱的驗證

未執行真手機全流程、1920×1080 實測 FPS、移動／遮擋場景準確度、Pi 部署或感測器／TFT 功能測試。手機端既有橫放發布流程沒有改成旋轉／拉伸直立影像。

## 套用

重啟前確認 Pi 無 PID、version、invocation、執行佇列或測試／trial，AI 無執行中的拍照／模型工作。沿用原 supervisor 與環境重啟 PID 85376；新服務 PID 62972。`/api/config` 與 `/api/camera/live-source` 回覆正常，Webcam ready=true、realtime_tracking=true。手機須重新配對，未替使用者啟動真手機測試。
