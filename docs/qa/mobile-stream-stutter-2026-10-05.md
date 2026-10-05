# 手機串流卡頓與破圖修正 — 2026-10-05

使用者回報手機本地畫面順、筆電卡頓且偶爾破圖。新版已載入；使用者重新整理筆電後回覆「目前順暢、沒有破圖」。本次未改 Webcam 程式、校正或設定，未調低手機解析度、碼率上限或相機 FPS。

## 已完成修正

- 在手機 publisher 的 aiortc 1.15 video receiver 開始接收前，將原本 128 包的 jitter buffer 換成手機專用 512 包、prefetch=0 的 buffer。原組包、NACK、PLI 流程保留；不改全域 factory、viewer 或 Webcam。版本、私有欄位或尚未接收的條件不符時保留原設定並回報原因。
- 只對 `phone:` 來源增加 JPEG 解碼 1000 ms 期限與 AbortSignal 清理。解碼停住不再永久阻塞後續 polling；取消後晚到的結果不復活舊影格。標準相機仍走原來的 decode 分支。
- 增加唯讀 `/api/mobile/stream/diagnostics`，可在沒有新解碼影格時取得 RTP 收包、遺失、jitter、解碼年齡、接收容量、溢位與 PLI 計數。另加入手機編碼與重傳統計，未知欄位保存 null，不推測為 0。
- 記錄手機 sampling 例外，保留原有斷線處理。

## 可重現的程式缺陷

使用實際安裝的 aiortc 1.15.0，以 200 個連續且沒有丟包的 H.264 FU-A 分片測試。影格共 239,605 bytes：原 128 容量觸發一次 PLI，只交付 86,256 bytes 且缺 NAL 起頭；512 可完整還原且無 PLI。序號回繞測試結果相同。原 buffer 需看到下一個 timestamp 才交付，因此完整影格最大包數為 capacity−1。

這證明接收端有大影格重組缺陷；本次舊版偶發停頓時沒有封包級紀錄，不能認定它是所有現場停頓的唯一原因。較大容量沒有增加 prefetch，但真正丟包未補回時可能延長等待；未更動速率控制來掩蓋此限制。

## iPhone 實測

量測檔在 `backend/runs/mobile-stream-quality/20261005-post-fix-live.json`，摘要為 `20261005-post-fix-summary.json`。只讀取既有 API，沒有啟動第二份相機或 viewer encoder。

| 項目 | 實際結果 |
|---|---|
| 觀察時間 | 180.058 秒，93 次採樣含等待連線 |
| 實際收到尺寸 | 1920×1080 |
| 碼率上限 | 12,000 kbps；上限不等於實際碼率 |
| 排除前 30 秒暖機後的區間 | 148.060 秒，4,441 張新解碼影格 |
| 該區間接收 FPS | 29.9946 |
| 該區間採樣的最大解碼影格年齡 | 63 ms；不是端到端延遲 |
| 接收 RTP 包／遺失包 | 17,794／0 |
| 接收 buffer 溢位／PLI flags | 0／0 |
| 採樣時解碼佇列 | 無堆積，最後 0 張 |
| 使用者筆電觀察 | 目前順暢、沒有破圖 |

本段最大 timestamp arrival 高水位為 79（含可能重複抵達，非完整影格的唯一包數），未觸發原容量邊界；大影格修復的證據來自上述重組測試。一次保存的實際串流 JPEG `20261005-post-fix-phone-frame.jpg` 可正常讀取，視覺觀察未見塊狀破圖；不把單張圖片當作連續影片驗證。

本輪手機回報仍未包含新增的 encoding／counter 欄位；執行中 OpenAPI 已確認新 schema，程式邏輯顯示手機可能仍使用先前載入的 chunk。本輪 FPS 結論採接收端不同影格的序號與時間差，不依賴該手機統計，也不將它解讀為 Safari 編碼停頓。新手機程式於正常重新載入後可使用新增統計。

接收 FPS 與筆電實際呈現 FPS 分開：本次沒有瀏覽器呈現時間 profile，筆電順暢與未破圖的結果由使用者現場確認。本次為三分鐘觀察，未聲稱長時間、不同網路或所有移動場景皆無卡頓。

## 軟體與部署驗證

- 後端：`pytest tests/test_mobile.py tests/test_mobile_api.py tests/test_mobile_rtc.py tests/test_mobile_without_webcam.py -q`，222 passed。
- 前端：`node --test tools/mobile_browser.test.mjs tools/realtime_frame.test.mjs tools/capture_countdown.test.mjs`，92 passed；涵蓋解碼掛住後恢復、取消、晚到 rejection、Webcam 分支與統計 reset。
- `npm run build` 與 `git diff --check` 通過。
- 只重載 8100 真正的後端一次，沿用既有 supervisor；8443 HTTPS gateway 與憑證未重啟。恢復原作品上下文，重新配對後量測同一代串流。新後端 stderr 為空。
- 未操作接線、Pi 部署或模型生命週期；不將串流結果當作 GPIO 或電氣正確性的證據。
