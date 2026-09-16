# 接線引導 Profile

Board Vision 有兩種不同用途的 Profile：

- 板卡視覺 Profile：`profiles/boards/<board-id>/`，決定偵測模型、參考影像、板型幾何與 Pin 座標；在後端啟動時選定。
- 接線引導 Profile：教學用 JSON，只決定步驟文字及「控制器 Pin → Sensor Pin」對應，不會切換偵測模型。

## Pi 5 三種零件逐線引導

Pi 5 模式按「顯示接線引導」，選擇 HC-SR04、HW-123 或 MRD-TF240 TFT。
這是內建的**人工確認教學**，不是既有光敏 JSON 匯入格式的擴充，也不是自動接線驗證。

1. 確認 Pi、模組與外接電源均已斷電；完成該零件的必要條件。
2. Pi 與選定零件必須穩定鎖定。接線卡片以半透明背景浮在 webcam 下方偏中間，留出中央操作區，展開／收合不改變影像尺寸。接線中以零件名稱取代不可操作的選單，寬視窗並排顯示本步說明與腳位對應；必要警告仍保留。窄視窗維持下方浮動，內容過長時在卡片內捲動。可收合卡片查看被遮住的 GPIO，步驟與 AR 目標仍保留。
3. 每次只高亮該零件的目標 Pin 與 Pi 目標 Pin。直連步驟畫示意線，其他元件淡化。
4. 自行核對後按「我已接好／下一步」；「上一步」會撤銷該步及後續的人工確認。
5. 結束或中止後查看總覽。所有完成項目只標示「人工已確認」，不代表導通、電阻值、電壓或功能正常。

收合面板不停止引導；重新整理會清除新引導的人工紀錄。進行中不能直接切換零件；先結束或回總覽。
定位短暫離開 locked 時先套用約 0.9 秒遲滯，避免按鈕與文字逐幀閃動；若仍未恢復，AR 目標與示意線會固定在最後可信位置並降低透明度，最長保留約 3.5 秒。超過保留時間、目標從未成功鎖定或連線中斷過久時才隱藏精準標記；定位恢復後沿用原步驟。暫存位置只是顯示連續性，不是新的辨識或接線證據。

| 零件 | 依序接線（Pin 為 Pi 5 實體腳號） | 限制 |
| --- | --- | --- |
| HC-SR04 | GND→Pin 6；TRIG→GPIO17 / Pin 11；ECHO→分壓節點→GPIO18 / Pin 12；VCC→5V / Pin 2 | ECHO 不可直連 GPIO；電源線最後接，接線全程斷電 |
| HW-123 | GND→Pin 9；SDA→GPIO2 / Pin 3；SCL→GPIO3 / Pin 5；VCC→3.3V / Pin 1 | 確認 AD0 依模組規格固定電位；本次不用 XDA、XCL、INT |
| MRD-TF240-8P-CS | GND→Pin 20；SCL→GPIO11 / Pin 23；SDA→GPIO10 / Pin 19；CS→GPIO8 / Pin 24；RES→GPIO25 / Pin 22；DC→GPIO24 / Pin 18 | 訊號線限定；此模組 SCL/SDA 是 SPI，不是 HW-123 的 I²C |

HC-SR04 保護接法：ECHO 經 330Ω 到節點，節點接 GPIO18，並經 470Ω 到共地 GND。介面刻意不畫 ECHO→GPIO18 的直連 AR 線；分壓電阻值與共地仍須人工確認。
這組分壓方式可參考 [GPIO Zero 的 DistanceSensor 說明](https://gpiozero.readthedocs.io/en/stable/api_input.html#distancesensor-hc-sr04)。Pi GPIO 映射可參考 [Raspberry Pi 官方說明](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#gpio)。

TFT 的 VCC、BLK、供電電流與精確驅動晶片尚未核實，因此**不指定供電腳位、不高亮這兩條線，也不允許視為可以上電**。六條訊號線全部人工確認後，總覽仍列出「待規格確認／禁止上電」。

### 實作邊界

- 三套定義與 reducer：`frontend/src/lib/componentWiringGuides.ts`；面板：`frontend/src/components/WiringGuidePanel.tsx`。
- 以 `component_id + pin_id` 選取對象，不使用全域 primary 元件猜測同名的 GND、VCC、SDA 等腳位。
- 新人工教學不送出後端的單一直連 step，避免把 ECHO 分壓網路假裝成直連；開始時只清除既有 legacy step/evidence。人工紀錄只存在當頁記憶體。
- 不自動啟動 VLM、Serial 或 GPIO，不開啟 Pi 上的 I²C/SPI，也不執行功能測試。既有光敏進階檢查仍走原本後端。
- 目前以一般 webcam 介面為交付範圍；透明眼鏡功能暫不繼續開發或實測。

### 驗證方式

前端在 `frontend` 執行 `npm test`，包含 i18n、逐線 reducer／安全映射／定位門檻測試與 production build。
後端在 `backend` 執行 `.\.venv\Scripts\python.exe -m pytest tests -q`。

完整 UI 操作可用獨立合成 fixture，不占用 webcam 或載入模型：

```powershell
# cwd: board-vision/backend
.\.venv\Scripts\python.exe -m tests.wiring_guide_preview
# 開啟 http://127.0.0.1:18761/；只用於合成 UI 測試
```

此 fixture 的 `/__test/scenario/locked`、`stale`、`missing`、`silent` 接受 POST，僅用於測試鎖定／凍結／HC-SR04 遺失／零件停止更新；正式程式不包含這些測試端點。
合成測試的人工確認不是實體接線證據。實際分壓電路與各零件通電功能仍需人工實測。

## 原有光敏引導／JSON 匯入

目前啟動 Pi 5 控制器模式：

```powershell
.\scripts\camera-yolo.ps1 -Board raspberry-pi-5 -DeviceIndex 1 -CaptureApi dshow
```

頁面中央上方的「顯示接線引導」可展開／收合面板。收合只隱藏面板，不會清除正在進行的步驟或 Pin 高亮。

Pi 5 先按「原有光敏電阻引導」；UNO Q 保留原介面。在引導尚未開始時，可從「接線 Profile」選擇內建或已匯入的 Profile；按「匯入 Profile」可載入 JSON。匯入內容必須：

- `board_id` 與目前後端的板卡 Profile 相同；
- `board_pin_id` 存在於目前板卡 Profile；
- 元件為目前支援的 `photoresistor-module`，元件腳位為 `VCC`、`GND` 或 `AO`；
- 符合 [wiring-guide-profile.schema.json](../schemas/wiring-guide-profile.schema.json)。

Pi 5 範例可見 [wiring-guide-profile.pi5.json](../frontend/public/examples/wiring-guide-profile.pi5.json)。匯入 Profile 只保存在目前瀏覽器，不會覆寫專案中的板卡視覺資料。

## Pi 5 光敏模組限制

內建 Pi 5 流程為：

1. 實體 Pin 1（3.3V）→ Sensor VCC
2. 實體 Pin 6（GND）→ Sensor GND
3. 實體 Pin 11（GPIO17）→ Sensor AO

第三步只能把 0–3.3V 的 AO 訊號當作 GPIO HIGH／LOW 門檻，不是類比量測。要取得連續光照數值，需加入 ADS1115、MCP3008 等外接 ADC，並建立包含該硬體的接線與電氣驗證流程。
