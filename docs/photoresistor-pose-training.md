# 光敏電阻模組 Pose 與腳位定位

此模型不直接猜 `VCC / GND / AO`。它辨識模組 PCB 的四個語意角點，再用
`profiles/components/photoresistor-module/vision_profile.json` 的單應性幾何，把三個腳位中心投影到即時影像。
因此 Arduino UNO Q 與感測器可以同時出現在畫面上，兩者各自定位自己的腳位。

## 1. 一次性 Sensor Profile 校正

模組元件面朝上、四支排針朝畫面下方：

```powershell
.\scripts\calibrate-photoresistor-profile.ps1
```

按 `C` 或空白鍵凍結，依序點藍色 PCB 本體的左上、右上、右下、左下，再點排針的 `VCC`、`GND`、`AO` 中心；模組上的 `DO` 不標。
按 `Enter` 儲存；`U` 復原、`R` 重來。

## 2. 收集 Pose 資料

```powershell
.\scripts\capture-photoresistor-pose.ps1 -Split train
.\scripts\capture-photoresistor-pose.ps1 -Split val
.\scripts\capture-photoresistor-pose.ps1 -Split test
```

即時畫面按鍵：

- `1`：無遮擋。
- `2`：手或線局部遮擋。
- `3`：手部重遮擋，但至少仍看得到一部分模組。
- `0`：負樣本，例如只有 UNO Q、手或桌面。

標記畫面依參考圖固定的實體角落順序操作。可見角點用滑鼠左鍵；被手遮住但可依輪廓估計的位置用右鍵，YOLO visibility 會記為 `1`。`L` 可沿用上一張座標，再以 `1` 到 `4` 切換各角點可見性。

建議第一輪至少：train 80 張、val 20 張、test 20 張。三個 split 要分成不同拍攝時段或背景，避免連續影格洩漏。train 建議配置為無遮擋 25、局部遮擋 30、重遮擋 15、負樣本 10。

模組太小時，三支排針會擠在一起。UNO Q 與模組同框時仍應讓相鄰排針約有 18px 以上間距。

## 3. 訓練與匯出 ONNX

```powershell
.\scripts\train-photoresistor-pose.ps1
```

預設以 CUDA 0、768px、150 epochs 訓練，輸出 `models/photoresistor-pose.onnx`。腳本已關閉水平與垂直翻轉，避免語意角點被交換。Ultralytics 只存在於訓練環境；執行階段使用匯出的 raw ONNX。

這裡的「強化」是監督式 Pose 訓練加上 hard-example 回收：把模型會飄、手遮擋、反光或小尺寸失敗的畫面重新標記後再訓練，並不是 reinforcement learning。
