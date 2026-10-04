# 接線照片分析：文案、計時、文字鎖定與拍照隔離

## 本輪變更

- 拍照邀請改為「這次 HC-SR04+ 沒有讀到距離，要拍 Pi 兩側和感測器接頭，一起檢查接線嗎？」；TFT 使用相應症狀及零件名稱。開始檢查時只新增明確的使用者操作句，不再將 AI 邀請全文複製成使用者話語。保留既有歷史紀錄。
- 共用對話新增 authoritative `wiring_analysis`，涵蓋排隊及實際執行的照片分析，因為這些工作原本存在 debug session 而非 assistant jobs。
- 計時使用後端 enqueue 時間，桌面／手機每秒更新本地顯示；重新整理不重設、不額外呼叫模型。完成／失敗保留固定耗時。沒有有效起始時間的歷史分析不猜測秒數。
- 分析期間停用文字送出，Enter／表單、直接 send／retry 與後端 POST 皆攔截；草稿可繼續編輯。後端回應 `409 wiring_analysis_in_progress`，不寫入新訊息、不建立模型工作。已完成 request 的 idempotent replay 保留。
- 工作區拍照改成 `/api/photo-wiring/snapshot`；不停止／清空即時追蹤，照片的搜尋 cursor 獨立。既有模型與幾何流程保持，單張原图與結果綁定同一影格。詳見 [拍照隔離紀錄](photo-snapshot-live-isolation-20261004.md)。

## 驗證及測試預算

本輪獨立於前一輪已交付的聊天流程驗證，保守計 **53／100 次**：

| 範圍 | 預算計數 | 結果 |
| --- | ---: | --- |
| 後端分析投影、封鎖及邀請角色 | 12 | 初次 6 個 setup error（漏匯入 MODULES，已修）；重跑 6 通過 |
| 手機與邀請文案 | 11 | 6 個不同案例通過；首次測試檔括號錯誤使 5 個手機案例未執行，仍按 5 次占用預算；修正後重跑 |
| 拍照隔離 | 11 | 5 個 Python、6 個 Node 全部通過 |
| 桌面、歷史計時及手機完成耗時 | 8 | 8 次全部通過（包含一個增補斷言後的手機案例重跑） |
| 桌面／390×844 手機 UI | 2 | 兩個隔離情境通過，時計遞增、禁止送出、草稿保留、完成解鎖 |
| 瀏覽器工具設定／讀取失敗後重試 | 4 | 缺少 JS 綁定、舊 tab 不存在、選擇器重複；修正讀取後完成，未觸發產品或模型操作 |
| TypeScript／Vite 建置 | 2 | 通過；第二次包含手機完成耗時補充；現有 bundle size 提示保留 |
| 重啟後 HTTP、HTTPS及正式頁面 | 3 | HTTP 200、以既有 rootCA 驗證 HTTPS 200、正式頁面載入新資源 |

自動化實際有 **31 次案例通過**；預算表也包含 setup error、未開始案例及重跑，不將它們當成功。

UI 使用真實桌面與手機 React 元件，封閉的 loopback 合成資料服務，無 production fallthrough。分析期間桌面按 Enter、手機輸入草稿後按 Enter，服務端沒有收到任何 `/messages` 請求。重新整理桌面仍沿用同一 started_at；完成後兩端恢復送出，草稿保留。增補的手機測試確認歷史計時改為固定 duration，不能重新跑時計。

### 畫面證據

![桌面分析期間計時與停用送出](screenshots/analysis-lock-desktop-20261004.png)

![手機分析期間計時與停用送出](screenshots/analysis-lock-mobile-20261004.png)

## 服務狀態

- 重啟 `scripts/start-mobile-prototype.ps1 -Port 8100 -MaxRestarts 3 -RestartDelaySeconds 2`。
- 新 8100 listener PID `24952`，診斷記錄 `backend/runs/mobile-backend/20261004-200004-3360-events.jsonl`。
- 8443 HTTPS proxy PID `57844` 持續服務。
- 正式桌面及 `https://192.168.50.141:8443/mobile` 皆載入 `/assets/index-CY0CPeGO.js`。
- 最終手機資源 `MobileWebApp-CTggBS14.js`，桌面 `App-BGW5N-r3.js`。

## 實測範圍

測試沒有執行雲端模型、SSH、GPIO 或硬體重測；正常重啟仍啟動原有 Webcam／辨識服務。即時畫面可載入不代表拍照前後 FPS 或辨識準確率已驗證。照片運算仍可能占用 CPU/GPU；本輪修正不必要的停機／追蹤清空，實體相機與手機串流品質仍需另外實測。
