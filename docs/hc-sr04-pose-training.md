# HC-SR04 Pose 與麵包板資料流程

## 1. 固定的 8 點定義

以超音波圓筒面向鏡頭、排針朝下時的實體方向為準。畫面旋轉後名稱不變：

1. `pcb_TL`：綠色 PCB 左上角
2. `pcb_TR`：綠色 PCB 右上角
3. `pcb_BR`：綠色 PCB 右下角
4. `pcb_BL`：綠色 PCB 左下角
5. `pin_VCC`：VCC 排針在 PCB 邊緣的根部中心
6. `pin_TRIG`：TRIG 排針在 PCB 邊緣的根部中心
7. `pin_ECHO`：ECHO 排針在 PCB 邊緣的根部中心
8. `pin_GND`：GND 排針在 PCB 邊緣的根部中心

Pin 點永遠標在同一個實體根部，不標麵包板孔。排針被麵包板、手或線遮住時，估計根部位置並設成「遮擋（v=1）」；真的無法合理推定時跳過該幀，不要用錯誤位置完成標註。

## 2. 拍攝批次

每支影片只能匯入一個 split，不能把同一影片的相鄰幀分散到 train、val、test。

| 批次 | Split | 建議內容 | 目標張數 |
|---|---|---|---:|
| T1 | train | 桌面平放、360° 旋轉、遠近變化 | 85 |
| T2 | train | 手拿、接線、局部遮擋、25–45° 傾斜 | 85 |
| T3 | train | 插入麵包板、30–40° 斜拍、不同孔位與方向 | 110 |
| V1 | val | 另一時段與光線，混合裸模組／麵包板 | 70 |
| E1 | test | 未在訓練出現的背景與擺法 | 40 |
| N1 | train | 無 HC-SR04、空麵包板、手與線、相似藍色模組 | 80 |

可使用標註器的「影片取幀」，也可以直接從目前 Board Vision 串流擷取：

```powershell
.\scripts\capture-hc-sr04-pose.ps1 -Split train -Duration 60 -Interval 0.7
```

建議間隔 0.5–0.8 秒。不要站在原地只錄連續近似畫面；每隔數秒改變距離、角度、背景或遮擋。直接串流工具會略過過度相似的連續畫面。

## 3. 標註與訓練

從專案根目錄執行：

```powershell
.\scripts\hc-sr04-pose-label-studio.ps1
```

在標註器選好 split 後使用「影片取幀」。第一版尚無 HC-SR04 模型，因此先人工完成至少 20 張 train 與 5 張 val，執行 pilot：

```powershell
.\scripts\train-hc-sr04-pose.ps1 -Pilot
```

目前 Board Vision 的正式 HC-SR04 疊圖採用與光敏電阻相同的 Profile 投影：
YOLO 的四個排針 landmark 只協助判斷接頭所在邊與 VCC→GND 方向，藍色 PCB
輪廓提供真正四角，VCC／TRIG／ECHO／GND 最終都由固定 Profile 透視投影，
不直接採用容易飄移的 YOLO Pin 座標。另保留四角遷移學習實驗流程；
Runtime 使用由 pilot checkpoint 重新匯出的固定 768×768 ONNX；原本的
960×960 ONNX 保留作比較，不能只改啟動 input size，否則 OpenCV 會因固定
輸入形狀不一致而拒絕推論。
要由已審核的 8 點資料建立並訓練正式四角模型，執行：

```powershell
.\scripts\train-hc-sr04-corner-pose.ps1
```

輸出為 `models/hc-sr04-corner-pose.pt` 與
`models/hc-sr04-corner-pose.onnx`。如需比較舊 8 點模型，可在啟動時同時指定
`-ComponentModelPath models\hc-sr04-pose-pilot.onnx` 與
`-ComponentProfilePath profiles\components\hc-sr04\vision_profile_8kpt.json`，
避免模型與 Profile 的點數契約不一致。

Pilot 會輸出 `models/hc-sr04-pose-pilot.pt`。重新開啟標註器並選擇這個模型，即可對其餘圖片做批次預標；所有 `auto_pending` 結果仍須人工確認。完成完整數量後執行：

```powershell
.\scripts\train-hc-sr04-pose.ps1
```

正式輸出為：

- `models/hc-sr04-pose.pt`：後續自動預標
- `models/hc-sr04-pose.onnx`：Board Vision runtime

Pilot 完成後可先在現有 C920 介面測試，不會取代 Controller 的板卡 Pose：

```powershell
.\scripts\camera-yolo.ps1 -Board raspberry-pi-5 -Component hc-sr04
```

畫面會以 HC-SR04 前四點繪製 PCB 外框，後四點直接顯示
`VCC`、`TRIG`、`ECHO`、`GND`。Pilot 僅供驗證與後續預標；正式接線引導前仍須以獨立 test split 驗收點位誤差。

## 4. 麵包板辨識範圍

HC-SR04 Pose 只負責模組方向與固定 Pin 根部。後續麵包板流程另外執行：

1. 偵測麵包板外框與中央溝槽。
2. Homography 校正成俯視網格。
3. 建立 2.54 mm 孔位格點。
4. 由四個 Pin 根部沿排針方向投影，吸附到四個連續孔位。
5. UI 顯示每個 Pin 對應的列／欄。
6. 是否真正導通仍由 Serial 或外部電氣量測確認。

若 HC-SR04 直接插入後接近直立，完全俯視只會看見薄邊，無法可靠定位；資料拍攝與使用時應讓鏡頭保持約 30–40°，或增加側視相機。
