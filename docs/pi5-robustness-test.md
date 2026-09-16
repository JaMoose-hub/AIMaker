# Raspberry Pi 5 背景與光線穩健性測試

這個流程會從已標註的 Pi 5 Pose 圖片建立一份**獨立的合成壓力測試集**，再用目前部署的 ONNX 模型比較原圖與合成圖的偵測率、關鍵點誤差。合成分數不會取代、合併或提高真實 `test` set 的驗收分數。

## 執行

先以少量圖片檢查遮罩與視覺品質：

```powershell
.\scripts\test-pi5-robustness.ps1 -Split val -MaxImages 5 -Variants 5 -GenerateOnly
```

確認輸出的遮罩有完整保留 Pi 5、手及線材後，執行完整測試：

```powershell
.\scripts\test-pi5-robustness.ps1 -Split val -Variants 5
```

完成八點模型訓練後也可直接串接壓力測試：

```powershell
.\scripts\train-pi5-8kpt.ps1 -RobustnessTest -RobustnessSplit test
```

每次執行會建立新的 `runs\robustness\pi5-<時間>`，內含：

- `images/synthetic`：合成後圖片。
- `labels/synthetic`：逐位元複製的原始 Pose 標籤，幾何位置不變。
- `masks/synthetic`：實際用來保留前景的二值遮罩，必須人工抽查手和細線。
- `manifest.jsonl`：每張圖的背景、Gamma、曝光、色偏、陰影、反光、模糊、雜訊及 JPEG 參數。
- `report.json`：原圖 baseline、合成整體、各背景與各色偏的分項結果及門檻。

## 前景遮罩模式

優先順序建議如下：

1. `mask`：最可靠。將與原圖同名的白前景／黑背景 PNG 放到指定資料夾；適合精確保留手指和細杜邦線。

   ```powershell
   .\scripts\test-pi5-robustness.ps1 -ForegroundMode mask -MaskDir datasets\pi5-foreground-masks
   ```

2. `clean-plate`：同一相機位置先拍一張沒有 Pi 5、手與線材的桌面，可用背景差分保留整組前景。

   ```powershell
   .\scripts\test-pi5-robustness.ps1 -ForegroundMode clean-plate -CleanPlate data\clean-table.jpg
   ```

3. `auto`：預設使用畫面邊界顏色估計背景，再保留與板子連通的手及線材。方便快速測試，但輸出的 mask 必須人工確認；不應直接拿未檢查的結果訓練。

可另用 `-BackgroundDir` 指向自行拍攝且無 Pi 5 的桌面背景；系統會與五種內建程序背景交錯使用。

## 合成條件與判定

- 背景：白桌、木紋、深色墊、金屬桌、雜亂工作台。
- 邊緣羽化：`0.8–2.2 px`；依隨機光源方向加入柔化陰影。
- Gamma：`0.65–1.45`；曝光：`0.70–1.30`。
- 暖黃、冷白或中性色偏；局部柔化陰影與小範圍反光。
- 模糊：`0–1.25 sigma`；高斯雜訊：`0–7 sigma`；JPEG 品質：`58–95`。

預設壓力測試門檻：合成偵測率至少 90%、相對原圖下降不超過 10 個百分點、關鍵點誤差中位數不超過板子對角線 10%、P95 不超過 25%。這些門檻只用來發現環境敏感性；正式模型仍須以不同影片時段的真實 test set 和 GPIO 投影誤差驗收。
