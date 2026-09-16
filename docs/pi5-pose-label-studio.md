# Pi 5 YOLO Pose Label Studio

這是 Raspberry Pi 5 板卡定位資料的獨立標註器，預設直接使用目前的四點資料：

1. `profile_TL`
2. `profile_TR`
3. `profile_BR`
4. `profile_BL`

四點名稱代表板卡 Profile 的固定語意方向，不是板子旋轉後在畫面中的左上、右上位置。

## 啟動

在專案根目錄雙擊：

```text
pi5-pose-label-studio.cmd
```

或執行：

```powershell
.\scripts\pi5-pose-label-studio.ps1 `
  -Data .\training\board-pose-pi5.yaml
```

預設自動載入：

- Dataset：`training/board-pose-pi5.yaml`
- Model：`runs/pose/runs/board-pose/pi5-handheld-v2/weights/best.pt`

## 標註方式

- 直接拖曳畫面上的 TL／TR／BR／BL 修正位置。
- 選擇關鍵點後按「重新放置」，再點選正確位置。
- 使用「可見／遮擋／未標」設定 YOLO Pose visibility。
- `Ctrl+Z`／`Ctrl+Y` 執行上一動與重做。
- 按「保存草稿」保存修正；按「確認並下一張待確認」完成人工審核。
- 畫面沒有 Raspberry Pi 5 時，使用「標記為負樣本」。

保存前會檢查四點是否完整、順序是否交叉，以及板卡四邊形是否過小。

## 自動預標

- 「自動預標目前圖片」會使用目前的 Pi 5 Pose 模型產生四點，再交由人工拖曳修正。
- 「批次預標所有未標圖片」只處理沒有 label 的圖片，不覆蓋現有標籤。
- 自動結果會標為 `auto_pending`；人工確認後才改為 `reviewed`。
- 模型沒有找到 Pi 5 時不會建立空標籤，也不會刪除原標籤。

首次修改既有標籤時，原檔會備份至：

```text
datasets/board-pose-pi5/.pose-label-studio/backups/<session>/
```

審核狀態保存在 `.pose-label-studio/review.json`。

## 新增資料

- 「匯入圖片」可將手持、接線、手部遮擋及不同角度圖片加入目前 split。
- 「影片取幀」可從多角度影片定時擷取圖片。
- 新圖片加入後，按「批次預標所有未標圖片」，再逐張人工確認。

