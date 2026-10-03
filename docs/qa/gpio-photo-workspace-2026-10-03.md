# 共用 GPIO 照片工作區 QA

2026-10-03。本輪範圍是 02 的影像切換／照片共用，不改手機橫向輸出、定位算法、Pi、實體接線或原 AI 除錯流程。

## 已交付

- 工具列「Webcam／手機取景／GPIO 照片」，相機工具只在 Webcam 畫面提供；移除「照片接線 POC」入口，保留其元件／服务。
- 手機串流在主畫面；手機來源擷取後轉入共用照片主畫面，不另開照片浮窗。
- Webcam 新增明確 GPIO 單次擷取：start → capture → finish；成功或擷取失敗都嘗試恢復連續辨識。恢復失敗保留照片、阻擋再擷取並提供明確恢復操作。雙擊去重；晚到的 session ID 仍會釋放。
- 已保存照片可按來源切換；接線步驟只匹配照片中完全相同的 wire/component/endpoints，不換照片、不推論、不呼叫 AI。
- 圖片載入尺寸、作品 ID／版本、接線輪次、照片定位一致性保護。歷史照片不高亮目前線路，也不當作人工接線確認或電氣／功能通過。
- 深／淺色主題；窄螢幕保留完整照片、聚焦操作及提醒。低高度沿用整頁捲動，不裁掉操作。

## 測試預算與結果

本輪實際自動化測試執行 **78 次（包含重跑）**，涵蓋 **66 個不同案例**。另外 10 組瀏覽器檢查（含初始 fixture 修復、排版重查），合計 88，低於使用者要求的 100 次上限；沒有跑整套數百項測試。

| 執行 | 結果 |
| --- | --- |
| `node --test tools/gpio_photo_workspace.test.mjs tools/maker_stage.test.mjs tools/mobile.test.mjs` | 61：55 通過、6 個 fixture／舊結構斷言失敗 |
| GPIO 新測試重跑 | 9／9 通過；修正測試照片缺少 `outline:null` 及 TSX 測試 loader 的 React 綁定 |
| 三階段聊天單項重跑 | 1／1 通過；Pi 元件已由既有 DeviceConnectionGroups 接管，舊測試改查其 slot |
| 照片尺寸／定位相關既有回歸 | 5／5 通過 |
| 最終 App 共用照片與被動 viewer 各一項 | 2／2 通過 |
| `npm run build` | TypeScript＋Vite 通過；既有大 chunk 提醒仍在 |

紀錄：`gpio-photo-unit.log`、`gpio-photo-unit-recheck.log`、`gpio-photo-stage-recheck.log`、`gpio-photo-geometry-regression.log`、`gpio-photo-final-stage.log`、`gpio-photo-final-viewer.log`、`gpio-photo-build.log`。

## 瀏覽器證據

使用 `tools/gpio-photo-preview.mjs` 的 127.0.0.1:18794 隔離頁面與 `gpio-workspace` 專用瀏覽器 session。fixture 完全不代理請求；相機／RTC／照片座標均為合成資料。首輪 fixture 模型少了 `excluded_efforts`，造成空白頁，補齐 mock 契約後修復；不是 production 程式放寬驗證。

- 1651×871 繁中／深色：Webcam 單次擷取只發出 start、capture、DELETE finish 三個照片請求；手機另用原 stream-capture。兩張照片可切換，無 POC 入口、照片浮窗或手機／照片模式相機工具。
- 改接線步驟 GND → TRIG 時，主照片高亮更新為 GPIO17／Pin 11 與 HC-SR04+ TRIG，照片 API 呼叫仍只有原三次。
- 共用照片單纯選回 Webcam 照片，擷取相關請求數保持 4（Webcam 三次＋手機一次）。
- 1352×871 英文／淺色：文字對比及操作正常；fit 模式 viewport scrollWidth = clientWidth，無額外水平捲動。
- 1352×520：低高度可用整頁捲動到照片提醒與接線操作，沒有水平溢出。
- 390×871 英文／淺色：首次檢查找到父容器只保留 400px、工具列加照片超出裁切；改為工具列自然高度＋照片独立 400px，底部提醒在父容器內，所有聚焦／縮放／返回操作可達。密集物件標題收起，只保留目前兩端標籤。
- 最終模擬手機 viewer 開啟／關閉為 1／1（只關桌面接收影片），不呼叫手機 stop；沒有 AI 生成／照片 checks／部署／Pi 測試请求。runtime errors 為空。

照片：`gpio-photo-initial.png`、`gpio-photo-webcam.png`、`gpio-photo-phone.png`、`gpio-photo-light.png`、`gpio-photo-mobile.png`、`gpio-photo-low-height.png`。最終請求／來源／錯誤摘要在 `gpio-photo-browser-evidence.log`。

## 邊界

沒有實際手機／Webcam 拍照、GPIO 對位精度或恢復推論實機驗收，也沒有 Pi 部署／測試或模型生成。本輪後端程式未修改；照片定位仍由原服務處理。獨立 QA 頁中的可信座標僅為繪圖 fixture，不是照片或硬體準確率。

共用清單為當次 App 開啟期間最多 20 張。手機 session 可在重新整理後被動恢復可查看照片；Webcam 前端清單尚未跨重新整理持久化，服務端仍依原期限保存。新的 GPIO 擷取沒有自動成為 AI 證據，也不取代原 AI「拍攝這一步」及其歷史附件。

使用 React 最佳實務技能維持單一手機控制器、被動照片元件、衍生版本／輪次狀態；使用 agent-browser 與 agent-browser-verify 技能取得真實 DOM、隔離流程及排版證據。既有工作樹變更保留，未提交或推送。
