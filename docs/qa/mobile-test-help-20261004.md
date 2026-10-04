# 手機訊息內拍照檢查邀請

手機共用助手新增與桌面相同的「拍照檢查／稍後」。有效的既有照片核對顯示「繼續照片核對」，進入既有逐張拍攝流程；不另建相機上傳管線。公開對話只顯示簡短提醒，測試來源與接線版本由私有結構資料傳遞。

## 行為與邊界

- 操作綁定確切訊息、offer ID、作品／版本、接線 key、輪次及對話 epoch；普通「好／開始」聊天不等於拍照授權。
- 桌面與手機共用伺服器上的邀請狀態。稍後只收起該邀請，保留草稿、照片與人工紀錄；重新整理不會使已關閉的邀請復活。
- Start 使用原本 collect-only session 與 wiring review；Continue 保留既有輪次、照片及人工確認。提醒與開始引導都不會擷取照片、分析圖片或執行 Pi 測試。
- 權限分開：無法開始時仍可依 `can_dismiss` 按稍後。連點共用單一 flight；失敗可明確重試，晚到結果不能更新新作品或新邀請。
- 手機沿用既有選用照片／裁切／分析能力；實際接線人工確認與改線維持既有桌面流程。

## 本輪有限驗證

測試次數計入失敗與重跑，限制為本輪累計 100 次以內；未執行完整 suites。

| 類別 | 執行次數 | 驗證範圍 |
|---|---:|---|
| 桌面共享 action／adoption | 12 | 精確收據、Late guard、稍後、續接及不重置人工紀錄；12 passed |
| 手機 Node | 21 | 新 8 項、既有 5 項、修正後重跑新 8 項；全部 passed |
| 手機隔離瀏覽器 | 8 | Start、Later、Continue、跨裝置收起、連點、晚到回覆、失敗重試及舊邀請；8 passed |
| 後端 pytest | 32 | 17 個不同案例已有通過紀錄；累計 26 passed、6 次早期失敗已修正 |

累計 **73 次**，共 **50 個不同檢查項目**；早期失敗及重跑均已計入，沒有用「73 passed」取代實際紀錄。後端包含既有獨立 debug conversation 的正確連結、Start／Continue 授權、保存原 review、晚到 context、並行 Start 及普通聊天不授權等情境。

瀏覽器使用真實 MobileWebApp／ChatView／useMobileBrowser 與 loopback 模擬 API。390 × 844 深／淺色畫面無橫向溢出或 JavaScript 錯誤，按鈕高度 48px。相機開啟、模型與硬體操作均為 0。最後 Later 權限分離為 TSX 一行調整，由最終 TypeScript／Vite build 檢查；未再次執行瀏覽器流程。

TypeScript／Vite build 與 i18n parity（761 keys）通過。這些結果是軟體與模擬 API 驗證，沒有宣稱真實手機拍照、雲端辨識品質或 GPIO／電氣接線已驗證。

證據：[8 個手機流程](../../runs/mobile-test-help-qa-20261004/qa-summary.json)、[手機訊息內按鈕](../../runs/mobile-test-help-qa-20261004/mobile-dark-inline-invitation.png)、[第一張照片引導](../../runs/mobile-test-help-qa-20261004/mobile-start-first-photo.png)。

## 正式程式載入

使用原本 `scripts/start-mobile-prototype.ps1` 重啟 8100 後端，保留原 HTTPS 手機入口。正式 `/`、`/mobile` 與新版 `MobileWebApp-BH5mT3Sl.js` 回 200；OpenAPI 已包含共享 test-help route 與手機 invitation schema。HTTPS `/mobile` 及新版 JS 也回 200，使用既有 rootCA 驗證 TLS，沒有略過憑證驗證。

使用者既有桌面頁面已重新整理。重啟前的 active debug case 依既有規則成為唯讀歷史、顯示「重啟後的舊紀錄」；沒有自動停止 Pi 工作或接續測試。舊訊息不會被改寫成新邀請，帶有新 offer 的提醒才會提供按鈕。手機重新整理即可載入新版介面。
