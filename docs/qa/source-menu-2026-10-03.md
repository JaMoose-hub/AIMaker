# 影像來源浮動選單 — 2026-10-03

## 變更

- 原生 select 改為自訂浮動選單，保留畫面右上膠囊觸發器。
- Webcam／手機各有圖示、短說明與目前來源勾選標記；僅成功回傳的新 source prop 改變選取狀態。
- 選單 portal 到 body，依觸發器位置定位、翻轉／限制在視窗內，避免被縮小的 video shell 裁切。
- 保留原本配對與切換回呼；不建立串流、不改 YOLO、backend、capture 或 Pi 狀態。
- React 檢查：事件／ResizeObserver 僅展開時註冊並清理，元件不內嵌定義，原本來源與相機生命週期不變。

## 驗證

- `node --test tools/image_view_controls.test.mjs`：7 項通過，沒有執行超過 100 次測試。
- TypeScript 檢查、production build 通過；保留既有 chunk-size 警告。
- 隔離瀏覽器驗證：滑鼠選擇、方向鍵不提前切換、Enter 確認、Esc 返回觸發器、Tab 離開、點外部關閉。
- 未配對時顯示「連接手機」，點擊開啟 mock 配對入口，來源仍是 Webcam、切換次數仍為 0。
- 1100×760 深色、390×650 淺色以及 1413×871 完整接線頁檢查。窄版選單在 viewport 內；完整頁面切到手機只有一次 source POST，無額外手機 viewer，errors=[]。
- 過程中 CLI 的 role/name 定位未找到 checkbox/menuitem；改用新 snapshot 的精確 ref 後實際互動正常，未修改產品邏輯繞過測試。
- 實際 8100 入口與目前 dist 一致。沒有重啟服務、重新配對真手機或執行硬體測試。

截圖：`source-menu-open.png`、`source-menu-light-mobile.png`、`source-menu-app.png`。
