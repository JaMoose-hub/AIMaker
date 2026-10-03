# 即時畫面內的來源控制 — 2026-10-03

## 本次調整

- 主工具列只保留即時畫面、接線圖、接線照片；來源選單移到既有 VideoView 右上角，使用相機／手機圖示的半透明膠囊。
- 等待影像、切換、連線失敗和重連操作集中在影像內。接線階段右側 AI 區不再重複顯示一般來源警告；拍照仍受原本 readiness 限制，停用時保留可存取的原因。Eye 恢復提醒、其他除錯頁警告不變。
- 選單 portal host 隨既有 video shell 保留，切到圖／照片只隱藏，不另開手機 viewer，也不修改 FrameBus、YOLO、拍照 API 或配對機制。
- 本次未新增前一題討論的 GPIO 照片擷取按鈕。

## 驗證

- 23 個獨立自動案例通過：來源檢視 4、影像內控制 5、共用手機來源 3、相機工具 9、右側提示／Eye 2。
- 共執行 36 次案例（含重跑，低於 100）；第一次 8 個失敗是測試 fixture 未替換單引號 import，修正後均通過。沒有跑完整套件。
- TypeScript 檢查及 2 次 production build 通過；仍有既有 bundle 大小警告。
- agent-browser 使用不接硬體／雲端的 `gpio-photo-preview.mjs`。正常 Webcam、手機、斷線、重連、接線圖／照片往返、深淺色與 1413×871、1000×700、760×600 版面均檢查。
- 斷線畫面只有一組提示＋重連按鈕，右側無重複警告；按鈕命中測試可點。模擬換 generation 重連後顯示 frame 643；原有來源 POST 為 2 次，圖／照片往返後仍為 2 次；額外手機 viewer 建立次數 0。
- 瀏覽器 errors=[]，沒有框架錯誤頁或橫向溢出。修正視覺檢查發現的全域 select 主題覆蓋，以及斷流時無 detection 被誤判為服務離線的提示優先序。
- 已確認 8100 回傳當前 dist 的入口；未重啟後端、未重新配對或操控真手機，未執行 Pi／GPIO／TFT 測試。

截圖：`live-camera-controls-initial.png`、`live-camera-controls-offline.png`、`live-camera-controls-light.png`、`live-camera-controls-narrow.png`。
