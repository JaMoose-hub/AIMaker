# HC-SR04+：3.3V 供電配置

更新日期：2026-09-17。此為軟體接線配置，尚未進行實體供電／ECHO 電壓或測距驗證。

## 適用版本

依 [使用者提供的商品](https://shop.playrobot.com/products/hc-sr04-3v3-5v-ultrasonic)，
商品描述為 HC-SR04+ 寬電壓版本，列出 3V/5V 操作、與 3.3V MCU 直接連接。
頁面未列出 ECHO 高準位的獨立電壓數值；直接接線配置的前提是確認實物為此版本、
在 3.3V 供電下 ECHO 也相容 3.3V GPIO。不可套用到標準 5V HC-SR04，亦不可維持 5V 供電卻直接移除分壓。

## 腳位

| 模組端 | Pi 5 實體腳位 | 單排位置（由遠離 USB-A／網路孔的一端數） |
| --- | --- | --- |
| VCC | Pin 1 · 3.3V | 內排第 1 支 |
| TRIG | Pin 11 · GPIO17 | 內排第 6 支 |
| ECHO | Pin 12 · GPIO18 | 外排第 6 支 |
| GND | Pin 6 · GND | 外排第 3 支 |

內排靠板內側，外排靠板邊。HC-SR04+ 單模組需要 4 條杜邦線；
不需原先 330Ω、470Ω 分壓電阻或分壓麵包板。TFT 供電／背光規格待確認的狀態不變。

## 軟體與舊作品

- `profiles/component-catalog.json` v2 為作品接線圖、步驟、BOM、生成程式共用來源。
- 選用 `profiles/components/hc-sr04/variants/plus-3v3.json` 電氣規格；原標準 5V `component.json` 保留，視覺模型及腳位幾何未變。
- 開啟頁面時，先將舊草稿完整備份到瀏覽器 localStorage 的 `boardvision.maker.v1.before-hcsr04-3v3`，才送本機 API 轉換；失敗不覆寫原始草稿。
- 保留作品 ID、原始對話、圖片及未改接法的人工紀錄；重建材料、接線與 profile 雜湊。VCC、ECHO 舊完成紀錄清除，硬體測試結果清除，不冒充新接法已通過。
- 未手改的生成程式同步更新；手動改過的程式保留在編輯器（完整舊草稿亦有備份），部署前請自行檢查。
- 不觸發 AI 生成、SSH、Pi 部署或上電。不推送 Git。

## 驗證

自動測試涵蓋 3.3V 電源軌、直接 ECHO、原標準 5V ECHO 拒絕直接連接、
新舊 profile 雜湊、草稿備份、轉換失敗保留、確認紀錄失效及前端布局。
這些是軟體測試，不代表實體硬體已驗證。

2026-09-17 檢查結果：

- 相關後端測試 144 項通過（`test_maker`、`test_maker_workflow`、`test_retired_components`、`test_hcsr04_3v3`、`test_pi_deploy`、`test_wiring_rules`、`test_cloud_wiring`，排除 6 個 HW-123 參數案例）。
- `npm test` 通過：前端 133 項測試、語系檢查與 TypeScript/Vite 建置；包括 VCC 內排第 1 支、ECHO 直接接線的實際引導元件渲染。
- HW-123 的 6 個舊參數案例另跑為 2 通過、4 失敗；以 HEAD 舊 catalog 載入同樣重現 4 個失敗，非本次 3.3V 更新造成，未修改相關辨識程式。
- 實際瀏覽器舊作品由 revision 2 轉成 3，標題及候選作品保留；Blueprint 顯示 VCC → Pin 1 / 3.3V、ECHO → Pin 12 / GPIO18，兩模組材料為 10 條杜邦線，無分壓電阻或必要麵包板。
- 本機服務已重啟；未部署到 Pi，未做實體測距驗收。
- 重啟後 `/api/tracking/frame` 可解碼為 1920×1080 相機畫面，平均灰階亮度 127.5，並非黑畫面；此數值只驗證影像串流，非辨識準確度。
