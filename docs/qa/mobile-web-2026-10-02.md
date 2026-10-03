# Safari 手機 prototype 驗證（2026-10-02）

本次將 iPhone 入口改為 Safari 網頁。原生 Expo 版本保留；手機頁獨立載入，不掛載桌面相機、Pi 連線或作品草稿遷移。

## 已完成軟體驗證

- 後端 149 項相關測試通過：mobile、mobile_api、mobile_web、mobile_https、mobile_rtc、mobile_photo_analyzer、mobile_without_webcam、model_lock、assistant_media、assistant、photo_geometry、photo_reference、photo_wiring。
- 前端 112 項相關測試通過：mobile_browser、mobile_web、mobile、photo_wiring、glasses、display_mode、component_overlay_scope、chat_scroll、realtime_frame。TypeScript／Vite build 與 i18n 檢查通過。
- 本機瀏覽器完成配對、既有聊天歷史載入、IndexedDB 草稿恢復、解析度／bitrate 選擇、離線撤銷配對、桌面重新產生 QR。
- 390 × 844 檢查無水平溢出；開啟取景按鈕在首屏。照片座標、方向、尺寸、線路與來源 ID 的測試通過。
- HEIC 解碼保留完整影像；JPEG EXIF 方向修正；原始上傳 bytes 保留；超過 12MP 只縮小分析副本，分析結果同時附原圖尺寸。
- aiortc 本地 publisher → receiver／sampler → viewer 實際協商測試通過。該測試使用 320 × 240 合成像素，不能當成 iPhone 1080p／FPS 實測。
- LAN HTTP 憑證下載回 200；HTTPS `/mobile` 與靜態資源以本機 CA 驗證回 200，未跳過 TLS 檢查。獨立 HTTPS gateway 不載入相機／模型後端。
- 實際 HTTPS 配對 → WSS 狀態事件 → DELETE session 204 → disconnected 事件／WSS close 1000 → 舊 token 401 → 桌面可重新配對完整通過，TLS 均驗證本機 CA。
- 配對結束後清理 RTC、定位工作階段、票與 token；聊天／照片持久化保留。手機失聯時舊 preview 不會重新取得可拍照提示。
- 修正影片連線狀態與辨識上下文的耦合：目前 generation 收到實際影格即允許桌面預覽；作品內容不同時仍撤銷拍照提示。新增測試確認零影格、舊 generation、停止或 RTC 失敗後的晚到 metrics 不會恢復連線。

## 本次啟動狀態

- 筆電 Wi-Fi：ATD_ROG，192.168.50.141/24。後端 8100、HTTPS gateway 8443 各僅一份。
- 手機入口：`https://192.168.50.141:8443/mobile`。
- 首次憑證下載：`http://192.168.50.141:8100/api/mobile/web-ca-profile`。
- 使用者回覆 iPhone IP 為 192.168.50.221，已安裝及信任描述檔，並確認 Safari 已看到相機畫面；後端也收到實際 iPhone 影片。
- 已確認現有 Python312 Public inbound TCP／UDP allow 存在。未改動防火牆規則、Wi-Fi 類別、Windows 根憑證、webcam 設定或模型設定。
- Expo Metro 與待登入的 EAS CLI 已停止；Safari 不需要這些服務。

## 尚未完成實機驗證

1. 720p、端到端延遲、bitrate 與相機切換。8／12 Mbps 是送端上限目標，並非測得或保證的速率；桌面 aiortc relay 會重新編碼。
2. iPhone 正式高解析度拍照／短影片上傳，完整 GPIO 對位與實物接線核對。
3. iPhone 移動、遮擋、失焦、旋轉、鎖屏、重連與拍照取消的實際表現。

## iPhone 影片與辨識量測

- Safari 直向實際輸入為 1080 × 1920；同一 generation 連續 44.47 秒收到 1324 張影格，平均 29.77 FPS，未發生該段串流重啟。這是筆電接收速度，不是端到端延遲或桌面顯示 FPS。
- 較早的短暫有效取景曾收到約 29.5–30 FPS、辨識約 2.71–2.87 FPS 並進入鎖定狀態；Pi 5、HC-SR04、TFT runtime 均回報 CUDA，實際 ONNX provider 優先使用 CUDAExecutionProvider。
- 後續桌面恢復了不同版本的接線上下文，正式撤銷取景鎖定，辨識結果不再接受。當時影片仍持續傳送，卻因 publisher_connected 只在接受辨識結果時更新，造成桌面隱藏影片；已修正並通過上述測試，部署後需重新配對確認。
- 這些數字不代表正式照片的 GPIO 精度、模型實物準確率或長時間穩定度。原 webcam 的介面及相關回歸測試通過，未進行完整重新校正或硬體驗收；未執行 Pi 部署。

## 聊天顯示同步修正

- 使用者手機的「安安」及 AI「安安！」已保存於同一作品對話，20:15:00／20:15:03 完成；請求屬於 round 2，而目前桌面 round 3。原桌面合併紀錄時標為先前輪次並預設隱藏，手機卻仍顯示，形成不同步的觀感。
- 兩端改用共用聊天可見性規則：同一 context_epoch 的各輪次訊息預設顯示，保留前輪標記；清除上下文後的舊 epoch 需手動展開。展開狀態綁定對話與 epoch，切換或清除後不會自動顯示舊上下文。
- assistant、mobile_web、chat_scroll 共 38 項相關測試通過，TypeScript／Vite build 與 i18n 通過。桌面實際重載後已直接顯示原本兩則「安安」，未重送 AI 或重寫保存檔，未重啟後端／HTTPS gateway。
- 瀏覽器證據：`C:\Users\james\AppData\Local\Temp\tinkro-chat-sync-fixed.jpg`。iPhone 尚需重新整理 Safari 載入新網頁；本次未代替使用者在實機送出新的測試訊息。

## 手機風格統一

- 手機配對、聊天、取景與照片頁改用桌面共用的 surface／ink／line／brand tokens、Pro 字體規則與控制項圓角。聊天角色配色在 assistant.css 共用；手機沿用桌面 Logo 與漸層送出按鈕，保留 44px 以上觸控高度。
- 37 項相關前端測試、23 項 HTTPS gateway 測試、TypeScript／Vite build 與 i18n 通過。320 × 740 淺色與 390 × 844 深色的瀏覽器檢查沒有水平溢出；390px 聊天按鈕至少 44px，320px 開啟取景按鈕位於 y=182–230。
- 正式 `/mobile` 頁顯示深色背景及已載入的 Logo；HTTPS 手機入口與公開 Logo 均以本機 CA 驗證回 200。只重啟 HTTPS gateway，8100 後端 PID 57136 保持運行。
- 聊天樣式截圖使用獨立的合成內容介面預覽，沒有配對真實手機、呼叫 AI 或開相機；不可將截圖中的同步狀態或示範回答當成新的實機測試。正式配對頁截圖：`C:\Users\james\AppData\Local\Temp\tinkro-mobile-entry-style.jpg`；聊天樣式預覽：`C:\Users\james\AppData\Local\Temp\tinkro-mobile-style-dark.jpg`。

## 2026-10-03 失效手機連線復原

- 使用者 Safari 顯示 `mobile_session_expired_or_invalid`；當時後端與 HTTPS gateway 在線，目前作品 session 為 null，手機保存的舊 token 無法使用。失效的 session 與五分鐘配對碼分別處理。
- 僅具體的 session 失效 401／404 才停止手機媒體與請求、關閉 WS／輪詢並清除舊配對，回到輸入新配對碼頁。HTTP 503 或一般網路錯誤保留配對；舊 token 晚到的錯誤不能清除新配對。IndexedDB 草稿與附件不刪除。
- 30 項 mobile_browser／mobile_web 測試、TypeScript／Vite build 及 i18n 通過。獨立 localhost mock server 使用真實 MobileWebApp／useMobileBrowser 驗證：401 自動回配對頁並顯示中文原因；重新配對後原文字草稿恢復；503 保留聊天頁與草稿。測試未連真實後端、相機或 AI，測試服務與頁面已關閉。
- 正式 HTTPS `/mobile` 使用指定 root CA 嚴格驗證回 200，已供應新版前端。未重啟 8100 後端或 8443 gateway；仍需使用者重新整理 iPhone Safari 並重新配對，實機重連尚待確認。

## 2026-10-03 後端退出／502 復原與實機畫面

- 使用者回報手機 502、桌面 `Failed to fetch`；查到 8443 gateway 仍在，但 8100 已不再監聽，原 exec session exit 1。原輸出只有 Proactor 清理 callback 的 WinError 10054；這類例外通常只由 event loop 記錄，Windows Application／GPU／資源耗盡事件亦未提供相符 crash 證據，故真正退出原因仍未確定。
- 恢復原設定後端，再改為隱藏、獨立 PowerShell 背景監督啟動。`start-mobile-prototype.ps1` 啟用 Python `-u -X faulthandler`、完整 stdout/stderr 與 JSONL 退出碼；異常最多重試三次、2／4／8 秒退避。正常／中斷退出不重啟；共享 lock、每次 port/process 檢查避免兩份後端與相機。gateway 未重啟，原 webcam 設定未改。
- `test-mobile-backend-supervisor.ps1` 的隔離子程序檢查涵蓋退出碼/hex、有限次數、stdout/stderr、正常退出、啟動/重啟前 guard、退避及中斷停止；PowerShell 7、Windows PowerShell 5 均通過。這些測試未啟動真實 app.main。
- 使用者重新配對並實際開啟 iPhone 取景；後端 generation 1 收到直向 1080×1920，短窗口曾回報 29.53–30 FPS，辨識約 2.82–2.87 FPS，三個 ONNX 模型 actual_backend 與前處理均為 CUDA。啟動初期與部分窗口曾低於此速度，因此不能將目標 30 FPS 當作全程穩定速度。
- 首次復原後電腦 `<video>` 確認 videoWidth=1080、videoHeight=1920、readyState=4、paused=false，畫面呈現 Pi 5 與超音波模組；`C:\Users\james\AppData\Local\Temp\tinkro-phone-live-restored.jpg` 是修正編碼前的實機證據。原 webcam `/frame.jpg` 同時回 200；4/11 人工確認紀錄及原聊天保留。
- 首次監督後端 PID 38340 於 10:13:37 再次退出，退出碼 -1073741819（0xC0000005，原生 access violation）；faulthandler 捕捉多個 `aiortc/codecs/vpx.py` encode 執行緒，監督自動啟動 attempt 1／PID 97768。這次記錄將故障縮小到 VP8 原生編碼；不能將先前 WinError 10054 當作已證實根因，也沒有 CUDA 崩潰證據。

### H.264 與觀看端影格隔離修正

- 手機 publisher、桌面 viewer 與 aiortc 答覆均優先 H.264，保留只支援 VP8 的協商 fallback。SDP codec 與實際接收尺寸分別回報，不把設定值當成量測值。
- 每個 viewer 取得獨立像素與時間戳的 VideoFrame；共享原始 frame 的轉換在同一 event loop 執行，避免多個 encoder 並行改動共享像素／reformatter。一般停止／重開先結束媒體並等候編碼；drain 逾時保留舊 ownership，回 503 而不建立競爭的 generation。強制 transport 取消的原生編碼停止時點尚未完整驗證；隔離 clone 仍避免共用原始 frame。
- 相關後端 46 項、前端 mobile／mobile_browser／mobile_web 40 項通過，TypeScript、Vite build 與 i18n 通過。獨立 H.264 encoder 的 600 張合成影格，以及實際 MobileRTC 的 1080×1920 合成 publisher → 兩個 aiortc viewer、同 session 重開三輪共 264 張皆通過；後者完整 close 約 31 ms，generation／frame 像素隔離／時間戳／集合清理通過。這些合成數字不代表 iPhone 實機 FPS。
- 修正版後端 PID 45628、監督 PID 92312；HTTPS gateway PID 25400 沿用。新事件檔 `backend/runs/mobile-backend/20261003-101844-8865-events.jsonl` 截至短程實機檢查只有 attempt 0 starting，沒有退出或重啟。原 webcam 設定及模型未改。
- 使用者再次確認已開啟新版取景。實機 session generation 1 的 publisher／viewer 答覆均為 H.264，電腦 video 為 1080×1920、readyState 4、paused false，currentTime 持續增加；畫面證據為 `C:\Users\james\AppData\Local\Temp\tinkro-phone-h264-restored.jpg`。啟動初期速度曾低於 30 FPS；10:22:36–10:23:21 同一 generation 的 45.36 秒收到 1359 張，平均接收 29.96 FPS，各窗口辨識約 2.67–2.91 FPS，模型 actual_backend／preprocessing_backend 均為 CUDA。這是接收 FPS，不是端到端延遲或桌面顯示 FPS。長時間穩定度仍未驗證。
- 本次修復串流及 502，未拍正式 GPIO 照片，也未驗證 GPIO 精度或 Pi 部署；手機取景提示不代表精細腳位已確認。

## 2026-10-03 手機與電腦串流畫質／速度落差

- 使用者回報手機本地取景與筆電串流品質及速度差距。已安裝 aiortc 1.15.0 的 H.264 viewer 重編碼原為預設 1 Mbps、硬上限 3 Mbps；手機送端的 8／12 Mbps 上限並未傳給這個編碼器。正式桌面在換上診斷前端後、後端仍是舊 encoder 的一個窗口實測：1080×1920、解碼 29.9 FPS、實際呈現 27.9 FPS、接收 1.03 Mbps、遺失 0%、接收緩衝 41 ms。這不是完整端到端延遲測量。
- 手機專用 H.264 encoder adapter 使用每個 viewer 自己的 libx264 context，預設目標 8 Mbps、上限跟隨 3／8／12 Mbps 選項，保留接收方 REMB 降碼率；使用 veryfast、zerolatency，保留 frame 與 codec 的色彩範圍／色彩資訊，不調 gamma 或銳化，不修改 aiortc 全域常數／site-packages、webcam、模型或 CUDA。
- 手機 POST `/stream` 可選 `{bitrate_kbps:8000}`，舊無 body 呼叫相容。每三秒的 POST `/stream/metrics` 僅保存當前 generation 的有限診斷數值，不更新接收影格、可拍照、定位、配對或有效期限；過期 generation／停流回 409。伺服器記錄出站 bytesSent 差分、當秒 clone／encode 時間、codec、編碼目標與 fallback。尚無實際 RTP 發送影格統計時保持 send_fps=null，不以 encode_fps 取代。
- 桌面分開量測解碼與實際呈現 FPS；後者使用 requestVideoFrameCallback、或 totalVideoFrames 減 droppedVideoFrames fallback。不支援／換 SSRC／計數重置顯示未知，不假設 30。補上實際接收 Mbps、封包遺失率與當段 jitter buffer 延遲；支援時嘗試 20 ms 緩衝目標，不宣稱實際達成 20 ms。手機顯示實際上傳 FPS、尺寸、RTT 與限制原因；碼率設定與測得值分開。
- 離線壓縮品質：相同 1080×1920 合成細字／格線及輕微移動畫面、15 張暖機＋75 張量測，stock 1／3 Mbps 與 mobile 8／12 Mbps 的細節 ROI Y-PSNR 為 29.12／41.81／54.66／59.14 dB，encode P95 為 5.655／6.754／4.974／4.873 ms，尺寸保留。內容 VBR payload 約 0.656／1.295／2.566／2.024 Mbps，因此這些結果不是 8／12 Mbps 實際網路達成、iPhone FPS、辨識精度或實拍清晰度。證據：`backend/runs/mobile-stream-quality/20261003-102839/report.json`。
- 初次新版兩 viewer 壓測遇到 ICE `pc.close()` 等待超過七秒；native encode 沒有 access violation，forwarder drain 已完成。測試取消 close 後，第二次 close 等待同一未完成 Future；這一輪不能列為通過。正在加入 owned close task、shield 及有界等待，重試保留原 task，不盲目解除 aioice 私有 Future。
- 後續修正為每個 peer 保留唯一 cleanup task，以 shield 保護、不讓 HTTP 取消中斷原清理，五秒等待逾時回 503，重試加入同一 task。62 項相關後端測試通過，包括 caller 取消、清理未完成不能啟動下一代、逾時重試不重複 close。最終同 session、3／8／12 Mbps、1080×1920、每代兩個實際 aiortc viewer 的合成壓測通過，共 393 張，REMB 降至 1.2 Mbps 與回 cap 通過，close／drain 31／31／32 ms、無 503／重試／native crash。報告 `backend/runs/mobile-stream-quality/20261003-103524-lifecycle.json`；原失敗證據保留，沒有宣稱已證實其 Windows ICE 根因。
- 52 項相關前端測試、TypeScript／Vite build 與 i18n 通過。手機介面分開顯示擷取、上傳、電腦接收與辨識 FPS，保留現有草稿／照片／作品聊天流程；桌面 DOM 確認原 4/11 接線紀錄及安安／Hello 聊天仍在。
- 第一輪修正版以原隱藏 supervisor 啟動方式部署：監督 PID 77872、後端 PID 75372；8100／8443 各只有一個監聽服務。後端更新造成原執行階段的手機配對失效，需要一次重新配對，未改憑證或 webcam 設定。
- 真機開始後發現 HTTPS gateway 的允許路由未包含新 POST `/api/mobile/stream/metrics`，故原先手機診斷未傳入後端；補上限定 POST 路由與 body／bearer／IP 轉送測試，24 項 gateway 測試通過。僅重啟 gateway 為 PID 69428，原手機配對維持；嚴格 CA／主機名驗證 `/mobile` 回 200，空 body 的 metrics 回後端 422 而非 gateway 404。
- 使用者確認兩次開啟高畫質取景；第二次 generation 2 實際設定是 8 Mbps 上限、1080×1920，不是要求中的 12 Mbps。啟動初期手機擷取約 30 FPS、實際上傳 2–6 FPS，後續恢复約 30；桌面 REMB 曾降至 500–1000 kbps。10:44 桌面窗口顯示接收 30、解碼／顯示 28.9 FPS、手機上傳 2.65 Mbps、桌面接收 3.39 Mbps、封包遺失 0%、接收緩衝 80.1 ms；下一個伺服器窗口 target 7.31 Mbps、實際出站 6.58 Mbps、encode 4.04 ms、clone 7.78 ms，當時只剩一個 viewer。碼率與 FPS 會變動，不能將此單窗口當作全程穩定，也不能斷定 REMB 下調已證实來自事件迴圈阻塞。
- 每 viewer 舊 clone 在真機耗時約 6–11 ms。隔離 native H.264 解碼 1080×1920 影格的不同 pitch（來源 1152／576／576、目標 1088／544／544）量測，新同格式 YUV plane 有效像素 copy 的 median／P95 為 1.10／1.51 ms，舊 ndarray pack copy 為 4.07／5.87 ms；像素逐位元相同且 buffer 獨立。已新增不同 stride、奇數尺寸、padding、buffer 隔離、時間戳與色彩 metadata、RGB fallback 測試；相關後端 67 項通過。報告 `backend/runs/mobile-stream-quality/clone_plane_benchmark.json`。這是隔離複製速度，不代表已部署後真機提升或完整端到端延遲。
- 最後獨立重測新 clone：同 session 3／8／12 Mbps 各兩個 aiortc H.264 viewer，共 394 張、全部 1080×1920；clone 平均 0.874–1.111 ms、close/drain 15–16 ms，沒有 503／重試／native crash，像素隔離及 metadata 通過。證據 `backend/runs/mobile-stream-quality/20261003-104519-lifecycle.json`。最後合併重跑相關後端與 gateway **91 項通過**；相關前端 **52 項、TypeScript、Vite、i18n** 已通過。
- 最終部署監督 PID 69624、後端 PID 34860，gateway PID 69428 保持。使用者再次確認取景後，generation 1 實機 **8 Mbps 上限、H.264、1080×1920**；3 個 ONNX 模型 actual_backend 與 preprocessing_backend 皆 CUDA。新的 YUV clone 已在真機量到約 1–2 ms；啟動前約 25 秒仍只有約 2–9 FPS 上傳，後來恢復约 30，不能宣稱消除了啟動降速。
- 10:48:10–10:49:06 的 12 個五秒樣本均為同 generation、兩個 viewer；55.38 秒影格計數差分 1634 張，平均接收 29.51 FPS（計數由約每秒更新的接收 snapshot 提供），接收窗口約 29.53–30.54 FPS，clone 平均窗口 1.176–1.830 ms。手機送端多數窗口約 29.9–30 FPS，但一個診斷窗口降至 13.97；實際上傳碼率隨內容／回饋約 0.91–7.59 Mbps。桌面 DOM 窗口顯示約 28–30 FPS；其中一個窗口接收緩衝 18.9 ms、loss 0%，其他窗口約 50 ms，這些都不是完整端到端延遲。紀錄 `backend/runs/mobile-stream-quality/20261003-final-live-samples.json`、`20261003-final-live-steady.json`。
- 本次實拍是手機對筆電螢幕，未拍正式 GPIO 分析照片，不是零件／腳位精度驗證，也尚未量到套用 **12 Mbps** 的 iPhone 結果。原 webcam `/frame.jpg` 回 200、桌面原來源仍顯示板卡及標記，4/11 接線紀錄和聊天保留；最終事件檔 `20261003-104547-5819-events.jsonl` 截至此次檢查只有 attempt 0 starting、沒有退出。介面證據 `C:\Users\james\AppData\Local\Temp\tinkro-phone-quality-optimized.jpg`。

## 2026-10-03 兩種拍照與持續串流

- 桌面新增「截取手機影像」，POST `/api/mobile/stream-capture` 綁定 session、generation、context 及 request ID。直接保存 RTC 最新原始接收影格為完整尺寸 PNG；不截網頁、不使用 webcam FrameBus，也不要求預覽 Locked。影格原接收時間超過 1.5 秒、停止或換代後拒絕新截圖。
- 手機「鎖定拍照」改為本地完整 `<video>` 影格的 JPEG 95；不釋放相機、沒有第二次 getUserMedia。照片與聊天分頁保留串流；背景、離線及明確停止仍清理相機。此快速拍照受目前取景解析度限制，不宣稱是原始 12MP 相機照片。
- 兩路都重新執行既有 YOLO／PhotoGeometry。照片有獨立 hash、尺寸、frame ID 和 runtime revision，手機與桌面分析完成順序顛倒、切换作品或選取其他照片時，舊結果僅保存，不覆蓋新的共用檢視／聊天引用。同 ID 重試加入原分析，不重新截圖或推論。桌面分析等候超過 180 秒解除忙碌，可重試讀取同張照片。
- 最終前端照片／手機測試 **88/88**、Assistant **23/23**，TypeScript／Vite build、i18n 通過。最終後端 mobile／RTC／gateway／照片／Assistant 相關回歸 **155/155 通過**；新截圖專項包括 pending recv 關閉後不能復活。測試使用合成影格或假模型，不能當作 GPIO 實物準確率。
- 獨立手機 QA 透過真正 MobileWebSurface／useMobileBrowser、Canvas 假相機及隔離 API，分別驗證 1920×1080 與 1080×1920。實際上傳 JPEG 的 SOF 尺寸、quality 0.95、capture_source=phone_frame 均符合；取景→Locked→拍照→照片→聊天→取景，相機開啟一次、停止零次、generation 不變。示範 GPIO 是假標記，不是實物定位證據。
- 本次部署監督 PID 30416、後端 PID 27188、gateway PID 62564，8100／8443 各僅一個監聽。HTTPS `/mobile` 使用 Python SSL context 驗證本機 CA 及 hostname 回 200；Windows curl Schannel 的本機 CA 撤銷查詢未知，沒有停用 TLS 驗證。憑證、防火牆、Webcam 設定及模型設定均未修改。
- 使用者重新配對並開啟真實 iPhone 串流。11:22 筆電從 Finding 狀態成功截取 **1080×1920**，capture `7a8207b6460d455ea4984c8fe8f5872a`、source=desktop_stream、generation 1、原影格 seq 935；保存為 PNG 且分析 hash 一致。照片完成後仍 generation 1、active=true，影格計數至 1401；接收窗口約 29.53 FPS。三個 ONNX 模型 actual_backend／preprocessing_backend 均 CUDA。
- 該照片 Pi 5 使用 reference_sift_j8，板面及排針影像校正條件通過，並顯示 GPIO；HC-SR04／TFT 沒有辨識到，保留 not_found。contact_visibility_verified=false、electrical_verified=false，沒有人工逐腳確認，不宣稱 GPIO 實物精度或接線正確。真機手機本地拍照仍待核對新上傳。
- 原 Webcam `/frame.jpg` 回 200，桌面原來源持續顯示 Pi／零件，人工接線 4/11 及原聊天保留；沒有操作 Pi、電氣測試或重設原照片 POC。新後端事件 `20261003-112028-4108-events.jsonl` 此次檢查只有 attempt 0 starting，stderr 無錯誤。介面證據 `C:\Users\james\AppData\Local\Temp\tinkro-phone-dual-capture.jpg`。
- 真機確認期間再次出現工作區更新：手機 context c090d7da 與桌面 4f606abe 的 JSON 差異只有 `context.debug_session_id`，同作品、revision、round、接線目標都相同。該暫時 ID 被納入手機 context hash，誤撤銷取景鎖定。前後端手機快照在 hash／保存前排除此頂層欄位，保留 debug_context 的接線目標、影像與程式；桌面原 send／debug continuation 保留原 ID。手機無附件的純文字問題走既有文字建議，手機照片 AI 本來就使用獨立 media 路徑。8 項後端及 2 項前端回歸確認除錯 ID 變動不換 context、鎖定／拍照票保留，真正作品、round、revision、wire、epoch 變動仍撤銷。
- 11:35 最後部署為監督 PID 31668，HTTPS gateway PID 62564 維持；原相片及聊天持久化保留。此後手機需重新配對，最終手機本地照片到達與同步仍待實機核對。
- 最終重新配對後，同一 context da6aa3e5 維持，實機預覽進入 Locked，手機完成新的本地拍照。保存 capture `31f7c00afcc24900a8480ae26108e83f`、source=phone_frame、JPEG **1080×1920**，HTTP 200 且檔案 SHA-256 與分析一致。手機選取 `hc-sr04:trig` 同步至桌面 view revision 2；拍照後 stream active=true、generation 1、收到 1310 張、接收窗口 30 FPS。這次確認正式手機照片已到達，不以使用者回覆代替接收紀錄。
- 這張手機照片 Pi 5 與 HC-SR04 都有 YOLO 候選，但板面／零件方向校正不足，分別保留 board_geometry_unverified／component_reference_unverified；TFT not_found。沒有顯示未確認的 GPIO 點。「Locked 可拍照」與「照片 GPIO 精確定位」維持分開。手機與筆電使用相同來源名稱，手機已保存與未完成上傳狀態分開顯示。
- 最終後端 PID 79184，8100／8443 各一個監聽，事件 `20261003-113535-6185-events.jsonl` 只有 attempt 0 starting，stderr 無錯誤；HTTPS CA／主機名驗證與 Webcam frame 皆 200。隔離 18789／18790 測試服務已停止。
- 使用者確認「已保存至筆電」後，最新筆電截圖 capture `ff9c854eb494461b9cf7832cd47718b5` 為 desktop_stream、PNG **1080×1920**；Pi 5 的 reference_sift_j8 校正通過，顯示 GPIO10／Pin 19。HC-SR04 與 TFT 有辨識到本體，但分別保留 component_reference_unverified／ring_layout_or_header_unverified，不宣稱其腳位方向或實物精度已確認。目前選線 `mrd-tf240-8p-cs:sda` 同步在第 7/11 條；串流仍為 generation 1、active=true，接收窗口約 29.56 FPS。最終介面證據 `C:\Users\james\AppData\Local\Temp\tinkro-phone-dual-capture-final.jpg` 同時顯示原 Webcam 與手機固定照片 GPIO 檢視。
