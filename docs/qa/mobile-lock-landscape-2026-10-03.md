# 手機 Locked 與橫向取景 QA — 2026-10-03

## 本次修改

- 手機專用 `mobile_stability` 使用原像素、Pi 固定基準對角線，統一橫／直向位移容許量；同時檢查大小、角度、凸四角及方向順序。
- 最近 1.4 秒至少三張合格影格、跨度至少一秒；合格間隔最多 0.7 秒。單張失效立即禁止新的 GPIO 拍照請求，有限保留候選；連續失效、移動、逾期、作品或世代切換則清除。既有正式照片 handoff 和重試契約保留。
- 找 Pi 與找指定目標各有單一原因；原本的完整入鏡、距離、清晰度及曝光檢查保留。
- 橫向取景使用左影片／右控制區，停止與導覽固定可達，設定在右側獨立捲動。直向保持簡潔版面，同一個原生 video／相機 track 等比例完整顯示。
- 未修改 Webcam 的參數、校正、追蹤、模型或正式照片 GPIO 演算法。

## 自動測試

- 後端：152 passed（`test_mobile`、`test_mobile_recognition`、`test_mobile_photo_analyzer`、`test_mobile_rtc`、`test_mobile_stream_capture`、`test_mobile_api`、`test_mobile_without_webcam`、`test_phone_live_source`）。涵蓋 90 度同構圖等價、平移／旋轉／尺度、固定基準防慢漂移、反向角點排列、短暫漏失／模糊、過期、序號／來源／作品隔離及正式照片流程。
- 前端：150 passed（`mobile`、`mobile_browser`、`mobile_web`、`mobile_capture`、`phone_live_source`、`mobile_recognition`）。保留雙拍照、原始 JPEG 尺寸、取景新鮮度、上下文與 single-flight，並驗證具體提示及過期提示優先順序。
- TypeScript、Vite production build 與 761 個語系鍵檢查通過。既有大型 bundle 提示與 Starlette 測試工具 deprecation warning 不影響以上結果。
- 舊 mobile_recognition 測試改為核對目前主畫面共用 renderer 的 `preview: null` 契約；未為測試恢復已移除的獨立預覽管線。

## 瀏覽器版面與操作

使用 `tools/mobile-capture-preview.mjs` 隔離 fixture；實際 React 元件、手機 hook 和瀏覽器原生影片 track 搭配合成畫面與假 RTC/API。**不是 iPhone 網路 FPS、模型準確率或實體 GPIO 證據。** QA 頁頂部另有 60px 測試列，已計入可用高度。

| Viewport | 影片容器 x/y/寬/高 | 控制區 x | 結果 |
|---|---|---|---|
| 844×390 | 12 / 68 / 537.9 / 314 | 561.9 | 全部四個影像角落可見；header、停止、拍照、導覽不重疊影片 |
| 667×375 | 12 / 68 / 401.3 / 299.3 | 425.3 | 較小橫向也保留全幅；資訊展開後只捲動右欄 |
| 390×844 | 73.4 / 166.3 / 227.9 / 405.1 | 上下配置 | 1080×1920 直向全幅顯示，除錯拍照不需 Locked |

- 展開取景設定與串流資訊後，左側影片尺寸不變；控制區 scrollHeight 713、clientHeight 約 165，停止／導覽仍可達。
- 展開設定及同方向 resize 未重開相機：getUserMedia 1、track.stop 0、generation 1。
- 切換直向後，getUserMedia 2、track.stop 1、generation 2，僅一份未停止的相機來源；實際來源及上傳皆 1080×1920。
- 未 Locked 的直向除錯照片加入聊天草稿，JPEG 1080×1920／quality 0.95，未要求 GPIO ticket、未上傳或呼叫 AI；相機仍持續。
- 另一輪橫向 fixture Locked 後 GPIO 拍照成功，JPEG 1920×1080／quality 0.95；一次 ticket、一次照片上傳，進入同一張照片／腳位檢視，無新增相機。
- 圖片：[橫向取景](mobile-camera-landscape-2026-10-03.png)、[直向取景](mobile-camera-portrait-2026-10-03.png)。記錄：`mobile-camera-layout-fixture-2026-10-03.json`、`mobile-camera-layout-locked-fixture-2026-10-03.json`。

## 收到影格的幾何回放

更新前從既有真實手機串流唯讀取得 55 筆唯一影格 metadata，跨約 22.7 秒、1920×1080、接收 FPS 29.53–30.07。原工作區版本不符，狀態為 `desktop_context_changed`，所以這段不是有效的實機 Locked。

Pi 初始對角線約 602px，中心最大漂移 0.201px、角點 0.314px、旋轉 0.00647 度，尺度比 0.99995–1.00045。新幾何比較 55/55 通過，僅依幾何候選回放 52 張滿足 hold。這支持初始門檻能容忍此段近乎靜止資料，不能校準移動場景或證明模型／GPIO 精度；metadata 可能已由主追蹤器平滑。

## 未完成的實機範圍

新版 iPhone Safari 直／橫向鎖定成功率、移動／遮擋恢復、實際轉向與瀏海安全區尚需重新配對後實拍。正式照片的 GPIO 物理對位亦未因這些軟體測試而完成驗證。本次 UI 及穩定判斷未改 WebRTC 編碼／串流排程，不以 fixture FPS 宣稱新版實測效能。

## 已載入目前服務

前端 build 已由原 8443 gateway 提供，使用既有公開 CA 驗證 TLS，`/mobile` 與新版 JS／CSS 均回 200。唯一 8100 後端透過原 supervisor 重載手機判斷；16:01:42 的 `unexpected_exit` 記錄是本次受控停止載入程式，不是這輪實測觀察到的崩潰。重新啟動後 Pi／HC／TFT 均回報 `actual_backend=cuda`、`preprocessing_backend=cuda`、available=true、fallback_reason=null 且有實際推論計數。

重載後原 Webcam 來源回報 ready=true、error=null，未修改其設定；目前仍只有一個 8100 listener 與原 8443 gateway。手機配對保存在執行階段，因此已在桌面開啟新的配對 QR；手機需重新連接再測新版。
