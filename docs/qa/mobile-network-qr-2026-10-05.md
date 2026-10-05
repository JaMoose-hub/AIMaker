# 換 Wi-Fi 後手機網址與 QR 更新

## 原因與修正

筆電由 ATD_ROG 換至 ASUS_ATD，IPv4 從 `192.168.50.141` 變成 `192.168.50.138`。8100 後端仍正常，但 `connection.json` 與 HTTPS 伺服器憑證 SAN 都保留舊 IP；以新 IP 進行嚴格 TLS 驗證出現 IP address mismatch。

更新含新 IP 的伺服器憑證，保留現有 CA。啟動器每 5 秒偵測實體 Wi-Fi（其次 Ethernet），連續兩次相同 IP 才啟動或切換 8443 gateway；同 IP 保留既有程序。確認斷網時停止自有 gateway，Windows 網路查詢暫時失敗則保留程序等待重試。只管理自己啟動的程序與其子程序，不重啟 8100。

桌面連接面板開啟時持續讀取 `web-config`，讀取完成前、網址改變或 HTTPS 不可用時隱藏舊 QR；新入口可用後產生新配對碼。配對 POST 完成後再次比對入口，晚到回覆不能恢復舊 IP。手動指定網址仍可使用，同一入口不反覆自動產生碼。保存過的 QR 圖片不會更新，應掃目前筆電顯示的碼。

## 本次已完成的驗證

- `scripts/test-mobile-web-network.ps1`：38 個隔離斷言通過，包含網卡優先順序、IP 切換、斷線恢復、查詢例外、程序清理、同埠鎖、失敗回復與 CA 保留。
- 前端 `npm run build` 通過，包含 TypeScript 與 Vite；保留既有 chunk 大小警告。
- 前端 `mobile.test.mjs`：72/72 通過，涵蓋新 IP、不可用狀態、晚到回覆與手動入口；獨立 TypeScript 檢查也通過。
- CUA 隔離介面測試通過：141 初始 QR、HTTPS 未就緒隱藏、138 自動新 QR、同 IP 不重發、延遲舊配對被捨棄，以及關閉面板後換網路再開啟。使用真實 `MobileCompanion` 元件與假 API，不操作正式作品、相機或 Pi。
- [隔離介面截圖](mobile-network-qr-2026-10-05.jpg) 為測試碼，不可用於正式配對。新的前端 build 已由現行 gateway 提供；桌面頁面需重新整理一次。
- 現行 `https://192.168.50.138:8443/mobile` 使用既有 `rootCA.pem` 驗證信任鏈及 hostname，HTTP 200。
- loopback `/api/mobile/web-config` 回傳 `available: true` 與新 138 入口。
- CA PEM SHA256 更新前後相同：`8c60ab32045bab9eee470f337b64a910f8a3a4b60342f56c7efcc1327919f74c`。
- 使用者回覆「已連上工作區」；後端確認手機工作階段使用新 138 入口，且已收到 1920×1080 影格。這不是串流流暢度驗收。
- 已部署長駐網路監測啟動器，觀察 confirming → started → unchanged；只有一個 8443 listener。8100 仍為原 PID 55320，未重啟後端或修改 Webcam 設定。
- 最新程式經獨立唯讀審查，未發現剩餘阻擋問題。

## 驗證界線

本次在已切換的 ASUS_ATD 上恢復實機連線，並部署自動監測。部署後再次切換真實 Wi-Fi 的端到端測試尚未執行；切换邏輯目前由隔離測試覆蓋。沒有進行 Webcam 實拍、GPIO、電氣或模型準確率驗收。
