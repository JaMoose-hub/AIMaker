# Raspberry Pi 5 八點姿態模型交接

目前程式已具備八點 PnP、40 Pin 3D 投影、Controller 熱切換與四點模型回退。若八點模型或有效的 C920 校正檔尚未存在，Runtime 會繼續使用既有四點模型，串流不會中斷。

## 目前狀態

- 原始四點資料保留在 `datasets/board-pose-pi5`，不會被補標工具覆寫。
- 八點資料輸出到 `datasets/board-pose-pi5-8kpt`。
- 共用相機校正檔為 `calibration/c920-1080p.json`。
- 完成的模型輸出為 `models/board-pose-pi5-8kpt.onnx`；下次啟動時會自動優先載入。
- 八點資料尚未補齊、校正檔或模型尚未產生時，介面會顯示「4 點回退」。

## 1. C920 1080p 校正

列印 9×6 內角點、25 mm 方格的棋盤格，保持 Board Vision 的 C920 1080p 串流運作，再於專案根目錄執行：

```powershell
.\scripts\calibrate-c920.ps1 -Mode capture
```

操作鍵：

- `Space` 或 `C`：保存目前有效視角。
- `U`：刪除上一張。
- `Esc`：結束擷取。

至少保存 20 張；建議拍 25–30 張，讓棋盤格分布於畫面中央、四角、不同距離及不同傾角。接著解算：

```powershell
.\scripts\calibrate-c920.ps1 -Mode solve
```

只有整體 RMS ≤ 1.2 px、最差單張 ≤ 2.5 px、覆蓋率 ≥ 30% 才會產生可被 Runtime 接受的校正結果。

## 2. 將既有四點資料補成八點

補標工具會鎖住原本四個板角，只需依序點選 `J8_P1`、`J8_P2`、`J8_P40`、`J8_P39`：

```powershell
backend\.venv\Scripts\python.exe tools\upgrade_pi5_pose_labels.py `
  --source datasets\board-pose-pi5 `
  --out datasets\board-pose-pi5-8kpt `
  --splits train `
  --session-id existing-train-20260827 `
  --resume
```

完成 train 後，再用不同 session id 補標 val，避免稽核時被判定為跨 split 洩漏：

```powershell
backend\.venv\Scripts\python.exe tools\upgrade_pi5_pose_labels.py `
  --source datasets\board-pose-pi5 `
  --out datasets\board-pose-pi5-8kpt `
  --splits val `
  --session-id existing-val-20260827 `
  --resume
```

操作鍵：

- 滑鼠左鍵：標記目前 J8 點。
- `U`：回復上一點。
- `V`：目前點被遮擋，不可見。
- `R`：清除本張新增的四點。
- `S`：跳過本張。
- `Enter`：四個點完成後保存。
- `Esc`：停止；下次加上 `--resume` 可接續。

不同影片時段必須使用不同 `session-id`，且同一時段不可跨 train、val、test。最終目標為 320 train、80 val、40 test，另有至少 50 張不含 Pi 5 的負樣本。

## 3. 資料稽核、訓練與驗收

訓練腳本會先做嚴格資料稽核，數量、八點格式、重複影格、跨 split 時段或負樣本不合格時會停止：

```powershell
.\scripts\train-pi5-8kpt.ps1 -Epochs 180 -Batch 8 -Device 0
```

資料尚未達正式門檻時，可先訓練不會被 Runtime 自動載入的 baseline：

```powershell
.\scripts\train-pi5-8kpt.ps1 -Pilot -Epochs 120 -Batch 8 -Device 0
```

Pilot 輸出為 `models\board-pose-pi5-8kpt-pilot.onnx`，不會覆蓋正式模型。

訓練完成後，以獨立 test set 與 C920 校正檔驗收 40 支 GPIO 的投影誤差：

```powershell
backend\.venv\Scripts\python.exe tools\evaluate_pi5_gpio_projection.py `
  --model models\board-pose-pi5-8kpt.onnx `
  --dataset datasets\board-pose-pi5-8kpt `
  --split test `
  --camera calibration\c920-1080p.json `
  --output-json runs\board-pose\pi5-8kpt-evaluation.json
```

驗收條件是 GPIO pitch ≥ 8 px 時，Pin 中位誤差 ≤ 0.25 pitch、P95 ≤ 0.5 pitch，且至少 95% 真實 test 畫面通過。模型與校正檔通過後，重新啟動程式即可由「4 點回退」切換為 `pnp_8pt`。

## 4. 背景與光線壓力測試

訓練或部署模型後，執行下列流程測試白桌、木紋、深色墊、金屬桌、雜亂工作台，以及 Gamma、曝光、色偏、局部陰影、反光、模糊、雜訊與 JPEG 壓縮的影響：

```powershell
.\scripts\test-pi5-robustness.ps1 -Split val -Variants 5
```

合成圖沿用原圖幾何與 Pose 標籤，結果只作穩健性壓力測試，不可混入真實 test set 分數。操作與前景遮罩要求見 [Pi 5 穩健性測試](pi5-robustness-test.md)。
