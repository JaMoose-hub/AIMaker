# 手機連線指示與作品同步分離 — 2026-10-05

本次側對話只修改連線指示，不重啟正式服務、不切換相機來源、不停止手機串流或 Pi，也沒有更動工作流程 Reset 或相機調整功能。

## 修正

- 既有 loopback-only `GET /api/mobile/desktop-session` 增加 `connection` 白名單摘要，並設定 `Cache-Control: no-store`。
- 摘要根據有效手機事件連線或 1.5 秒內收到的串流影格判定；僅保存配對記錄不等於目前在線。優先顯示目前作品的在線手機，否則顯示其他作品的在線手機。
- 桌面綠燈反映手機在線，不再因切換作品而誤顯示等待掃碼。跨作品另提示「尚未同步目前作品」，並提醒切換工作區後重新開啟串流。
- 摘要不帶 token、完整 context、照片、view 或 GPIO；原有 `session`、照片操作、相機來源切換與訊息傳送仍限目前 conversation。
- 狀態查詢失敗清除綠燈並顯示待確認；作品事件不能掩蓋連線查詢失敗。對舊後端僅保留原本同作品配對判斷，不推測跨作品連線。
- 沿用現有 5 秒輪詢，沒有新增相機、RTC viewer 或狀態 WebSocket。

## 驗證

- `node --test tools/mobile.test.mjs`：65 項通過，包括跨作品綠燈、離線、錯誤恢復、作用域隔離及切換作品時保留裝置狀態。
- 後端 `tests/test_mobile.py tests/test_mobile_api.py`：175 項通過，全部使用 fake RTC / 合成資料，不操作真實硬體。
- `check_i18n.mjs`：中英文 761 keys 一致。
- 實際 MobileCompanion + useMobileCompanion 的隔離瀏覽器頁面確認：跨作品為綠燈（`rgb(61, 214, 140)`）並顯示同步提示；已配對離線時為灰燈並顯示「手機已配對，目前離線」。隔離頁面不代理任何正式 API。
- 截圖：`C:/Users/james/AppData/Local/Temp/tinkro-phone-connection-qa-20261005.jpg`。
- 可重現 UI fixture：在 frontend 執行 `node tools/mobile_connection_preview.mjs`；使用啟動時輸出的隨機 loopback port，支援 `?case=other/current/offline/error`。

## 未通過或尚未執行

- 擴大手機測試 117 項中，114 通過、3 失敗；`mobile_web.test.mjs` 引用已不存在的 `MobileWiringPhotoDialogue`。本次未修改 MobileWebApp 或那些舊測試。
- 前一次 TypeScript 與隔離 production build 成功；最後重跑 TypeScript 時，並行主線新增的 `phoneCameraTuning.ts:122/124` 出現 4 個 `BrowserRtcStats.measuredAtMs` 型別錯誤。本次保留主線檔案，未修復該功能，不能宣稱整份最新工作區編譯通過。
- 未覆寫正式 dist、未重啟後端、未重新整理使用中的正式瀏覽器頁面。正式套用仍需完整編譯通過後建置前端、重啟後端及重新整理桌面頁面。
- 本次沒有套用後的真實手機端對端驗收，也不代表 GPIO／硬體功能驗收。
