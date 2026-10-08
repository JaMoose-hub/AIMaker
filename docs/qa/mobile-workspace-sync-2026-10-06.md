# 手機工作區更新提示修正

2026-10-06，台北。範圍：手機／桌面工作區同步；不變更 Webcam 設定、模型、GPIO 定位算法或實體接線。

## 原因與程式證據

原本 `MobileService.publish_context` 對完整桌面 payload 計算 `context_id`，而手機只比較目前 ID 與 `available_context.context_id`。接線步驟、階段、模型偏好、聊天歷史、除錯 runtime ID、部署診斷等皆可能更換完整快照，即使仍為同一作品。

唯讀比對正式服務保存的相鄰 context 檔，找到只變更 `context.debug_context.entry.runId`／`context.guide.inspection` 的組合，也找到只變更語系、目前線路、階段的組合。這證明這些日常更新能觸發提示；沒有宣稱已逐次對照使用者 iPhone 上每次提示的時間。

## 修正契約

- 保留完整、不可變的 `context_id`；另以 `workspace_id` 綁定對話、作品、版本、輪次、服務端 epoch 及程式。
- 同作品的日常快照自動更新 session，保留 RTC generation、相機、照片檢視與線路選擇。真正更換作品／版本／輪次仍須加入新工作區。
- 更新時撤銷舊定位锁與票券；晚到的旧辨識結果不撤銷新快照已取得的鎖。
- 相機重開的有效性以 session／作品綁定判斷，日常更新發生在 stop/start 之間仍能完成重開。
- 手機與桌面以遞增 `context_revision` 拒絕舊 HTTP／WebSocket 回覆。
- 訊息重試保留原 context、request ID、模型、語系、照片與文字；後端重算作品綁定並交由既有 AssistantService 去重。不同作品／版本／輪次／epoch／程式不允許跨範圍重試。
- 過期照片工作顯示明確原因、停用無效重試；使用者可保留原照片為一般聊天附件，再拍攝 GPIO 照片。過期定位不套入新照片。

## 驗證

- 前端七組相關測試：252／252 通過；新增照片復原介面單項：1／1 通過，共 253 個不同案例。
- 後端六組相關測試：246／246 通過，含真實 AssistantService 持久 job 去重測試；模型派送替換為 no-op，不呼叫 AI 或 Pi。
- TypeScript＋Vite 建置通過；既有較大 chunk 提醒仍在。
- 額外後端 API／拍照／零件／接線核對／無 Webcam 回歸：83 通過、1 個既有接線核對測試失敗。後端 agent 在獨立程序還原本次工作區方法後仍重現 fake bridge 2 次、預期 1 次；未降低該測試標準。
- 唯讀審查發現的串流重開、outbox 重試、過期拍照與桌面舊回覆問題皆已補上修正與回歸測試；最後審查無新增阻擋缺陷。

## 套用狀態與限制

前端已產生新的 dist。首次重啟曾被執行工具拒絕（`blocked by policy`）。使用者隨後明確要求重啟，已於 2026-10-06 09:41（台北）停止本案舊 supervisor 與後端程序，並以隱藏視窗啟動新 supervisor（PID 21216）；新後端 PID 38500 為 8100 唯一監聽者，已載入修正。

重啟後 `/api/config`、`/`、`/mobile` 均回應 HTTP 200。既有 HTTPS gateway 保持運行，以既有 rootCA.pem 嚴格驗證 `https://192.168.50.141:8443/mobile`，回應 HTTP 200。兩端須重新整理頁面，若原配對失效則掃新的 QR；上述檢查不代表 iPhone 已重新連線。

本輪未進行 iPhone 實機串流／長測、拍照定位精度或電氣驗收；自動測試與建置不等於實機驗收。
