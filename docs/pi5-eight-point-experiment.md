# Pi 5 八點離線比較

此工具只比較既有資料與模型，不修改 Board Vision 的啟動設定、相機、API、正式權重或人工標註。舊 `pi5-8point-rollout.md` 提到的 C920 校正不可直接套用到其他相機；沒有有效校正時不強行開啟八點 PnP。

## 比較內容

- 凍結三個歷史八點 pilot 的 ONNX／PT，沿用四點實驗的原始資料、幾何與後端快照。
- 104 張人工八點 train、35 張既有 val，另沿用 50 張空標註負例。驗證來源及 J8 標註與四點基準逐一比對 SHA256；原圖與標註不改寫。
- J8 只使用人工 P1、P2、P40、P39；另外比較兩排 GPIO 的方向誤差及交叉／翻轉。其餘 36 腳不當成人工真值。
- 模型直接輸出的 J8、正式流程 GPIO、既有有界端點修正的診斷值分開記錄。缺少相機校正時，正式流程可能回退四點，即使載入的是八點權重。
- 微調只使用既有人工 train 與既有負例，40 epochs、AdamW 0.0001、warmup_bias_lr=0、batch 4、960；不使用鏡像、Mosaic、MixUp、偽標註或新拍攝。
- checkpoint 按實際端點誤差與漏檢選取。驗證集選模不是獨立測試，沒有新真實接線泛化的保證。

## 重現

請使用新的獨立 `--out` 目錄。輸入 `--parent` 是已凍結的四點實驗，不會改寫它。

```powershell
# 專案根目錄；以下每個命令另帶 --parent <四點實驗> --out <新目錄>
& '.\backend\.venv\Scripts\python.exe' tools/pi5_eight_point_check.py prepare
& '.\backend\.venv\Scripts\python.exe' tools/pi5_eight_point_check.py evaluate
& '.\backend\.venv\Scripts\python.exe' tools/pi5_eight_point_check.py audit-images
& '.\.venv-training\Scripts\python.exe' tools/pi5_eight_point_train.py dataset
& '.\.venv-training\Scripts\python.exe' tools/pi5_eight_point_train.py train --epochs 40 --seed 0 --accept-ultralytics-license
& '.\.venv-training\Scripts\python.exe' tools/pi5_eight_point_train.py scan --seed 0
& '.\.venv-training\Scripts\python.exe' tools/pi5_eight_point_train.py export --seed 0
& '.\backend\.venv\Scripts\python.exe' tools/pi5_eight_point_check.py evaluate --models eight-seed0
& '.\backend\.venv\Scripts\python.exe' tools/pi5_eight_point_check.py parity --models eight-seed0
& '.\backend\.venv\Scripts\python.exe' tools/pi5_eight_point_finish.py replay
& '.\backend\.venv\Scripts\python.exe' tools/pi5_eight_point_finish.py report
```

授權旗標沿用專案已確認的使用方式，不代表工具替使用者作法律判斷。不安裝、更新或複製另一個環境的套件。訓練環境缺少後端依賴時，選模只讀 YAML 與無伺服器依賴的解碼函式。

八點所有端點都做 PT／ONNX 一致性比對；不能只檢查前四個板角。連續回放採四→八→八→四，保留既有追蹤門檻、未延長舊座標保留。失鎖與光流殘差不是人工 GPIO 真值，也不是 webcam FPS。

任一準確度、角度、覆蓋或回放門檻不通過即保留四點。首輪通過也不自動上線，仍需第二個 seed 與實際使用者驗收。

相關測試請在 `backend` 目錄執行，避免依賴其他測試的隱含 `sys.path` 修改：

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/test_pi5_eight_point_check.py tests/test_wiring_pose_experiment.py tests/test_yolo_profile_detector.py tests/test_cuda_pose.py tests/test_pi5_j8_geometry.py -q
```
