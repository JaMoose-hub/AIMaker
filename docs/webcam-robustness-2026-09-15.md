# Webcam 遮擋、移動、背景：固定回放、移動交接與採用紀錄

後續更新：[9/16 Pi 搜尋區域修正已啟用；交接／GPIO 驗收仍待完成](webcam-pi-handoff-2026-09-16.md)。以下保留 9/15 紀錄。

日期：2026-09-15。最新狀態：**第二輪 HC-SR04／HW-123 移動交接修正已接入 Webcam，並重啟載入；Pi／TFT 候選未通過比較，維持原版。尚未達到四件 90% 實體驗收。**

## 第二輪交付：先採用有改善且未退步的部分

本輪沒有新增訓練、模型權重或資料集，仍使用下方 10 段既有影片。Eye 程式、模型與設定不變，未啟用 Eye。

### 已接入的修正

- 新增 `image_pose_window.py`：先用當前板面特徵量測影像位移，把連續觀測對齊後再累積定位共識，不要求使用者把移動中的零件停在相同螢幕座標。
- 沿用有界光流／RANSAC；分散特徵不足、方向不一致、缺幀、過期或全遮擋不能累積成新定位。輸出仍對應當前影格，不以延長舊框顯示冒充追蹤成功。
- `main.py` 僅對 HC-SR04／HW-123 的 Webcam worker 啟用 `webcam_motion_handoff`；TFT 關閉，Pi 實驗搜尋與交接關閉。
- 將 worker 的真實 `motion_outline` 與原圖接入 `MotionTrack`／`PinRegions` 回放，量測最終是否有新鮮腳位，不再只比較模型 `locked`。
- Eye 的直接 YOLO 路徑不經此交接；新增 builder 範圍／Eye 路徑隔離測試。前端原藍框與 GPIO 樣式未改。

### 同段影片 A/B 結果

以下是**包含完整失敗區間的原始影片影格中，最終顯示階段輸出腳位的數量**，不是實體腳位正確率，也不是恢復動作的通過率。

| 手持片段 | 原版有腳位 | 修正版有腳位 | 原版全部腳位／修正版全部腳位 |
|---|---:|---:|---:|
| HC-SR04，1492 幀 | 176 | 530 | 167 / 501 |
| HW-123，1467 幀 | 535 | 570 | 416 / 420 |

兩組前後影格錯配均為 0。回放使用相同模型輸出、來源影格與時間戳，模擬 150 ms 推論結果送達延遲；包含真實後端顯示追蹤，但**不含瀏覽器呈現、四個 worker 同時競爭或現場實測延遲**。不同工具的抽樣影格數不同，不能把上表和下方 worker `locked` 比例混用。

- HC worker：473 幀 `locked` 21 → 33；HW：473 幀 62 → 150。HW 在這一層增加很多，但最終腳位增加較少，表示後段追蹤仍是限制；不把中間指標當最終成果。
- 花紋／雜物線遮擋／白背景：HC／HW 的原有 `locked`／`stale` 計數均未下降；三段空背景均未新增 `locked`。
- 同一批靜態背景中，候選腳位相對原版最大偏移小於 1.84 px。這是**新舊座標差**，不是相對真實排針的誤差。

### 不採用的候選與待解問題

| 零件 | 已試方法與结果 | 本次決策 |
|---|---|---|
| Pi 5 | 參考圖搜尋加影像補償的確認；手持 181 幀 `locked` 68 → 24，花紋 0/30 → 30/30。J8 後段確認仍有交接問題 | 不啟用，保留原版；不能用單一背景改善抵銷手持退步 |
| TFT | 以實際四個安裝孔聯合核對角點；手持 `locked` 1 → 10，灰／雜物空背景誤鎖消除，但白背景 63 → 42、線遮擋 70 → 29 | 不啟用，保留原版；需處理局部可見孔位與反光，而非要求四孔始終清楚 |

### 重啟與現場讀取核對

- 已重啟 Board Vision 載入 HC／HW 修正，WebSocket 已重新連接；未操作接線、部署或雲端檢查。
- 介面回報 HC／HW 的 `webcam_motion_handoff=true`，TFT 為 false，三模組推論仍為 CUDA。
- 解碼重啟前後的實際相機影像，均為 1920×1080，同影格資料錯配均為 0。平均亮度 133.42 → 132.28，P99 225 → 223，影像不是黑畫面。
- UVC 回讀的亮度／對比／飽和度／銳利度均 128，焦距 10、曝光 -5、增益 0；前後數值及模式旗標一致，均 Verified。`backend/config.yaml` SHA-256 亦未變。
- 重啟後這張靜態畫面：Pi `locked`／40 pins、HC `locked`／4 pins、HW `locked`／8 pins；TFT `searching`／0 pins。**TFT 在當前擺位仍有漏認，不能宣稱四件都已穩定。**未執行瀏覽器 GPIO 視覺驗收。

### 本輪完成與剩餘項

- [x] 影像移動對齊的定位共識／交接實作及小型 A/B。
- [x] 同步 MotionTrack／PinRegions 完整後端顯示回放，保留沒腳位的影格與同影格核對。
- [x] HC／HW 背景與空背景回歸，僅啟用通過比較的兩件，重啟核對相機與設定。
- [x] Pi／TFT 候選比較，未達採用條件的功能留在離線試驗，未改成現場預設。
- [ ] Pi：解決模型、參考圖與 J8 精修的定位交接退步，再用相同片段比較。
- [ ] TFT：修正反光／局部遮擋下的初次角點取得，不能以丟失真零件來換取空背景零誤認。
- [ ] 四件正常接線動作的 GPIO 實體對準與遮擋恢復驗收。目標仍是每件約 9/10 操作循環，不以本輪連續影格數勾成完成。

目前不需重拍整套資料或重跑九階段。接下來先處理 Pi／TFT 剩餘程式問題；只有原素材確實無法核對方向時，才提出具體、少量的補拍需求。

### 第二輪證據與測試

位於 `runs/acceptance/2026-09-15/webcam-robustness-v1/`：

- `handoff-final-hc-hw.json`：最終 HC／HW worker 比較。
- `handoff-display-final-hc-hw.json`：最終顯示腳位回放，上表以此為準。
- `handoff-regression-v2.json`：背景、線遮擋及空背景回歸。
- `pi-handoff-window-v3.json`、`handoff-tft-rings-v5.json`：未採用的 Pi／TFT 候選，保留退步證據。
- `runtime-before-handoff/`、`runtime-after-handoff/`：原始 JPEG、相機設定與同影格資料快照。
- `runtime-handoff.stdout.log`、`runtime-handoff.stderr.log`：本輪重啟日誌。

新增 `tools/replay_motion_display.py` 及只讀 `tools/check_webcam_runtime.py`；擴充原 component／Pi 回放工具，不替換既有模型。

最終相關測試 **101 passed**，包含 Webcam 啟用範圍、Eye 隔離與影像幾何失敗情境。本輪完整後端測試曾為 **1285 passed、2 skipped、3 failed**；三項仍是既有 `test_pi_boundary_rejection.py::test_bad_primary_only_yields_to_fresh_feature_lock` 的 SimpleNamespace mock 缺 `body`，未宣稱全套通過。最後新增的啟用範圍測試已另行通過，未再跑完整後端套件。

以下保留第一輪離線紀錄供追溯；當時的「候選未啟用」不代表上方最新的 HC／HW 現場狀態。

## 範圍與執行原則

- 包含 Pi 5、HC-SR04、HW-123、MRD-TF240 TFT；不含光敏電阻，不調整 Eye／眼鏡路徑。
- 不新增拍攝、不重訓、不更換模型權重；優先重用現有影像特徵、校準參考圖及原始影片。
- 原藍框與 GPIO 顯示方式不變。沒有當前影像證據時，不把舊腳位當成新定位。
- 不改接線、供電、部署或雲端檢查，不增加使用者操作門禁。

## 固定比較集：只重用 10 段舊片

清單：`runs/acceptance/2026-09-15/webcam-robustness-v1/suite.json`。
原始素材：`runs/acceptance/2026-09-13`。

- 四件各一段手持影片。
- 花紋背景、雜物加線遮擋、白背景各一段。
- 灰、花紋、雜物空背景各一段，檢查誤認。

三模組以至少 100 ms 間隔抽樣，Pi 至少 300 ms；因此不能直接比較不同零件的比例。相同零件的 A/B 使用同一份原始模型輸出、影格、時間戳與 RNG seed 7。快取核對來源影像及模型 SHA-256、設定與時間；不相符即報錯。

這是已在歷史工作中看過的工程回放，**不是全新獨立驗收集**。不把單張抽查或重複影格當大量獨立試驗，不重跑全部九階段。

## 第一輪歷史：已實作但當時關閉的兩項候選

### A. 三模組的影像接續

`backend/app/vision/pose_continuity.py` 與 `component_worker.py`：

- 沿用 PlanarFlow 的前後向光流、RANSAC 及分散板面特徵。
- 使用已接受的語義方向，從當前影像求新位置；模型只核對物件／角點順序是否相容。
- 有效期 1500 ms、最大影格間隔 400 ms；無模型、錯方向、全遮擋、缺幀、相機變更不能產生新 GPIO。
- 寬鬆的模型區域一致不能永久續期；回傳座標來自影像，不是速度預測。
- 有當前分散板面證據時，候選才不受整塊手部／材質比例單獨否決。
- `ComponentPoseTracker(..., visual_continuity=False)` 為預設；正式 worker 沒有啟用候選。

### B. Pi 的校準參考照搜尋備援

`backend/app/vision/scene_reference_search.py` 與 `yolo_profile_detector.py`：

- 原模型／ROI 或板面輪廓失敗時，候選可從既有校準參考照直接尋找板面。
- 全畫面搜尋最多每 500 ms 一次；找到後優先搜最後核實的局部區域，仍須每次重新匹配，不回傳快取座標。
- 沿用既有 SIFT／RANSAC 的內點數、分布、幾何、重投影檢查，沒有放寬這些門檻。
- 搜尋矩形 confidence 明確為 0，不把它當模型辨識或 GPIO 方向。
- Eye 路徑不呼叫此備援。預設關閉，未開啟時也不建立額外 SIFT 參考特徵。

## 第一輪歷史：實測結果與採用決策

以下數字是 **worker 輸出 locked 的影格數**，不是逐 Pin 正確率、最終瀏覽器 GPIO 可見率或電路驗證。

| 固定片段 | 原版 locked | 候選 locked | 決策 |
|---|---:|---:|---|
| HC 手持，473 幀 | 21 | 23 | 幾乎無改善，不啟用 |
| HW 手持，473 幀 | 62 | 127 | 有改善，但尚缺腳位真值／顯示驗證，不啟用 |
| TFT 手持，464 幀 | 1 | 1 | 沒改善，不啟用 |
| Pi 手持，181 幀 | 68 | 23 | 退步，不啟用 |
| Pi 花紋背景，30 幀 | 0 | 30 | 備援能解此情境，但不能抵銷手持退步 |
| Pi 雜物／線遮擋，31 幀 | 31 | 31 | 無變化 |
| Pi 白背景，31 幀 | 31 | 31 | 無變化 |

其他背景的三模組 A/B 狀態計數沒有變化。Pi 三段空背景合计 90 幀，A/B 均未 locked；HC/HW 三段空背景亦均未 locked。

**TFT 舊版已有空背景誤認，候選沒有解決：**灰背景 76 幀有 21 locked／53 stale；雜物背景 77 幀有 2 locked／18 stale；花紋空背景 76 幀無 locked。不能宣稱負例全部通過。灰背景原照確認是無零件的印字墊面。

Pi 備援有計算成本：花紋片段中，排除主模型推論的後段處理 p50 約 62 → 279 ms、p95 約 79 → 342 ms；手持 p50 約 109 → 290 ms。這是離線 CPU／GPU 混合路徑計時，不是現場端到端延遲或 FPS。

## 已定位的瓶頸

1. **移動時仍要求螢幕座標近似靜止。**原版 HC 的 473 幀中，377 幀等待共識；TFT 的 464 幀中，412 幀等待共識。影像接續目前須先有接受過的錨點，初次取得定位仍常卡住。
2. **Pi 定位備援與後段靜止確認衝突。**新備援手持回放有 99 幀 `jump_hold`，stale 由 5 增至 101。需要按真實影像位移確認移動，不能只延長舊座標保留時間，也不能把所有 stale 算成功。
3. **TFT 同時有角點錯位和背景假陽性。**花紋案例首張，TFT 模型角點不在真實 TFT 上；空背景又會鎖到非零件。不能只放寬材質／角點門檻。
4. **單一參考照不是四件都適用。**每段抽 3 張、合計 30 張的舊圖特徵探測：Pi 有幫助，HW 僅部分有效；HC 及 TFT 舊參考照多數不能匹配。不能據此推論它們一定要大量重訓，也不能把 Pi 方法直接全件上線。

## 第一輪歷史：當時排定的下一輪工作

- [x] 固定四件／背景／空背景小型集，保留失敗與逐影格證據。
- [x] 實作候選與同輸入 A/B 回放；保持現場候選關閉。
- [x] 分開記錄定位、共識、材質／遮擋及模型缺失；找到上述瓶頸。
- [ ] **優先：重構「取得定位 → 移動追蹤 → 失鎖重找」的交接。**用板面當前影像運動補償比較，而不是在移動期間要求同一組螢幕座標；同時檢查 Pi 板面與 J8 後段確認，避免互相重設。不可直接移除定位可信度檢查。
- [ ] 將 worker 的 `motion_outline`、同影格 JPEG、MotionTrack 與 PinRegions 接成完整離線顯示回放；現有 locked 報表不包含這一層。量測新鮮定位、無證據舊座標、恢復時間，而非只看框留多久。
- [ ] TFT 初次取得定位加入實際螢幕／板面幾何證據，排除印字、線材、空桌誤認；先用這 10 段驗證，避免犧牲真 TFT 召回。
- [ ] 僅在現有素材缺少可核對的語義方向時，再要求指定的少量近照；不先要求重拍整套背景，不先開新訓練。
- [ ] 候選在同組回放不退步、沒有增加假陽性後，才啟用 Webcam，做一次四件集中現場短測；仍以每件約 9/10 操作循環為 Demo 目標，但未達標不能勾選。

目前**不需要使用者操作硬體**。本檔不將九階段任何尚未完成的實體驗收改成已通過。

## 第一輪歷史：證據、工具與測試

同一結果目錄 `runs/acceptance/2026-09-15/webcam-robustness-v1/`：

- `dense-component-comparison.json`、`dense-cache/`：三模組密集同輸入 A/B。
- `pi-baseline.json`、`pi-scene-comparison.json`：Pi 原始輸入與參考搜尋候選 A/B。
- `reference-probe.json`：30 張舊照片的參考特徵探測，不是完整影片驗收。
- 早期 `components-before.json`／`components-candidate.json` 是 300 ms 探索結果；三模組以 dense 報告為主，避免混用分母。

新增／擴充工具：

```powershell
# 範例：只重跑一個已快取的 HW 片段；輸出必須使用新檔名。
backend/.venv/Scripts/python.exe tools/replay_component_sequences.py --case hw-123=runs/acceptance/2026-09-13/S05-HW-handheld-01 --cache-dir runs/acceptance/2026-09-15/webcam-robustness-v1/dense-cache --out runs/acceptance/2026-09-15/webcam-robustness-v1/hw-repeat.json --interval-ms 100 --compare-continuity

# 範例：Pi 背景 A/B，沿用已核對的模型輸出，不重跑主模型。
backend/.venv/Scripts/python.exe tools/replay_pi_boundary.py --case S02-pattern-four-parts-01 --out runs/acceptance/2026-09-15/webcam-robustness-v1/pi-repeat.json --observations-from runs/acceptance/2026-09-15/webcam-robustness-v1/pi-baseline.json --scene-reference-comparison
```

測試（backend 目錄執行）：最終相關測試 **62 passed**。本輪全套曾跑得 **1259 passed、2 skipped、3 failed**；三項均為既有 `test_pi_boundary_rejection.py::test_bad_primary_only_yields_to_fresh_feature_lock` 的 SimpleNamespace mock 缺 `body`，在本輪新增 Pi 搜尋前也已失敗。未以修改共享執行路徑掩蓋測試問題。最後另補兩項 lazy-init／非 Pi 隔離測試，包含在 62 項相關通過結果中。

未執行相機重啟、瀏覽器驗收、實體 GPIO 精度測量、雲端接線檢查或任何硬體部署。**沒有宣稱 90% 已達標，也沒有宣稱候選已在現場啟用。**
