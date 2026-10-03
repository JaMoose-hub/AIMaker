# 手機橫直向串流與免鎖定除錯拍照 QA — 2026-10-03

## 行為

- 1080p／720p 依手機方向請求長短邊。直接傳送原相機 track，支援橫、直及方形實際輸出，不旋轉、裁切或放大。
- 方向或原生像素尺寸改變：撤銷舊 Locked，關閉舊 RTC／相機與伺服器串流後，才重新開啟新的 generation。停止、背景及作品切換取消重連。
- 「拍照問 AI／除錯」只要求本地播放中的有效影格，不依賴 YOLO 或 Locked。完整影格 JPEG 95 加入原聊天草稿，使用者補充問題後送出；不建立 GPIO capture ticket。
- 「GPIO 引導拍照」保留原 Locked、新鮮度及正式照片分析。一般除錯附件不冒充已確認 GPIO 定位。
- 筆電已選手機來源時，核對新串流 generation 並沿用現有相機切源交易；成功後才記錄來源。失敗最多自動重試一次，至少間隔五秒，之後仍可手動重連。Webcam 使用中不因手機訊息切源。
- 晚到的拍照、方向事件或切源結果不能把舊資料加入另一個作品／取景來源。

## 隔離瀏覽器實走

使用真實 `useMobileBrowser` 與 `MobileWebApp`，搭配 loopback fixture 的合成相機、假 API／RTC。測試頁 `/mobile?portrait&unlocked` 始終 `Finding`、`can_capture=false`。**此處沒有使用 iPhone、實體板卡、CUDA 或 Codex。**

1. 以直式啟動：原始與傳送尺寸均為 **1080×1920**；一般拍照可用、GPIO 按鈕停用。
2. 按一般拍照：切到聊天並顯示附件，相機仍為一次開啟／零次停止。
3. 輸入問題後送出：假服務收到一張 JPEG，SOF 實際尺寸 **1080×1920**、150265 bytes。保存 SHA-256 `c498c26c436ecd7ea9a0f308762f99455b46530524c25f7d014361f2876f9003`。沒有正式照片／capture-ticket 請求。
4. 回取景並按 fixture 的方向切換：自動從 generation 1 到 2，**1920×1080**；開相機兩次、停止一次，沒有第二份並存相機。
5. 手動停止後再旋轉：generation 保持 2，開相機次數保持 2，停止次數為 2；兩種拍照停用、舊 FPS 清空。
6. 明確重新啟動直式：generation 3、1080×1920；390×844 版面可操作兩種拍照並保留整張取景。
7. 結束後停止合成相機、關閉 fixture 分頁及 loopback 18789 服務，還原瀏覽器 viewport。

證據：[fixture 狀態](mobile-portrait-debug-fixture-2026-10-03.json)；[手機版面](mobile-portrait-debug-2026-10-03.png)。fixture 所顯示的 FPS 是合成資料，不是 iPhone 實測。

## 自動與正式服務驗證

- 後端 RTC、手機辨識及 PhoneFrameSource 相關測試 **55 通過**：直式 YUV/YUVJ buffer／尺寸、generation 取消與舊回覆、FrameBus 序號、工作者重設、模型保留及 Webcam 復原。影像與推論皆為測試替身，不代表 GPIO 實物精度。
- 前端手機、照片、來源切換、Webcam 設定／工具相關測試 **179 通過**；TypeScript／Vite 建置成功，i18n 761 keys 檢查通過。包含切源失敗重試、離開接線頁後旋轉再返回、停止／Webcam／作品切換時忽略舊交易的行為測試。
- HTTPS `/mobile` 與頁面資產皆 200，透過既有 CA 驗證 TLS；下載的 entry JS／CSS 與 `frontend/dist` 相同。
- 更新只建置前端，不重啟後端／gateway。8100 PID 62972、8443 PID 62564 保持單一 listener；原配對、作品與既有聊天仍可讀。
- 正式頁面載入，手機連線顯示已連接；目前手機取景為停止狀態。本次未進行 Webcam 硬體驗證，未修改其相機參數；桌面仍由使用者選擇 Webcam 或手機來源。

## 未完成硬體驗證

本次沒有收到新版 iPhone 直式串流，尚未驗證 Safari 真實旋轉事件／相機像素方向、直式實際 FPS／延遲、照片清晰度、YOLO 準確率或 GPIO 腳位精度。此前橫式串流與長測結果記錄於 [原相機串流 QA](mobile-native-stream-2026-10-03.md)，不當作本次直式實測。

使用者需停止舊取景、重新整理 Safari 的既有 HTTPS 手機入口與筆電頁面，再以直式開啟取景。免 Locked 拍照可直接試「拍照問 AI／除錯」；正式 GPIO 拍照仍須取景 Locked。
