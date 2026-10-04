# 手機照片訊息 HTTP 500 修正 — 2026-10-04

## 原因與修正

截圖三張附件均顯示 100%，待送訊息沒有文字。手機前端允許只送附件，`MessageBody.text` 預設空字，但 `MobileService.send` 直接把空字傳入要求非空文字的 `SendRequest.model_validate()`；驗證例外未轉成 HTTP 客戶端錯誤，形成 500。

新增隔離 HTTP 回歸測試後，修正前確實重現單張／三張照片無文字送出 HTTP 500；空白且沒有附件也回 500。修正後，有明確媒體且無文字時，後端依作品語言補上「分析影像、說明可見零件與接線」的提問。無文字、無明確媒體時回 422。既有文字、媒體 ID、上下文及 request ID 沿用原值；舊手機待送訊息不需改寫 payload 即可重試。

改動範圍：backend/app/mobile.py 與 backend/tests/test_mobile_api.py。未修改前端、Webcam、模型或串流設定。

## 驗證

- 修正前：三個新 HTTP 案例失敗，均實際收到 500。
- 修正後：mobile_api、mobile、assistant_media、assistant 共 97 項測試通過。
- 使用實際 MobileService、MobileAssets、AssistantService 與暫存照片，AI bridge 使用 fake：三張圖皆傳入，手機與桌面讀到同一保存回覆，相同 request ID 重試只有一個 job／一次 bridge 呼叫。
- 正式 8443 使用既有 rootCA 驗證 TLS；`/mobile` 回 200，空白無媒體訊息穿過 HTTPS gateway 回 422 與 mobile_message_requires_text_or_media。測試工作階段已關閉，未呼叫正式 AI。紀錄：backend/runs/mobile-photo-only-fix-live-2026-10-04.json。
- 手機 frontend 已上傳 asset 與原 request/context ID 會在失敗後保存；重試有 asset 時跳過重傳。仍需使用者重新配對後在實際 iPhone 上按待送訊息「重試」，確認正式 AI 回覆。

## 服務狀態與限制

15:10:43 受控停止舊後端以載入修正。Supervisor 恢復後，15:11:59 又發生一筆來源未確認的 -1 退出，15:12:08 自動恢復；這不是已重現的空文字驗證錯誤，亦不能宣稱本修正已解決後端退出問題。目前後端 PID 70272、gateway PID 62564，HTTP／HTTPS 已確認可用。聊天、上傳附件與桌面上下文保留；後端工作階段因重載需要重新配對。

原後端／gateway logs 沒有本次訊息錯誤 stack；已記錄的 WinError10054、CancelledError 和 gateway WebSocket 模組警告不作為本次 500 的原因。

另以截圖中的三個檔名逐一確認上傳資產：三份分析照片均存在且為 1920×1080。未知退出已做窄範圍脚本與 Windows 事件審查，仍無可確認終止來源；目前 attempt 3 為原 supervisor 最後一次自動恢復，本修正未改 supervisor 政策。
