# 手機串流與桌面拍照倒數 — 2026-10-04

使用者確認手機本地預覽順，但筆電卡，尤其電腦 AI 除錯／三張照片引導的 10 秒倒數期間。

## 實測

- 8100 與 8443 均正常在線；目前 supervisor attempt 0 未再退出。不是再次發生整個後端離線。
- 16:45:15–16:45:45，手機工作階段的 generation 2 與 context 不變；接收序號 5214→5223，29.736 秒收到 9 張，約 0.303 FPS。
- 同段手機 media-source 診斷大多約 30 FPS，但 7/11 次 publisher send FPS 為 0；6/11 次接收逾時。RTT 一度達 281 ms，不能用其他低 RTT 樣本排除丟包。
- 這段沒有 WebRTC viewer transport，故沒有筆電 H.264 viewer 重編碼。主畫面追蹤另一次處理時間 7.84 ms，不能將本次嚴重停頓單獨歸因於模型／GPIO 處理。
- 實際模型狀態顯示 Pi 5、HC、TFT 使用 CUDA，沒有 fallback reason；這不是逐 operator GPU audit。
- 原始僅診斷數據：backend/runs/mobile-stream-quality/20261004-countdown-readonly.json；未另保存影像或呼叫 AI。

## 倒數／照片入口

createCaptureCountdown 歸零前不呼叫拍照 action 或後端 API。AI 三張照片入口讀取 FrameBus 影格、品質與 JPEG，沒有停止手機串流或持有 MobileService 鎖。另一个 GPIO 照片 PoC 入口暫停 workers 的行為不能套用到這次入口。

目前已定位為手機發布／上行／接收階段的停頓，尚未確認具體為 Safari 編碼、自適應頻寬或封包遺失。倒數與卡頓同時發生，不足以證明倒數 timer 是原因。

## 已修正的獨立恢復缺口

BrowserPublisher 成功完成協商時回傳實際 generation，useMobileBrowser 當下記錄本次 publisher 的 owner、session、context 與開始時間。原先需完整刷新 session、聊天和照片核對成功後才記錄；其中一項刷新失敗，已啟動的串流就失去自動恢復資格。

不修改解析度、bitrate、模型、倒數、Webcam 或既有單次自動重試策略。此修正不是已證實的傳輸停頓根治。

## 驗證與交付

63 項 browser／countdown 測試通過，涵蓋刷新失敗、失敗協商、過期 generation、明確停止，以及倒數前不發出 API。TypeScript 與 Vite production build 通過。前端靜態檔更新，未重啟後端或撤銷手機配對。

新版自動恢復尚未在實際 iPhone 上完成重載與故障恢復驗證。後續若要區分 Safari encoder 與網路，需補上 publisher encoder、NACK／PLI 與接收端 RTP loss／jitter 診斷；不能把前端測試當作已恢復穩定 30 FPS。
