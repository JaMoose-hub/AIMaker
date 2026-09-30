# 接線場景三模型微調實驗

入口：`tools/wiring_pose_experiment.py`。這是離線研究工具，不連相機、不改 API/UI、不更新正式模型路徑。

## 執行

在 `C:\Project\PnP\board-vision` 執行，沿用既有兩個 Python 環境。完整實驗必須使用新的輸出目錄：

```powershell
& '.\backend\.venv\Scripts\python.exe' tools/wiring_pose_experiment.py run `
  --out runs/wiring-pose-optimization-YYYYMMDD `
  --accept-ultralytics-license
```

授權旗標表示專案已確認 Ultralytics 授權使用方式，不代表工具代替使用者判定授權。GPU 訓練會影響同機即時程式效能。程式不安裝套件或更新環境。

`run` 依序執行 audit/snapshot、七個既有模型 CUDA 比較、三類 A/B seed 0 訓練、選出每類研究候選、seed 1 重跑、PT/ONNX 比對、共同回放及報告。已完成階段可接續；部分完成的訓練目錄會拒絕覆寫，需要先檢查錯誤，不會自動清除資料。

分段命令：`prepare`、`baseline`、`datasets --component pi|tft|hc`、`train`、`export`、`evaluate`、`freeze-replay`、`replay`、`report`。訓練和匯出使用 `.venv-training\Scripts\python.exe`；其餘使用 `backend\.venv\Scripts\python.exe`。`train` 必須另帶授權旗標。

## 資料規則

- 原始圖、標註、模型、幾何設定、後端程式與資源均快照及 SHA256；來源不改寫。
- 缺失標註排除，只有存在且空白的標註檔才算負例。非數字、非預期類別、錯誤尺寸、交叉或不完整角點排除。
- 同圖不同標註視為衝突；同來源／已知拍攝組不跨 train 和 held-out。無法追回拍攝組的舊圖標示 unknown，不冒充獨立測試。
- `__` 歷史衍生圖不再當增強起點；既有合成 test 只列壓力資料，不作獨立驗收。
- 已確認的 TFT 語意問題保存在 `tools/wiring_pose_semantic_exclusions.json`，用圖片＋標註 SHA256 比對；命中即隔離整類訓練／定位驗收，不自動修標。目前舊 TFT 訓練／驗證的抽查點位在 PCB 外角，和正式孔心語意不一致。`blocked/tft.json` 記錄依據，`label-audits/tft.jpg` 可檢視對照。不把格式正確當成語意正確。
- A/B 使用相同原始來源、已知拍攝組均衡、相同 affine 及 photometric 變換。每來源有原圖、兩個輕量變體；B 的第二個變體額外包含定向情境。增強不創造額外人工真值。
- Pi 遮擋最高 20%；TFT 只改四孔內中央 60% 長寬範圍，不改孔及邊框；HC 保留既有 Pi-only 負例，增添線材／接頭／小面積反光。
- 幾何操作同步更新框、角點、可見性；可見但被合成遮住的已知角點標 v=1，出界標 v=0。停用 flip/Mosaic/MixUp。

## 訓練與選模

Pi 960 / TFT 1280 / HC 768；CUDA；AdamW、lr0=0.0001、warmup_bias_lr=0、batch=4、seed=0、patience=8。Pi/TFT 上限 40 epochs；HC 上限 20。loss 權重來自選定起始 checkpoint 的 train_args，缺項才用已保存 args.yaml。

2026-09-30 修正：第一輪保存的訓練曾沿用 Ultralytics 的 `warmup_bias_lr=0.1`，第一個 epoch 的 bias 組實際 LR 約 0.0669。這不適合作為低學習率微調的隱含預設。現在明確設為 0，並檢查 CSV 中所有 optimizer 組都未超過 lr0。第一輪原始結果保留，不回寫成新設定。

A/B 提前停止輪數若不同，取兩者共同已完成輪數內的 checkpoint，比較相同步數預算；預算外權重不參選。checkpoint 依 pose mAP50-95，平手依較低 validation pose loss 選取。最終回歸驗收看角點／J8 誤差，**不是用 mAP 代替 GPIO 精度**。seed 1 保留原 LR 排程總長度，以 callback 在共同輪數預算停止，避免縮短排程影響比較。

本機 Ultralytics 8.4.115 的 DataLoader 使用固定 generator seed，單改訓練 `seed` 在固定離線增強情境可能產生完全相同的訓練。本工具對非零 seed 重新設定 train loader generator 並 reset，記錄於 `sampler.json`；不修改套件。seed 0 保留原本資料順序。首次偵測到無效 seed 重跑時，已停止並保留該部分結果，檔名包含 `invalid-fixed-loader`，不納入驗收。

## 驗收邊界

- Pi J8 只比較原有四個人工端點 P1/P2/P40/P39，單位為 px 與影像腳距。
- 元件分別列原始角點、正式 mounting-hole/PCB/refinement 流程結果，TFT 不拿外框和孔心交叉比較。
- 預測框與人工框 IoU 至少 0.5 才算匹配；不只檢查有沒有輸出。未匹配正例計為漏檢，不直接假定一定認成其他物件。
- 漏檢進入定位成功率分母。P95 仍是有輸出點的分布，所以同時限制漏檢、負例誤檢及後處理有效覆蓋數不惡化。
- metric schema 4：後處理有效覆蓋還必須與人工角點四邊形 IoU ≥ 0.5；錯誤對象不能算定位成功。另列 `post_emitted_positive` 保留所有輸出數，P95 不刪除錯誤輸出。比較時由兩邊保存的逐圖座標重新計算同一定義。
- 為避免「模型更準但正式 GPIO 沒改善」，原始與正式流程兩者的 P95 均需改善 15%。這比只看原始角點更保守。
- 沒有負例的 validation 不宣稱誤檢已驗證；historical validation 不是新獨立 holdout。
- 重用既有連續影格及原 timestamp；三工作器共享 component 狀態，保留 identity gate 與追蹤參數。不以增加舊位置保留改善分數。
- 回放是同步 worker 重放，不是完整 camera/server/MotionOverlayWorker/UI 排程。P95 延遲上限為基準 +10%，不能換算實際 webcam FPS。
- 低頻抽幀不評估精細恢復時間。未有人工確認靜止及移動真值時，只記錄狀態重新鎖定及光流補償殘差，不冒充絕對抖動／恢復準確度。
- 不共用 raw 推論快取；每個模型真實執行每張圖。完整評估報告快取以模型、來源圖片／標註、設定與凍結 runtime 雜湊隔離。
- PT/ONNX 使用相同輸入、fused FP32 參考及私有 CUDA FP32 session，`rtol=.001, atol=.01`。另以未修改的正式 CUDA session 驗證解碼後偵測有無一致、角點差 <=0.5 輸入像素、信心差 <=.002。保留兩種 raw tensor 比較結果，不以單純放寬數值容差掩蓋不相容。參考 [ORT CUDA TF32 設定](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html#use_tf32)。
- 所有候選不自動上線。未達標或真實插滿接頭情境未驗證，都保留原正式模型。

## 測試

```powershell
& '.\backend\.venv\Scripts\python.exe' -m pytest backend/tests/test_wiring_pose_experiment.py -q
```

產物位於 `REPORT.md`、`report.json`、`manifest.json`、`integrity.json`、`evaluations/`、`comparisons/`、`candidates/`、`training/`、`replay/`。訓練設定 `args.yaml`、`complete.json` 及 paired lineage 是重現依據。若工作區其他開發變更原始來源，`integrity.json` 記錄漂移；已凍結實驗不受影響。

參考：[Ultralytics 訓練參數](https://docs.ultralytics.com/modes/train/) · [資料增強](https://docs.ultralytics.com/guides/yolo-data-augmentation/)。實際行為以本機凍結環境及保存 args 為準，不升級到網站的新版本。

## 第二輪：分段診斷與受控修正

`tools/wiring_pose_followup.py` 對第一輪凍結資料做 Pi 分段／高度投影診斷、TFT 29 張既有孔心標註的放大稽核與回歸比較。人工板角的 oracle 分析不進候選推論。

`tools/wiring_pose_followup_train.py` 使用新的輸出目錄、同一組 HC A 資料及 20-epoch LR 排程，在共同 14-epoch 預算停止。只改 bias 暖身，兩個 seed 的原始標註與權重來源不變。

```powershell
& '.\.venv-training\Scripts\python.exe' tools/wiring_pose_followup_train.py `
  --parent runs/wiring-pose-optimization-20260929 `
  --out runs/wiring-pose-followup-NEW --component hc --budget 14 `
  --accept-ultralytics-license
```

先以 `wiring_pose_checkpoint_scan.py --parent <第一輪> --training-root <第二輪> --out <第二輪>/warmup-scan --runs hc-A-seed0 hc-A-seed1 --budget 14` 比較所有已保存 checkpoint。`wiring_pose_followup_finalize.py export` 在遵守原模型漏檢上限、達成定位 P95 目標的候選中選漏檢較少者；接著用 backend 環境的 `evaluate` 驗證實際 ONNX、正式流程、負例與 PT 一致性。所有命令均需指定 `--parent`、`--out`。

TFT 候選在 `wiring_pose_candidates.py`，僅於離線評估程序掛載：方向翻轉必須符合既有面板內縮幾何，且經過局部擾動仍一致；不增加歷史位置保留時間、不修改正式模組。第一個僅做擾動投票的版本未改善，保留其失敗結果。加入面板幾何檢查的版本另行保存。

`replay` 比較 HC 新權重＋TFT 方向保護；`tft-replay` 則獨立比較保留三個原權重、只加 TFT 方向保護。各自的結果不可混成「三類模型全面通過」。`report` 彙整結果與工具快照。

HC 靜態誤差改善不表示手持追蹤通過；TFT 的 29 張孔心圖曾參與歷史訓練，只能作回歸。Pi 八點架構仍需另行確認，不因這些工具而自動啟用。
