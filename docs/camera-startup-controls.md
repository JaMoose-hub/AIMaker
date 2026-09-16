# C920 重啟時的設定一致性

## 已觀察的問題

2026-09-13 13:06，重啟前讀回增益 0、飽和度 128、銳利度 128；重啟後曝光仍為 -5/manual，但這三項變成 91、119、255。相機照片也同時出現變亮、雜訊、高光裁切。不能只看曝光不變就宣稱設定維持。

舊 FFmpeg 啟動流程先開一個 OpenCV 720p 串流設定屬性，關閉後再開正式 FFmpeg 1080p 串流。只在第一個 handle 呼叫 `set()`，不能保證第二個 handle 開啟後的硬體狀態。

## 現行可選路徑

- `camera.native_uvc_controls: true`：Windows FFmpeg 使用 `windows_uvc.py/.ps1`，直接操作指定裝置的 DirectShow 屬性，不另開 OpenCV 擷取串流。
- `camera.uvc_image_controls`：只保存已量測／使用者要求的亮度、對比、飽和度、銳利度、背光設定；增益、曝光、焦距沿用原本欄位。
- 啟動前套用一次；正式串流收到首張非黑畫面後再套用一次並丟棄套用前的首張影像。後續每次重開串流都執行，非逐幀處理。
- 同名裝置不唯一、屬性不支援、模式／數值不在範圍時，不假裝成功。整批先驗證範圍再寫入，最後讀回整批值；失敗不封鎖 demo，但記錄 warning 與 `focus_state().uvc_controls.verified=false`。
- 自動白平衡未被切成手動；不改相機解析度、FPS、模型、電子零件或接線流程。
- 非此可選路徑仍保留既有 OpenCV 設定方式。

接口依 [Microsoft IAMVideoProcAmp::Set](https://learn.microsoft.com/en-us/windows/win32/api/strmif/nf-strmif-iamvideoprocamp-set) 與 [Configure the Video Quality](https://learn.microsoft.com/en-us/windows/win32/directshow/configure-the-video-quality)。manual=2、auto=1；自動模式只核對模式，不能要求動態值永遠相同。

## 驗證方式

1. 用 `tools/read_windows_uvc_controls.ps1` 在重啟前後各讀一次硬體值，保存獨立 JSON。這個診斷工具仍然只讀。
2. 配對同場景照片與四件定位結果，避免「設定值一致」被誤当成「辨識／逐 Pin 精度通過」。
3. 全套回歸包含：不能開第二串流、首張黑畫面不能跳過恢復、每次串流重開重新套用、錯誤不回報成功、子程序有時限／隱藏視窗／literal argv。

單次重啟成功不等於第九階段的十次重啟、拔插鏡頭及長時間運行全部驗收。實際結果依每日工作單。
