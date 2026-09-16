# Component Label Studio

Board Vision 的 YOLO 零件資料標註工具，支援 Detection 方框與 Segmentation 多邊形資料集。

## 啟動

在專案根目錄雙擊 `component-label-studio.cmd`，或執行：

```powershell
.\scripts\component-label-studio.ps1 -Data C:\Users\james\Downloads\pi5_data\data.yaml
```

未指定資料集時，工具會優先載入上次使用的 `data.yaml`，其次嘗試目前的 Pi 5 資料集。

## 建議工作流程

1. 選擇 `train`、`val` 或 `test`，再匯入圖片資料夾；也可從影片依時間間隔自動取幀。
2. 對新圖片按「預標目前圖片」，或按「批次預標所有未標圖片」。
3. 自動結果會標為 `auto_pending`，逐張修正多邊形／方框及類別。
4. 按「確認並下一張待確認」完成審核。
5. 沒有目標零件的畫面按「標記為負樣本」。

批次預標只處理沒有 label 檔的圖片，不覆蓋既有標籤。單張預標若模型沒有找到零件，也會保留原標籤。每次開啟工具後，首次修改既有 label 時會備份到：

```text
<dataset>/.component-label-studio/backups/<session>/
```

審核進度保存在 `<dataset>/.component-label-studio/review.json`，不會混入 YOLO 訓練標籤。

## 操作

- Polygon：左鍵依序加點，`Enter` 完成；右鍵退回一點。
- Box：按住左鍵拖曳方框。
- Edit：選取標註並拖曳頂點。
- `Ctrl+Z`／`Ctrl+Y`：上一動／重做。
- `Delete`：刪除選取標註。
- `1`–`9`：快速切換前九個類別。
- 滑鼠滾輪：縮放圖片。

目前預設自動預標模型為 Pi 5 零件 Segmentation 模型；模型類別以名稱對應資料集類別，不存在於資料集的模型類別會跳過並顯示在狀態中。

