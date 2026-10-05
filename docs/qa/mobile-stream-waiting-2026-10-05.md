# 手機串流等待提示與部署頁重連

## 本次觀察

8100 後端與 8443 gateway 正常，入口仍為 `https://192.168.50.138:8443`。

- 初次讀取手機 generation 9，收到 1920×1080、約 29.53 FPS，影格年齡 16ms。
- 隨後同工作階段出現 `stream_stopped`，選定來源 generation 9、`ready=false`，同步照片 API 回 204。此時等待提示符合已停止的來源，不能歸因為 IP 錯誤或模型未鎖定。
- 請使用者保持 Safari 串流頁前景後，使用者回覆「手機、筆電都有畫面」。generation 10 的來源與接收端一致，`ready=true`，同步影像 API 回 200、序號遞增。初段速度有波動，之後樣本達 29.53–30 FPS。
- 這段觀察也記錄到 generation 10 的實際影格接收停頓，`video_receive_stalled`、同步影像 204。之後 generation 11 恢復，收到約 30 FPS，選定來源同為 generation 11、`ready=true`。不能把所有等待都當作來源版本錯誤，也未判定此次停頓的網路或手機原因。

手機網頁現有程式在 visibility hidden／pagehide 時停止 publisher，回到前景只重新讀取狀態，不自動重開相機。因此背景、鎖屏或其他 App 切換後，需要在串流頁按「開啟串流」。本次沒有記錄是哪一個事件觸發最初的停止。

## 修正

原本 MobileCompanion 只在 guide 主畫面顯示手機時跟隨新的串流工作階段；部署頁雖已選手機來源，guide 的 `showing` 為 false，會停止跟隨。新增獨立 `phoneSourceSelected`，已選手機且在 guide／deploy 時均跟隨新 session／generation。

保留相機操作中限制、新鮮影格條件及晚到回覆失效判斷。Webcam、照片、設計頁、顯示模式與 demo 不會被此流程自動切換；沒有放寬逾期判斷，也不借用舊影像或 GPIO。

## 驗證與部署

- 110 個相關前端測試通過：mobile 75、phone 6、deployment 4、realtime 25；涵蓋部署頁重連、session 變更、忙碌／逾期影格、來源切換及晚到回覆。
- `npm run build` 通過 TypeScript 與 Vite；保留既有 chunk 大小警告。
- 獨立唯讀審查未發現本次變更的阻擋問題。
- 前端已建置供現有服務提供，桌面頁面需重新整理一次。未重啟後端或 gateway、未修改 Webcam 設定。

實機確認的是手機重新開啟後兩端恢復畫面；部署頁新版再次重開串流的實機驗收尚未完成，現由相關回歸測試覆蓋。本次沒有執行 GPIO 或電氣驗證。
