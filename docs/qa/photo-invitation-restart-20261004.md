# 重啟後「拍照檢查」無法按下

## 原因

正式頁面的新拍照邀請仍為有效測試結果，但後端把舊的純照片工作 `paused/backend_restarted` 視為尚有工作需要停止。這同時阻擋 `test_help_start_available()` 的按鈕權限，以及 `DebugSessions.create()` 的實際開始操作；單純解除前端 disabled 無法修正。

現場舊工作為 `purpose=wiring_review`、`phase=backend_restarted`、`model_busy=false`、照片輪次已 stale，沒有 session job/run/trial 識別。

## 修正

共用唯讀判斷 `replaceable_photo_history()`，僅辨識已重啟、無可信可恢復 context、沒有執行或待處理工作的照片歷史。輪詢不會改寫這些紀錄；使用者明確按拍照檢查，且新請求為 collect-only 時，才建立新的工作並把舊工作標記為 superseded。

舊訊息、照片、逐線人工決定仍保留；新照片輪次不承接舊人工確認。功能除錯、issued job/run/trial、待處理模型／取證及實際仍在執行的 Pi 工作保持阻擋。

`_adopt_tests()` 可能只讀引用其他零件已通過的歷史測試；只有既有 `source=existing_component_test`、`evidence_scope=current_configuration_historical_run` 及非空 run_id 的完整引用才視為歷史資料，未知或不完整紀錄保持阻擋。

## 軟體驗證

本次採用真實後端流程與封閉的合成資料，覆蓋桌面、手機的邀請權限 → 開始操作 → 第一側 Pi 拍攝提示；保留舊歷史、阻擋真正的功能工作及模型忙碌。合計 8 次 pytest 項目執行、7 個不同案例、0 失敗；歷史引用補充後重跑一個既有案例。

Python 編譯及相關 diff check 通過。未修改前端；沿用上一輪已建置且確認的資源 `index-CY0CPeGO.js`。

正式程式已重啟，8100 listener PID `38584`，診斷 `backend/runs/mobile-backend/20261004-202500-2883-events.jsonl`。HTTP 根頁及以既有 rootCA 驗證的手機 HTTPS 均 200。

正式頁面重載後舊邀請失效，按「請 AI 幫忙」恢復目前失敗結果的邀請；「拍照檢查」已啟用。實際按一次後出現 Pi 第一側近照提示及「拍攝 Pi 第一側」按鈕，建立全新的 collecting 工作。沒有按拍攝、沒有開始分析或執行硬體測試。

![正式頁面已進入第一張拍照引導](screenshots/photo-invitation-working-20261004.png)

本次按保守計數 13 次（8 pytest、2 HTTP/HTTPS、2 正式頁面驗證嘗試包含一次舊邀請找不到、1 編譯），仍在 100 次以內。這些為軟體與入口操作證據，未驗證線路或電氣連通。
