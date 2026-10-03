# 手機原相機串流優化 — 2026-10-03

## 改動

- 手機 `prepareBrowserLandscapeStream` 僅用影片元素確認橫向及實際尺寸，WebRTC 直接接原相機 track。移除逐幀 Canvas 重畫、縮放、`captureStream` 和重複 FPS 節流；不以放大來冒充 1080p。橫向／尺寸變更仍撤銷舊串流，停止只釋放一次原相機。
- 手機預設 1080p／30 FPS 目標、12 Mbps 上限。筆電 H.264 的初始 target 跟隨 3／8／12 Mbps 設定，不再將 12 Mbps 初始限制成 8 Mbps；仍保留 RTCP／REMB 適應。
- 實際影片 receipt、辨識及各段統計分開。新增 `video_received_at`、`video_receive_seq`、`video_receive_age_ms`、`video_receive_fresh`；後端以 monotonic time 判定停幀，1.5 秒撤銷 Locked、清除舊 FPS。診斷統計及手機 heartbeat 不能延長影格壽命。
- 統計回呼失敗記錄後繼續接收，不讓非影像錯誤殺掉 aiortc relay。合成測試重現舊程式缺陷，但尚未證明這就是先前 iPhone 實機停流的根因。關閉／EOF 取消 owned pending recv，晚到影格不能復活。
- 手機在前景、同工作區與本次啟動 generation、無拍照／上傳／其他忙碌時，停收五秒可自動重連一次；未收到首張影格亦使用本次啟動的期限。停止、背景及切作品取消重連，不反覆要求相機或建立競爭連線。
- 各段 FPS 逾期獨立清除；重複或倒退 RTC timestamp 不產生新的 FPS，getStats 失敗清除差分基準。
- 此次保留目前 aiortc 解碼後重新編碼給桌面的路徑，沒有實作 SFU，不能宣稱影片只壓縮一次。

## 軟體驗證

- 前端照片／手機回歸 **133/133** 通過，其中 browser **44** 項包含原 track 直接送、720p 不放大、單一相機所有權、取消／方向／尺寸變化與重複 RTC 統計。
- TypeScript、Vite production build 通過；i18n 761 keys 通過。
- 後端 mobile／RTC／照片／gateway／Assistant 回歸 **162/162**，手機辨識回歸 **14/14**，共 **176** 項通過。合成、假模型及生命週期測試不能當作 iPhone 速度或 GPIO 實物準確率。
- 隔離瀏覽器使用真正手機 hook／UI、瀏覽器原生合成影片來源及假 WebRTC／API；取景→Locked→拍照→照片的 JPEG 上傳尺寸為 **1920×1080**、品質 0.95、phone_frame，相機取得 1 次、停止 0 次、generation 1。照片頁顯示已保存及串流持續。假 GPIO 不屬實物定位證據。

## 部署與原相機

- 更新前四個實機樣本、同 generation 3：15.19 秒接收計數增加 337 張，平均 **22.19 FPS**；手機送出約 23–25 FPS。這是短窗口基準，不是固定場景畫質、五分鐘穩定性或完整延遲量測。證據：`backend/runs/mobile-native-quality/20261003-before-native.json`。
- 最終 production assets 包含 `MobileWebApp-D7SAjtsl.js`、`browser-BIhwrvbM.js`。隱藏監督 PID 58976、後端 PID 85376；HTTPS gateway PID 62564 沿用。8100／8443 各一個 listener，事件檔 `20261003-142438-3758-events.jsonl`。
- 原 config 前後 camera_source=device、video_size=1920×1080、capture_backend=ffmpeg 相同，Webcam `/frame.jpg` HTTP 200。HTTPS 使用原 CA 與 hostname 驗證回 200；未修改憑證、OS／防火牆、Webcam 設定、模型、GPIO 或 Pi。
- 隔離 18789 服務及測試分頁已關閉。
- iPhone 新版實機 generation 1 在 14:27:28–14:27:38 的穩定窗口收到 1920×1080，影格計數 895→1201，約 30 FPS；手機回報約 29.94–30 FPS、RTT 8–9 ms。三個模型回報 actual_backend=cuda、preprocessing_backend=cuda。這是實際接收短窗口，並非五分鐘連續通過或 GPIO 準確率證據。
- 隨後手機影格與 publisher 回報同時停止；後端保持回應，舊 FPS 清零並撤銷 Locked。約 30 秒後串流斷線，尚不能判定為 Safari 離開前景、網路或其他原因。沒有依此猜測原因重啟或改解碼器。
- 手機 generation 2 重新連接後亦收到 1920×1080、30 FPS；使用者選擇繼續五分鐘實測。保存實際筆電手機畫面 `C:/Users/james/AppData/Local/Temp/tinkro-phone-native-stream-optimized.jpg`，能看到 Pi 5 與 HC-SR04；此畫面不能證明每個 GPIO 坐標或細字畫質已達標。長測結果另補，沒有以顯示設定替代實測。

## 實機連續測試

- generation 2 的 14:31:09.857–14:32:05.081 接收計數 12→1333，55.22 秒整段平均 23.92 FPS；包含啟動與兩個低 FPS 樣本，不能拿其中 30 FPS 的窗口聲稱整段達標。最後影格 14:32:03.848、publisher 回報 14:32:02.870；兩者一起停止，後端保持回應，稍後回報 stream_disconnected。
- 程式核對：Safari hidden／pagehide 會停止相機並取消取景意圖，返回前景需手動開啟取景；僅手機內切換聊天／照片／取景不會停止相機。此次沒有 visibility 事件證據，不能把背景行為當作已證實停流原因。
- generation 3 第一個新鮮樣本 14:34:01，獨立記錄五分鐘；gen2 斷線樣本保留，不混入新的平均。檔案：`backend/runs/mobile-native-quality/20261003-generation2-stability.json`。
- 14:35:00 使用既有 `/api/inference/status` 核對共用模型：Pi、HC、TFT actual_backend=cuda、preprocessing_backend=cuda，providers 包含 CUDAExecutionProvider；當手機作為主畫面來源時，stream.model_runtime={}，不將它偽裝成手機狀態本身有模型回報。
- 主畫面檢查為完整 1920×1080 JPEG，沒有以小圖放大冒充；主畫面目前採既有影像與標記同步路徑。手機協作 WebRTC viewer 仍保留第二次 H.264 編碼，因此本次沒有宣稱所有桌面路徑皆零重編碼。
- 第一段五分鐘驗收未通過：gen3 在 14:34:01–14:38:01 的 49/49 抽樣新鮮，240.008 秒實收增加 7094 幀、平均 29.557 FPS（含啟動）、五秒區間中位 30 FPS；14:38:05 後端退出，記錄 -1／0xFFFFFFFF，14:38:08 supervisor attempt 1 重啟。舊手機 session 隨之失效。
- 退出原因未確認：Application/System 記錄未提供相應 fault module／stack；stderr 僅 CuPy CUDA_PATH 警告。程式與 launcher 未發現主動退出、存活期限或殺掉後端的確定路徑。supervisor 紀錄的是 venv launcher 的退出碼，不能只依 -1 歸因原生崩潰或外部終止。未據此修改 CUDA、編碼器、OS 設定或重啟。
- 重啟後實際 Python PID 62972、venv launcher PID 75836；監督 PID 58976 及 gateway PID 62564 保持。持有真正程序 Handle 的唯讀監測 `backend/runs/mobile-native-quality/20261003-process-liveness.jsonl` 記錄原生程序存活及記憶體，沒有改應用程式。
- 手機重新連線為新 session，另做五分鐘觀測 `backend/runs/mobile-native-quality/20261003-post-restart-stability.json`；不把新舊 session 拼接成通過結果。
- 重啟後五分鐘：14:42:38.282–14:47:38.287，61/61 抽樣 API 成功、同 session／generation、新鮮 1920×1080；接收計數 5444→14432，實際增加 8988 幀、平均 **29.96 FPS**，五秒區間 29.2–30.2 FPS、最大接收 age 47 ms。此窗口沒有觀測到停流、重連或後端重啟，五秒抽樣不能證明每個影格均未掉落。三個模型首尾仍回報 CUDA 且推論計數增加。
- 最後停止本次唯讀程序監測器，保留單份後端與 HTTPS 服務及正在取景的手機；沒有恢復／切换使用者已選的手機畫面。原 Webcam 畫質參數保持，沒有改用手機參數覆蓋。
- 本次軟體優化與新五分鐘窗口已驗證，但前一段後端退出仍未有根因，不能宣稱長時間退出問題已解決。原畫質與新版未在完全固定的實物場景做細節 A/B，不能給出定量的清晰度提升或 GPIO 精度結論。
