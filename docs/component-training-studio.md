# Board Vision 零件辨識訓練中心

## 啟動

雙擊專案根目錄的 `component-training-studio.cmd`，或在 PowerShell 執行：

```powershell
cd C:\Project\PnP\board-vision
.\scripts\component-training-studio.ps1
```

## 工作流程

1. 選擇 Roboflow、CVAT 或其他工具匯出的 YOLO `data.yaml`。
2. 按「檢查資料」；系統會自動辨認 Detection／Segmentation，並檢查：
   - train／val／test 數量
   - 類別與 instance 分布
   - 非法 class id、座標、Box 或 Polygon
   - 未標記負樣本、孤立 label
   - 跨 split 完全相同圖片造成的 data leakage
3. 設定 Epoch、Image size、Batch、GPU 與 augmentation。
4. 按「開始訓練」；完成後會自動跑 test（沒有 test 時使用 val）、匯出 ONNX，並建立同名 JSON manifest。
5. 按「安裝到 Board Vision」；舊 runtime 模型與 manifest 會先備份，再安裝新模型。
6. 重新啟動 Board Vision 才會載入新 ONNX。安裝不會自動打開 Segmentation UI。

## 建議資料規格

- 每一類至少 100 張 train；容易混淆或較小的零件建議 200 張以上。
- val 至少每類 20 張，獨立 test 至少每類 20 張。
- train／val／test 使用不同影片時段，不可將同一段連續影格隨機拆散。
- 加入不同距離、0–360° 平面旋轉、25–45° 傾斜、反光、接線、手遮擋與局部出框。
- 加入沒有目標零件或沒有板子的負樣本；空 label 或沒有 label 代表背景圖。
- Pi 5 GPIO Pin mapping 仍由 Board Pose 負責；零件 Segmentation 只用來圈出 GPIO、USB、HDMI、CPU 等區域。

## 輸出內容

- `*.onnx`：OpenCV DNN runtime 模型。
- 同名 `*.json`：task、類別順序、input size、資料指紋、test metrics 與 Ultralytics 版本。
- `runs/components/<run-name>`：best/last checkpoint、曲線、confusion matrix 與預測圖。
- `models/backups/component-segmentation/<timestamp>`：安裝新模型前的 runtime 備份。

