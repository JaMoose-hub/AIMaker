# 測試異常後的簡短接線檢查邀請

本輪將「請 AI 幫忙」改為具體下一步。沿用已有測試異常的顯示条件；按下後，助手直接根據測試記錄發出簡短提醒，不再等待模型產生一般性分析。

例如：「MRD-TFT240 的畫面或顏色不正常。要拍照檢查接線嗎？我會帶你拍 Pi 兩側和 MRD-TFT240 接頭，逐條核對。」

- 桌面直接在這則 Tinkro AI 提醒內提供「拍照檢查／稍後」。明確開始才使用既有 collect-only session 與 wiring_review start，展開 Pi 第一側的第一問。
- 已有相同零件的有效核對時，提供「繼續照片核對」，只展開該紀錄，保留照片、觀察、人工確認與版本。
- 缺套件、連線失敗等明確環境或測試操作問題，顯示該問題的具體處理步驟，不提供拍照邀請。
- 稍後只關閉當前邀請。照片、模型、功能測試、改線或接線確認都不由這個提醒自動執行。
- JSON／原始 log 不進入公開訊息或草稿。提醒以現有 assistant import 存入共用歷史，沒有偽造照片、session 或 evidence 引用。

邀請綁定作品、版本、接線 key、輪次與對話 epoch。App 另外訂閱已有共用 componentTestStore，比對該零件的 run／outcome／失效狀態與最新 test job；同接線重測、新排隊測試或通過結果會使舊 CTA 失效。其他零件與一般 telemetry 更新不會替換來源。發送完成後再核對一次来源，晚到結果不能重新展開舊邀請。聊天文字仍保留為歷史。

相同問題的提醒去重；重複按 Help 會定位原本的短訊息，沒有新增一段無關回覆。明確操作才恢復對話跟隨；正常閱讀歷史與後續新訊息保持既有行為。邀請按鈕為 44px。

訊息內操作使用原有 AiDebugPanel 的 React Portal；同一組開始／稍後／續接處理不會在工具區另顯示一份。UnifiedAssistant 只為本輪、本對話 epoch、未封存的 legacy-debug 助手提醒提供 host；App 同時綁定邀請 ID 與伺服器訊息 ID。Host 尚未載入、移除、邀請失效或切至 Demo／設計／展示時，不顯示可執行的邀請。

重複 Help 以既有 import_key 收據找回確切訊息，不依文字相同來選擇訊息。已去重的提醒若不在最新 50 則內，先沿既有 before／limit 分頁載入，保留歷史順序與最新訊息，再發布操作按鈕；沒有找到收據時提供可重試錯誤。分頁期間清除、換作品／版本、改程式、改輪次或有其他模型任務，都不接受過期結果。

## 驗證

- 前端助手、提醒、逐線／拍照核對、debug session、接線重啟與執行管理相關測試：204 passed，含 Python 中文／換行收據契約、170 則跨兩頁恢復、同文不同問題、過期分頁與游標不前進等情境。
- 後端 assistant／手機公開歷史契約：前一輪 27 passed；本輪沒有修改 Production backend。
- TypeScript／Vite build 與 i18n parity（761 keys）通過。
- 本輪隔離真瀏覽器／network：12 項檢查通過，包含精確訊息內按鈕、工具區無重複、Start／Later／Continue、44px、清除／新 epoch、同文不同測試與重新整理後追回最新 50 則以外的提醒。見 [訊息內按鈕 QA](../../runs/test-help-inline-actions-qa-20261004/README.md)。使用真實元件與 hook、模擬 API；沒有渲染完整 Production App。
- 前一輪隔離真瀏覽器／network 紀錄：14 項檢查通過，包含 Start、Later、Continue、手機共享短訊息、草稿／人工確認保留、44px 按鈕與重複 Help 定位。此紀錄的畫面為按鈕移入訊息前的版型。
- [瀏覽器 QA 詳細紀錄](../../runs/test-help-invitation-qa-20261004/README.md)。測試 fixture 使用真實元件與 hook、模擬 API，並未操作完整 production App。App 的測試來源 guard 以純函式測試與程式審查驗證。

以上為桌面訊息內操作完成時的驗證紀錄。後續手機也已加入初始 Start／Later／Continue，並新增持久化共享 offer 與共用 action handler；最新驗證及本輪 100 次以內的測試預算見 [手機邀請 QA](mobile-test-help-20261004.md)。普通「好／開始」聊天文字仍不作為拍照授權。

所有驗證均為軟體與模擬 API；沒有呼叫雲端模型、擷取實際相機照片或操作 Pi／硬體。既有使用者對話與確認紀錄未重設。

完成建置後，正式 `http://127.0.0.1:8100/` 與新版 `/assets/index-5H9zYHTD.js` 均回 200；使用者原桌面頁面已重新載入。此次為前端更新，保留既有後端與手機 HTTPS 服務。
