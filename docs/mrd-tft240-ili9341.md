# MRD_TFT240_8P_CS / ILI9341 接線與首次測試

更新：2026-09-17。範圍：Pi 5、HC-SR04+ 3.3V 版、TFT；不修改視覺模型、追蹤幾何或智慧眼鏡。

## 證據與仍待確認的部分

- 使用者正反面照片確認：MRD_TFT240_8P_CS、ILI9341、240×320、2.4 吋。
- 正面排針順序：GND、VCC、SCL、SDA、RES、DC、CS、BLK。
- 背面可見 U2 與 R1–R6，但照片不能證明 U2 型號、完整背光接法、模組額定電流或最高供電電壓。
- 本版**提供 3.3V 接線方案，不宣稱照片已證明電壓規格**。首次上電前須以此模組的賣場／原廠資料確認 3.3V 相容性。不可改接 5V。
- BLK 留空、不指派 GPIO。是否預設亮背光待實測；若不亮，先取得背光規格，不能只憑相似模組就直接接 GPIO。
- 接線進度、程式執行、實體螢幕成功顯示是三件不同的事。

## 接線方案

板子正面看排針標示；Pi 以實體腳號為準。內排靠板內，外排靠板邊；兩排各自由遠離 USB-A／網路孔的一端起數。

| TFT 腳位 | Pi 實體腳號 | 單排位置 | 功能 |
|---|---|---|---|
| GND | 20 | 外排第 10 支 | GND |
| SCL | 23 | 內排第 12 支 | GPIO11 / SPI0 SCLK |
| SDA | 19 | 內排第 10 支 | GPIO10 / SPI0 MOSI |
| CS | 24 | 外排第 12 支 | GPIO8 / SPI0 CE0 |
| RES | 22 | 外排第 11 支 | GPIO25 |
| DC | 18 | 外排第 9 支 | GPIO24 |
| VCC | 17 | 內排第 9 支 | 3.3V；先核對模組相容性 |
| BLK | 不接 | — | 背光預設狀態待實測 |

SCL / SDA 在此模組是 SPI，不是 I²C。Pi Pin 1 的 3.3V 保留給 HC-SR04+。
接線時關閉電源；接好並核對規格後，再接 Pi USB-C 電源。

## Pi 一次性環境準備

在 Pi 的 `raspi-config → Interface Options → SPI` 啟用 SPI；如系統提示，重新開機。
以部署帳號執行，路徑依部署頁顯示調整：

```sh
sudo apt install python3-venv python3-gpiozero python3-lgpio python3-spidev python3-pil
python3 -m venv --system-site-packages ~/Desktop/Pi_deployer/.venv
~/Desktop/Pi_deployer/.venv/bin/python -m pip install luma.lcd==2.13.0
ls -l /dev/spidev0.0
```

部署帳號須有 GPIO 與 SPI 存取權。程式使用 gpiozero 的 LGPIOFactory，不依賴舊版 RPi.GPIO。
Webcam 主機只產生程式；上述硬體套件是在 Pi 安裝。部署頁不會自行安裝或修改 Pi 系統設定。

## 程式行為與驗收

1. 按「連線 Pi」，再按部署。缺少套件或 SPI 裝置時，部署前檢查會回報；不先中斷原服務。
2. 螢幕先畫紅／綠／藍色塊和 ILI9341、240×320 文字，維持 3 秒。
3. 同時選用 HC-SR04+ 時，顯示真實距離、OK / WARNING；無有效新回波顯示 NO ECHO，不保留舊數值。
4. 只有 TFT 的作品維持測試圖，不假造距離。
5. 目前固定為上述畫面，不代表任意 AI 設計的 UI 都會自動在 TFT 呈現。

現場待驗收（未勾選代表尚未測過）：

- [ ] 此 MRD 模組 3.3V 供電相容性已由規格確認。
- [ ] BLK 留空時背光亮起；若不亮，取得 BLK 電路規格後再安排接法。
- [ ] 三色順序、文字方向與整個畫面正常。紅藍相反時才依實機調整 BGR 設定。
- [ ] 移動物體時距離同步更新；靠近／移遠會切換 WARNING / OK。
- [ ] 無有效回波時螢幕顯示 NO ECHO。

## 實作與驗證範圍

- 接線圖、逐腳引導、生成程式共用 catalog v3；TFT 供電步驟加在最後。
- 舊作品在前端掛載前遷移，備份到 `boardvision.maker.v1.before-tft-ili9341-v3`，不覆蓋舊 HC-SR04+ 升級備份。
- 只保留端點與接法完全相同的人工紀錄；新 VCC 步驟需要使用者確認。
- 自訂程式草稿保留；若仍為舊程式，需要使用者選擇採用新版，不無聲覆蓋。
- 顯示函式庫預設背光腳 GPIO18 已停用，避免和 HC-SR04+ ECHO 衝突。
- 自動化測試涵蓋資料遷移、真實 luma 2.13.0 驅動搭配模擬 SPI、RGB 圖像、過期回波、單螢幕、資源釋放與部署前檢查。**不是實體亮屏或電氣測試。**

參考軟體文件：[luma.lcd ILI9341](https://luma-lcd.readthedocs.io/en/latest/api-documentation.html)、[Raspberry Pi 設定文件](https://www.raspberrypi.com/documentation/computers/configuration.html)。它們不是本 MRD 模組的供電／背光規格證明。
