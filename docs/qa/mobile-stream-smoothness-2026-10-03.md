# 手機同步串流流暢度 — 2026-10-03

## 實機瓶頸

原版本、iPhone Safari 1920×1080、桌面主畫面啟用同影格 GPIO。30 秒量測使用額外唯讀 `/api/tracking/frame` client，會增加 JSON 傳輸負載；未開新相機、模型或寫入影片。以下是收到的影格／同步封包速率，**不是螢幕實際呈現 FPS 或端到端延遲**。

| 指標 | 修改前 |
|---|---:|
| 手機 → FrameBus 實際序號增量 | 30.02 FPS |
| 同影格 JPEG／GPIO 唯一封包 | 18.95 FPS |
| 手機來源 fresh 樣本 | 30/30 |
| 每包處理平均／P95 | 51／63 ms |
| 三物件串行平均總成本 | 39.82 ms |
| 灰階／JPEG 平均 | 3.60／6.94 ms |
| 封包間隔 P95 | 69.66 ms |
| 來源影格年齡 P95 | 110 ms |
| Recovery 搜尋 | 564 張皆為 0 |

原 `processing_ms` 使用 Windows coarse monotonic，子步驟使用 `perf_counter`；新版總時間改用 `perf_counter`，因此毫秒值需考慮舊時鐘量化。來源 30 FPS 與同步輸出約 19 FPS 的差異支持三物件串行追蹤是瓶頸。桌面另兩次唯讀 DOM 檢查顯示 hook 23／24 FPS，這是 JPEG decode 完成與 React 提交計數，不是 browser presented FPS。

完整原始 metadata：`backend/runs/mobile-smoothness-before.json`。未保存 JPEG payload。第二輪補充量測遇到後端退出／工作階段失效，未形成有效比較資料。

## 修改

- 僅 `state.config.camera.source == 'phone'` 使用最多三個物件追蹤工作。每一個物件持有自己的 MotionTrack、BodyTrack、prediction；所有 source gray 先由影格 owner 共用準備，再以唯讀 cache 供工作讀取。
- 每張只提交一批工作、等待所有工作完成；不堆積影格。保持原 rotating recovery 優先、每張最多一次 recovery，以及原模型、門檻、解析度、JPEG 品質和幾何演算法。
- 三組結果完成後才做 identity arbitration，輸出同一個 FrameSlot 的 JPEG 與 GPIO。Webcam／Eye 使用原串行流程；退出手機模式關閉 pool。
- Stop、runtime／source 切換、工作例外及 submit 已排入工作後才拋例外，都先結束原工作；晚到手機封包不能發布。
- 手機同步影格暫時缺失時顯示等待並清除舊 GPIO，不再改開 `/video` 或 `/frame.jpg`，避免在兩種顯示來源間切換。新同步影格自動恢復，無需重開手機相機。
- 新增 `tracking_execution`、`timing_ms.source_gray`／`objects_wall`；不增加取景頁資訊。
- 第一輪並行後，20 秒僅起終兩次讀取的 producer counter 仍為 24.26 FPS，來源 30.05 FPS，每張處理起終 17.34／16.91 ms，僅四張超過處理預算。確認最後的 Windows `Event.wait` 節奏仍在掉幀；手機改為既有 `wait_eye_deadline` 的 QPC deadline／短睡眠，仍保留顯示 FPS 上限，不修改全域 timer period。Webcam／Eye 等待方式維持原分支。

## 軟體驗證

- 121 項後端相關測試合併通過：phone_live_source、phone_motion_parallel、motion_tracking、motion_rebase、body_tracking、camera_tracking_reset、eye_tracking_api、eye_timing。
- 其中 12 項新增 phone_motion_parallel 回歸驗證真正 OpenCV 光流的串行／並行移動及遮擋結果一致、三工作重疊、共用 seed gray 僅 owner 計算一次、recovery 優先、公平與預算、例外／stop／reset／未回傳 Future 清理、JPEG 期間 source／revision／stop 變化不發布，以及手機 deadline／serial 等待／停止後不繼續取 frame。
- 114 項前端相關測試通過：phone_live_source、realtime_frame、display_mode、mobile_browser、mobile_capture、mobile_web、mobile_recognition。
- TypeScript、Vite production build、761 個 i18n key 檢查通過。
- 額外舊 `glasses.test.mjs` 檢查有三項預期已落後於既有 source identity／LiveCameraOverlay 實作；本輪未修改那些產品分支或放寬 Eye 測試。以上不宣稱全專案測試通過。

## 部署與實機結果

第一次部署「三物件並行」後，正式 iPhone 取景 30 秒：來源 30.01 FPS、30/30 fresh、727 個唯一同步封包、HTTP 24.23 FPS、每張處理平均 20.69／P95 28.33 ms、來源年齡平均 47.27／P95 78 ms。727/727 JPEG／Pi／HC／TFT frame_id 一致，Pi 725、HC 723、TFT 722 個樣本為 locked；狀態不等於 GPIO 物理精度驗證。桌面 hook 當時顯示 26 FPS。這段期間曾從照片檢視切回直播，封包間隔最大 577 ms，因此也不宣稱完全無卡頓。原始資料：`backend/runs/mobile-smoothness-after.json`；精簡摘要：`mobile-smoothness-after-summary-2026-10-03.json`。

再用只有起終兩次 HTTP 讀取的 20.04 秒量測：motion producer 計數 +486，即 24.26 FPS；FrameBus +602，即 30.05 FPS；Phone received +601，即 30.00 FPS，世代／runtime 不變。這排除了高頻額外讀取 client 是剩餘速率損失的唯一原因；精確 deadline 修改後需再確認。

16:15:23 舊後端非預期退出（-1／0xFFFFFFFF），stderr 僅有 CuPy CUDA path 警告，沒有已確認的退出原因；原 supervisor 自動恢復。這個事件不能宣稱已由本次 FPS 修改修復。

16:20 受控重載完整新版，重新啟動原 bounded supervisor；保留 8443 gateway 和既有 CA。確認 Pi 5／HC-SR04／TFT 的 `actual_backend=cuda`、`preprocessing_backend=cuda`、available=true、fallback_reason=null，並有實際推論計數。這是模型後端狀態，不是每個 ONNX operator 的 GPU audit；光流仍使用 OpenCV CPU。

16:29 為載入最後的精確 deadline 修改，受控停止第一個後端程序；supervisor 將這次人工停止記為 unexpected_exit，並自動啟動 attempt 1。這次有已知人工原因，不能與 16:15 的未知退出混為一談。最後正式後端為 PID 87688，8443 gateway 仍為 PID 62564；16:36 再確認兩個服務皆監聽。

最後版 iPhone 重新連接後的 30.026 秒量測：收到 857 個唯一同步封包，即 **28.56 FPS**；手機來源實際 **29.98 FPS**，30/30 fresh、零 HTTP 錯誤，全部為 1920×1080。857/857 JPEG／追蹤 frame_id 一致；每張處理平均 23.53／P95 38.24 ms，來源影格年齡平均 50.44／P95 78 ms。桌面一次 hook 讀值為 29 FPS。原始資料：`backend/runs/mobile-smoothness-final.json`。

| 同場景量測 | 修改前 | 三物件並行 | 並行＋精確 deadline |
|---|---:|---:|---:|
| 手機來源 | 30.02 FPS | 30.01 FPS | 29.98 FPS |
| 唯一同步封包 | 18.95 FPS | 24.23 FPS | 28.56 FPS |
| 每張處理平均 | 51 ms | 20.69 ms | 23.53 ms |
| 來源影格年齡 P95 | 110 ms | 78 ms | 78 ms |

**後段負載增加時仍會掉幀，不能宣稱穩定 30 FPS。** 16:33:29–16:33:49 再使用只有起終兩次 tracking／status 讀取的 20.073 秒 producer 量測：同步計數 +469，即 **23.36 FPS**；FrameBus／phone received 各 +605，約 30.14 FPS（端點 snapshot 取樣差）。兩端皆為同一 session、generation 1、runtime revision 2、active／fresh、phone_parallel。這段超過處理預算的計數 +432，起終處理 48.63／34.59 ms，objects_wall 33.82／18.87 ms；處理成本已高於前段，不支持把後段掉幀繼續歸因於等待計時。資料：`backend/runs/mobile-smoothness-final-producer.json`。只有端點 freshness 不代表中間每一張都已驗證。

16:36 模型狀態再次確認 Pi 5／HC-SR04／TFT 皆 actual_backend=cuda、preprocessing_backend=cuda、fallback_reason=null，推論計數分別為 6193／2827／1606；追蹤光流仍在 CPU。正式頁面切回即時畫面，確認實際手機影像、Pi GPIO 與 HC Pin 可呈現。截圖：`mobile-smoothness-final-2026-10-03.png`；精簡結果：`mobile-smoothness-final-summary-2026-10-03.json`。

本輪完成手機專用優化、部署與橫向短程實測，並保留 Webcam 原執行分支及設定。剩餘瓶頸是負載變化下的 CPU 追蹤／影像處理成本；本次沒有量測螢幕實際呈現 FPS 或完整端到端延遲，也尚未完成最後版本的直向、受控移動和長測。不能以設定 30 FPS、接收 30 FPS 或一次 hook 讀值宣稱持續同步顯示已達 30 FPS；此輪亦不是 GPIO 物理精度或電氣驗證。
