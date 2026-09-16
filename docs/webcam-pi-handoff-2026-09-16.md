# Webcam Pi 5：搜尋與移動交接修正（2026-09-16）

狀態：**最新修正 TFT 接線後漏認：兩段開發回放109/111、107/110次鎖定；不是GPIO準確率或跨背景90%驗收。HC既有16/34、8/36改善保留，Pi/HW/Eye不啟用新的TFT路徑。**

## 範圍

### TFT 接線外觀：低分候選、局部固定孔與 LCD 邊框（2026-09-16）

- 原始 `tft-wired-sequence-01` 12秒111張配對圖片：全部 searching，93次 model_missing。第一張 TFT 分數0.163低於0.20，但四角信心約0.90；原框偏移，兩孔因反光缺少藍色而漏掉。屬於模型外觀與幾何定位問題，非相機或雲端斷線。
- TFT Webcam 仍用原模型／CUDA，每個週期只推論一次。新增0.08候選通道，不改原0.20預設門檻、其他模組或Eye。低分候選不能直接畫GPIO，必須通過當幀固定孔／LCD幾何；高分模型缺孔時仍保留原共識路徑。
- 固定孔以局部自適應明暗、鍍環形狀及藍色PCB佐證；不能要求每一孔周圍都藍色。四孔模式同時確認LCD矩形；既有姿態只限定600ms內的搜尋區，每次必須重新取得當幀影像證據。未取得證據不回傳舊座標，相機／序列／逾時會清空。
- 接線遮住一孔時，新增 `tft_panel_geometry`：完整LCD四邊＋至少三個不同的可見固定孔，聯合單應矩陣投影缺少的一角。LCD相對固定孔的內縮比例來自現有清楚照片，屬於此模組的近似幾何，不是精密腳位標定。`missing_corner` 明確記錄為投影，不宣稱第四孔可見；缺兩孔或LCD不完整不能走此路徑。
- 保留原始TFT幾何觀測不讓光流覆蓋；兩張當前幾何一致後重建光流錨點。沒有只延長舊框；未更動腳位定義、實際接線、模型權重或相機控制。
- 最終回放：四孔接線片段 **0/111 → 109/111**（`tft-wired-final-replay2.json`）；重啟時新增的一孔被線壓住片段，原上線四孔版 **0/110 → 最終107/110**（`tft-partial-panel-probe7.json`）。兩段都參與開發，**不可當成獨立驗收或97%以上GPIO準確率**。三張疊圖目視位置接近固定孔；沒有GPIO接觸真值。
- 第二段CV與追蹤離線耗時中位18.5ms、P95約34ms，不包含YOLO、圖片讀取與UI延遲，不能當作端到端FPS。低分通道單次CUDA／OpenCV推論、候選失敗拒絕、三孔＋LCD、兩孔拒絕、空板／空背景、當幀移動、全遮擋、重置、HC與Eye隔離等 **252項相關測試通過**。
- 嘗試既有照片SIFT匹配第二段僅1–2對，未採用；沒有新增參考權重或要求使用者重拍。
- 最終版已重啟（服務PID3680）。`runtime-tft-panel-final` 實際1920x1080照片可解碼，目視Pi／超音波／已接線TFT清楚；平均亮度125.8、P99=179，與重啟前相機控制完全相同，同幀錯配0。此快照Pi/HC/TFT均locked，TFT回傳8個腳位。
- 重啟後再取12秒即時TFT模型來源：**107/110 locked、3 stale**（`tft-panel-live-final/sequence.json`）；82次四孔路徑、28次LCD輔助路徑，配對錯誤0。這是目前接線／靜態場景的即時結果，不是快速手持或全面90%驗收。
- 可重跑：`backend/.venv/Scripts/python.exe tools/replay_tft_wiring.py runs/acceptance/2026-09-16/<sequence-folder> --candidate-geometry --out <new-report.json>`。首次將候選推論快取於該資料夾，後續重播使用相同原始照片與時間戳。舊基準JSON保留，不用新程式冒充舊版重現。
- 尚待：不同角度手持／反光／背景的獨立短片驗收；不能承諾完全遮擋仍精確定位。

### HC 原拍攝特徵與高品質快速重新定位

- 只改 HC Webcam。原模型、權重、藍框／腳位幾何、Pi/TFT/HW 與 Eye 路徑不變；未新增訓練資料、未改曝光、未要求重拍。
- 診斷 `probe_hc_reference_views.py` 比較同一張既有參考的原拍攝、拉正與四種縮放視圖：拉正匹配12/34，原拍攝18/34；其他視圖沒有額外覆蓋，因此不增加多視圖的即時計算。
- HC profile 選用 `descriptor_space: native`：在原照片的PCB裁切／藍色遮罩內取 SIFT 描述子，只把特徵座標轉至共同 PCB 座標。其他 profile 預設仍是 rectified。匹配／分散覆蓋／方向／幾何門檻保持。
- 新增高品質單張重新定位：同一 frame_id 的當前 `hc_reference_sift` 結果，已通過參考幾何，且至少32內點、內點比率≥0.80、板面覆蓋≥0.30、重投影中位誤差≤0.8px時，可直接 seed。其餘維持兩次參考確認／影像共識，不沿用舊證據冒充新匹配。視覺幾何支撐沿用原政策，不把膚色比例單獨視為遮擋；完全遮住時不能取得參考匹配。
- 主比較 `hc-synchronized-held-01`：舊版7/34 locked → 僅原拍攝特徵12/34 → 加高品質單張16/34；舊版七次均保留。分母是模型觀測，**不是顯示可用性或GPIO準確率**。此片為開發診斷集，不是獨立驗收。
- 另一段既有 `hc-held-sequence-02` 未用作參考圖或參數挑選：2/36 → 4/36 → 8/36。它只有稀疏模型圖片，沒有中間畫面，不能推論連續追蹤幀率；僅是額外回放檢查，不是跨場地驗收。
- 七張既有人工粗標註中，新版鎖定六張、23個可見角，平均2.4px／最大6.3px；舊版鎖定四張、16角，平均3.0px。**不同覆蓋且標註約5–8px不確定性，不能把3.0→2.4當精度提升**。另目視12604、68592、68633，板框大致符合板面；沒有新增GPIO真值。
- 255項相關回歸測試通過，涵蓋四方向座標、鏡像／局部貼片／空白拒絕、舊 frame_id 不採用、弱參考不能單張鎖定、完整遮擋不能取得匹配與其他模組不啟用。
- 報告：`hc-reference-views-probe.json`、`hc-native-reference-replay.json`、`hc-native-strong-reference-replay.json`、`hc-rectified-reference-secondary.json`、`hc-native-reference-secondary.json`、`hc-native-strong-reference-secondary.json`、`hc-native-corner-review.json`（皆在 `runs/acceptance/2026-09-16/`）。
- 可重跑舊版條件：`tools/replay_hc_acquisition.py <folder> --reference --rectified-reference --two-image-reference --output <new-report>`；新版省略兩個比較選項。`hc-native-baseline-reproduced.json` 再現7/34。工具不修改 runtime profile。
- 已重啟，`runtime-hc-native-reference-01` 原圖1920x1080、平均亮度131.5，同幀錯配0；目視三種零件清楚，該顯示影格 Pi/HC/TFT 均 locked。API已回報 `descriptor_space: native`。四秒呼叫頻率快照 Pi23.6、HC7.5、HW9.2、TFT9.2次/s，非受控前後性能比較。
- 尚有模糊／傾斜時匹配不足及覆蓋過窄；靜態場景的模型路徑也仍會回報 reference支撐不足／model_image_disagreement，即使顯示光流當下保持locked。不能宣稱手持已全面穩定或90%達標。

### HC 定位誤差量測與參考／光流交接修正

- 本輪僅修改 Webcam HC 交接；Pi/TFT/HW/Eye、模型及曝光設定不改，不要求重新錄製。
- 修正三處：光流不再蓋掉供連續確認使用的原始參考觀測；連續兩張參考確認後重新 seed 光流；舊 anchor 逾時時保留 400ms 內的新參考確認。相機／序列重置仍清空，單張參考不直接覆蓋可信光流。
- 固定 `hc-synchronized-held-01` 回放：**5/34 → 7/34 次模型觀測 locked**；新增 frame12634、12645，原先五次鎖定均保留。這不是畫面顯示率、GPIO 正確率或新 10Hz 排程的現場驗收，回放不模擬推論耗時。
- 新增 `pcb-review-labels.json` 與 `tools/measure_hc_corner_error.py`：人工目視標註七張、27個可見 PCB 角；被遮角不猜測。標註約5px不確定性，frame12645有模糊、約8px，僅供粗略診斷，非訓練資料或GPIO真值。
- 原模型七張平均角點誤差20.6px；參考匹配成功的四張平均3.0px，**兩組覆蓋不同，不能直接當改善幅度**。前後均鎖定且有標註的兩張平均均2.3px；新增兩張鎖定的可見角點平均約3.7px、最大7.9px，目視板框跟隨，但在標註誤差範圍內，不主張精密改善。
- 232項相關回歸測試通過（含四項交接／重置新測試）；尚未達90%手持可用性。剩餘缺口集中在模型角點與參考匹配覆蓋，不能靠提高更新頻率或延長舊框遮掩。
- 報告：`runs/acceptance/2026-09-16/hc-handoff-before.json`、`hc-handoff-after.json`、`hc-corner-review.json`。
- 已重啟，`runtime-hc-handoff-01` 原圖為1920x1080，目視三種零件清楚、正常亮度（灰階均值128.0），同幀錯配0；此靜態單張 Pi/HC/TFT 均 locked，非手持验收。四秒模型呼叫頻率快照為 Pi23.3、HC7.7、HW9.2、TFT9.2次/s，皆 CUDA backend；場景與系統負載未控制，不當作前後性能比較或全算子GPU證據。

### Webcam 零件更新速度

- 修改前5秒計數差：Pi約29.2次/s，HC/HW/TFT各2.8次/s。模型locate均值約15–22ms，但每次工作後另等300ms。
- Webcam component worker排程週期上限100ms，週期扣除實際處理時間；超時不排隊，下一輪取最新畫面。Eye direct等待路徑、模型／輸入大小／信心門檻保持不變，Pi排程不改。
- 重啟後5秒實測：Pi30.0、HC7.6、HW9.2、TFT9.2次/s。這是模型呼叫頻率，不是成功鎖定率；HC有參考比對與影格銜接成本，未保證10Hz。
- 51項相關測試通過。`runtime-components-10hz-01` 實際1920x1080畫面可解碼，同幀錯配0。手持精度仍未驗收。

### HC PCB 參考紋理定位試行：有有限改善，尚未達標

- 新增 `tools/replay_hc_acquisition.py`，使用已保存顯示影格與離線重跑後快取的原始模型角點。基準34次模型觀測0次locked；PCB-only光流候選仍0，已撤回。
- 採不同拍攝片段 `hc-motion-inspection-02/source.jpg` 作獨立參考，目視指定PCB角點，複製為 profile 的 `webcam-pcb-reference.jpg`。SIFT參考特徵限制在藍色PCB附近，避開大部分突出的金屬探頭與背景。角點為目視估計，不是GPIO實測標定。
- 新模型仍負責限定搜尋區域；參考匹配必須符合既有雙向匹配、至少16內點、分散覆蓋／三象限及重投影條件。HC Webcam連續兩張當前參考匹配才能建立幾何交接；缺匹配回到原模型與共識路徑，沒有把舊框當新結果。
- 同一手持回放由0/34提升5/34 locked，**仍遠未達90%且不是實際腳位準確率**。12/34張能通過參考匹配，並非全部可鎖定。離線回放略過實際推論延遲，不能替代現場驗收。Pi/TFT/HW/Eye路徑不啟用這個HC參考交接。
- 報告：`hc-replay-before.json`、`hc-replay-pcb.json`、`hc-replay-reference.json`；參考逐張匹配證據在 `hc-synchronized-held-01/reference-trial.json`。本輪不要求再拍相同影片。

### HC 同步手持錄製：改善未通過

- `hc-synchronized-held-01`：12秒271張顯示畫面、34張配對模型來源；顯示全為searching。顯示來源跳過82個相機影格ID，最大間距3，沒有配對／順序錯誤。不是完整30fps相機錄影。
- 模型28次awaiting_consensus、6次skin_on_component；視窗18次collecting、9次semantic_disagreement、1次window_not_consistent。
- frame12656有29張中間影格、4次模型觀測，但對齊後前後半視窗差9.38px仍不通過。證明中間影格路徑已運作，不能宣稱修好；也不能只從semantic_disagreement判定角點順序翻轉，可能包含模型位置變動或光流漂移。
- 最後一張照片板面清楚且在手掌前。下一步使用本段做同幀幾何誤差分析，區分模型角點誤差與影像變換誤差；不要求使用者重拍相同動作。

### 同步證據錄製已可用，追蹤改善尚未通過

- 使用者回報中間影格修改「無感」，不得視為手持驗收通過。
- 新增 `tools/record_tracking_evidence.py`：並行保存 `/api/tracking/frame` 的原始JPEG及同影格顯示定位、`component-source` 的PNG及同影格模型處理結果。兩條串流依各自frame_id保存，不假裝不同時間結果是同一幀。
- 3秒連線測試保存65張顯示影格、9張模型來源，無配對錯誤；顯示影格ID略過20張、最大間距2。這是latest-only顯示來源錄製，不是無遺漏30fps相機錄製。模型資料為後處理結果，非原始YOLO角點。
- 4項錄製器測試通過，資料位於 `synchronized-recorder-smoke-01`。尚未錄製修改後的指定手持失敗動作，沒有新增定位準確度結論；未改Pi/TFT或重啟服務。

### HC 重新定位中間影格銜接（待實體移動驗收）

- `hc-held-sequence-02` 保存12秒36張模型配對原圖：36張searching，33 awaiting_consensus、3 skin_on_component。相鄰模型來源平均344.7ms；主要光流中斷，不能僅靠放寬角點誤差。
- HC Webcam worker 的模型間等待期間消費最新相機影格，讓 ImagePoseWindow 逐影格累積影像變換。FrameBus仍維持latest-only，不新增影格佇列，不增加YOLO推論次數；推論本身耗時仍可能跳過影格，並非保證每個30fps影格都處理。
- 中間影格不增加模型確認票數、不發佈GPIO、不延長辨識有效期；遮擋、尺寸改變、重複／逆序、超時或光流失敗則清空視窗。模型確認仍需4次。Pi/TFT/HW/Eye等待路徑保持原樣。
- 60項相關測試通過；合成序列驗證21張中間影格銜接4次模型觀測，另驗證失敗清空與無模型不能初始化。未宣稱手持精度達標；已存的模型稀疏序列沒有中間影格，不能用內插圖冒充實際回放驗證。

### TFT 手持交接試行（尚未實體驗收）

- 保存 `runs/acceptance/2026-09-16/tft-held-inspection-01/source.jpg` 與同幀資料：螢幕清楚、hand_fraction .0569、visible_fraction .869，重新定位殘差7.642px超過3px，92支持點；runtime TFT handoff 原為 false。
- Webcam TFT 啟用既有影像對齊視窗及視覺連續性。四孔修正失敗時回退既有當前模型／局部修正，仍須方向、材質及連續影像共識，不虛構被遮住的孔，不直接將舊框當成新辨識。
- 保留3px影像共識門檻，優先用對齊後多幀估計減少模型抖動；未放寬成7.6px。Pi、HC、HW與Eye程式分支未改動。
- 29項相關測試通過，包含無四孔觀測的移動抖動合成序列。單張實拍診斷及合成測試不代表手持對準率；偏移與快速移動恢復待現場驗收。

### 最新：HC 近距離影像對齊共識採尺寸相關門檻

- Webcam motion_handoff 的 HC 使用 max(原門檻, min(6px, 對角線1.5%)) 作為影像對齊後的模型殘差門檻；原始四角／無影像支撐的共識門檻不變，四次確認仍保留。
- 53項相關測試通過，包含尺寸上限、其他模組不變，以及無影像支撐不能接受4.7px連續位移。非實拍準確率驗收；需以剛才近距離握法確認。

### 最新：實際 HC 捏邊畫面確認被膚色 gate 擋住

- 使用者保持手持時擷取：模型信心 .749、hand_fraction .1248、reason skin_on_component。保存圖 hc-held-diagnosis/source.jpg 可見雙探頭，原圖離線 raw corners 的雙圓環檢查通過。
- 只限 motion_handoff 的 HC：手部比例小於 .20、藍板至少 .25、模型信心至少 .60 且雙探頭圓環符合時，允許捏邊例外；其餘幾何、方向、重定位與材質條件保留。Pi/TFT/HW/Eye 原設定不變。
- 89項相關測試通過，包括同一保存圖的狀態機回歸（靜態圖重複輸入，不是獨立連續影片）、無圓環與較大遮擋拒絕。已重啟試用；快速移動仍待實測。

### 最新：HC-SR04 與 TFT 手持恢復／短時預測試行

- 使用者指定僅擴充 HC-SR04、MRD-TF240；HW-123 與 Eye 不改。各零件獨立預測歷史，120 ms／15%對角線上限不變，預測為 stale、非辨識且不可供雲端裁圖。
- 兩種零件失鎖時可用同身份、同runtime、新locked的配對原圖重新seed，再驗證当前影格；正常追蹤時不因新模型抖動重置。不是套用 Pi 40-pin 幾何或更換模型。
- 前端兩種零件預測框呈虛線並標「預測補位 · 非辨識」。68項相關測試與前端build通過；尚無這兩種零件的新舊實拍準確率比較，不宣稱手持驗收通過。

### 最新：Pi 失鎖期間允許以新模型原圖重新建立追蹤

- 只在 recovering、同 Pi/runtime、locked 且含腳位與輪廓、來源晚於最後有效追蹤且距上一處理影格不超過250ms時允許。強制讀取模型配對原圖，不用目前畫面配舊座標；新 seed 失敗不破壞舊 anchor，成功後仍需當前影格 LK 檢查。
- 同片固定模型快取／模擬150ms延遲：手持 GPIO 529→559／1362、完整40pins 418→451、板框605→630；花紋205／226、線遮244／247、白底248／252不變；三段空背景均0。同幀錯配0。
- 71項相關測試通過，已選用於 Webcam Pi；其他零件不啟用、背景搜尋仍預設關閉。報告 `runs/acceptance/2026-09-16/fresh-recovery-comparison.json`。
- 這是既有素材的顯示可用性改善，沒有GPIO實體真值，不是90%驗收，也不代表所有快動作已穩定。

### 最新：背景廣域搜尋＋預測搜尋區域候選，預設關閉

- 新增單一背景工作，獨立 ORB/幾何副本、不累積工作佇列；150 ms 過期、重新 seed、不同 flow 的結果丟棄。候選必須在當前影格再通過原 LK/幾何檢查，不能直接畫上 GPIO。
- 以兩個可信光流姿態短時預測搜尋區域中心，120 ms / 板對角線 15% 範圍內使用；不變更 GPIO 真值或雲端判斷。僅 Pi 候選，其他零件不改。
- 69 項相關測試通過。同片按原時間間隔回放 `S05-Pi-handheld-01`，固定主模型快取、模擬150 ms模型延遲：1362幀中有GPIO 529→528、有板框605→595；單物件前景處理p95 41.64→12.06 ms；同幀錯配均0。
- 結果：降低前景阻塞但未提高追蹤可用性，故 `background_recovery_enabled=False`，不重啟、不替換現場版本。原有同步路徑維持。報告：`runs/acceptance/2026-09-16/background-recovery-comparison.json`。
- 此為單物件、既有素材、無實際GPIO真值的工程比較；不能當端到端速度、準確率或獨立驗收。背景工作的排程會影響回放數據。

### 最新：依使用者要求恢復 GPIO 局部顯示判斷

- 撤回上一輪 full-header 顯示政策，恢復 `pi_geometry_debounced_partial_support`：板面部分支撐且局部外觀不足持續三幀才隱藏，恢復也需三幀；外觀單獨改變不隱藏。
- 59 項相關測試通過。保留先前追蹤交接、120 ms 顯示預測與其他修正，不修改智慧眼鏡。

### 最新：Pi GPIO 不再依局部外觀逐腳位隱藏

- 依使用者要求取消三幀局部遮擋／恢復的顯示判定。Pi 40-pin 幾何引導統一顯示有效且位於畫面內的腳位，policy 為 `pi_geometry_full_header`。
- 整體失鎖、期限與畫面邊界仍保留；不代表插孔可見或接線已確認。其他零件、Eye 路徑不修改。
- 59 項相關測試通過，重啟套用。此變更取消局部顯示閃爍，不宣稱已解決整板追蹤失敗。

### 最新：使用者授權的 120 ms 顯示預測試行

- 僅 Webcam Pi display worker，在兩個完整可信追蹤輸出間估計四角移動趨勢；短暫 LK/support 失敗最多補 120 ms，位移限制為板對角線 15%，出界／反轉／逾期拒絕。單純四角外插不是完整 3D 運動模型。
- 預測輸出 stale、predicted、display_only、recovering，蓝色虛線與「預測補位 · 非辨識」標記。不是當幀影像證實的座標，不回灌 MotionTrack 或模型，不延長 lease。雲端裁圖明確拒收預測定位。
- 57 項相關測試及前端 build 通過，已重啟。需重新整理前端取得標記。現場快動作改善尚未驗收。
- 尚未加入預測導引搜尋與平滑接回；重新辨識成功即採用可信座標。此階段只測試短時顯示連續性。

### 最新：拒收 Pi 單幀錯誤候選，不直接清空有效光流

- 現場診斷曾有 4170 處理影格、76 超預算；Pi 在模型資料年齡 63 ms 時亦因 boundary/corner rejection 消失。因此不能只歸因於效能。
- 僅 Pi 已有追蹤時，`pcb_boundary_unverified` / `corner_box_inconsistent` 改為拒收本次模型候選，不 reset 現有光流、不採用候選座標、不延長確認期限。當幀 LK、幾何、影像支撐、時效與方向限制仍生效；其他零件維持原行為。
- 55 項相關測試通過，包含拒收後移動座標仍跟隨、無法用錯誤候選初始化、遮擋隱藏與期限到期。這是程式測試，手持實際效果尚未驗收。

### 最新：光流優先接回與失鎖紀錄

- PlanarFlow 一般 LK 失敗後，先使用清楚 anchor 進行原有 LK/幾何檢查，成功即跳過廣域 ORB；兩者失敗才搜尋。未放寬門檻、未保留失效座標。
- `/api/tracking/frame` 新增 `tracking_diagnostics`：最近 24 次狀態轉換、原因、模型資料年齡、處理時間及超出更新預算的影格數。原因計數是各物件影格累計，非準確率；重新啟動／相機上下文重設後清空，不保存影像。
- 52 項相關測試通過。已重啟；`runtime-anchor-first` 實際畫面 1920×1080、平均亮度 130.44、同幀錯配 0，Pi 恢復 locked，新診斷欄位確認可讀。
- 尚未做廣域搜尋非同步背景化，也沒有正常速度實拍新舊比較；不能宣稱已完全解決快動作。先利用近期狀態紀錄找下一個失鎖原因。

### 最新：Pi SIFT 重新搜尋加速（已啟用、重啟）

- 僅 Pi hybrid fallback 的 SIFT 搜尋影像長邊限制為 960 px；相機仍為 1920×1080。特徵座標先還原至原圖，再進原有 Homography/PnP 幾何驗證；沒有降低匹配門檻，其他板與 Eye 路徑不變。
- 固定 A/B：`runs/acceptance/2026-09-16/pi-sift-speed-960.json`。同一批既有影片與主模型快取，手持 locked 93 → 105／181，花紋維持 28／30，線遮擋與白背景各 31／31，三段空背景仍 0 誤鎖。stale 未計入成功。
- 手持後段處理 p95 310.57 → 227.24 ms、花紋 284.44 → 132.56 ms；手持 p50 45.00 → 47.29 ms，並非所有時間都下降。此數據不含快取的主模型推論，不能當作端到端 FPS 或 GPIO 跟手延遲。
- 相關測試 80 passed；最終全套 1317 passed、2 skipped、3 個既有失敗（boundary rejection 測試替身缺 body 欄位），沒有宣稱全綠。
- 重啟後確認 CUDA、`reference_sift_frame_max_px=960`、1920×1080 實際非黑畫面、同幀錯配 0；快照位於 `runtime-after-sift-speed`。智慧眼鏡、HC/HW 交接與 TFT 設定未修改。
- [ ] 尚待一次正常速度「拿起→移動→轉向→放回」現場驗收；105／181 是偵測器鎖定數，不是 GPIO 精度或 90% 可用性。尾端延遲仍存在，不宣稱已完全解決快動作。

- 不修改智慧眼鏡模型、路徑或設定。Eye 直接 YOLO 路徑不使用本次調整的 reference fallback。
- 不換模型、不新增訓練資料。重用 9/13 的 Pi 手持、三段背景正例及三段空背景，使用 9/15 同一份主模型輸出快取；逐圖 SHA、時間戳、模型與設定均核對。
- 保留 HC／HW 昨天已啟用的交接修正；TFT 不變。
- 不操作接線、供電、部署或雲端檢查。

## 發現與實作

1. 昨天「參考圖搜尋＋移動交接」是組合候選。本次新增獨立 A/B 開關，單獨測移動交接，Pi 手持仍為 68/181 locked，未改善，不啟用。
2. Hybrid 主定位回傳 stale 時會提前返回。新增只接受同影格、同時間戳、含腳位與板框的 fresh fallback 候選；既有回放沒有改善，因此維持關閉，不當成已解決手持問題。
3. 真正得到改善的是 **Pi 備援的深藍色 ROI 裁切**。原 ORB 雖能在裁切失敗後搜全圖，但 SIFT 救援仍只搜深藍色區域；綠色 Pi 可能被排除、反而搜尋 HC／TFT。Pi hybrid fallback 現在不使用這個顏色裁切；其他板子保持原預設。
4. 原有匹配、內點分布、Homography／PnP 幾何門檻及 SIFT 每 N 次失敗的重試預算都保留。沒有用低信心或舊框冒充新定位。
5. 補上移動 gate 拒絕影格時清空 ready 座標，以及成功交接時板框／wire-exclusion 使用同一份幾何。此 gate 本輪仍未在 Pi 啟用。

## 同片 A/B 結果

以下為 detector 輸出的 locked 數，不是 GPIO 真值精度，也不是最終瀏覽器可見率。

| 片段 | 影格 | 原版 locked | 修正版 locked |
|---|---:|---:|---:|
| Pi 手持 | 181 | 68 | 93 |
| 花紋背景四零件 | 30 | 0 | 28 |
| 雜物／線遮擋 | 31 | 31 | 31 |
| 白背景 | 31 | 31 | 31 |
| 灰空背景 | 30 | 0 | 0 |
| 花紋空背景 | 30 | 0 | 0 |
| 雜物空背景 | 30 | 0 | 0 |

手持 searching 108 → 81、stale 5 → 7；失敗區間保留，未將 stale 計入成功。

計算成本仍有限制：手持後段處理 p50 約 114 → 62 ms、p95 約 439 → 469 ms；花紋正例 p95 約 58 → 303 ms，花紋空背景約 92 → 320 ms。這是離線、不含主模型推論的處理時間；期間亦有其他工作，不能當現場 FPS。全圖 SIFT 救援有尖峰，下一步需確認恢復延遲與計算預算，不能只看 locked 數。

## 測試與啟用核對

- 最終相關測試：**134 passed**，包含 Pi factory 範圍、Eye 隔離、同影格 fresh fallback、拒絕舊座標及顏色 ROI／SIFT 重試預算。
- 全後端曾跑 **1302 passed、2 skipped、3 failed**。三項為既有 `test_pi_boundary_rejection.py::test_bad_primary_only_yields_to_fresh_feature_lock` mock 缺 `body`，未改生產契約來掩蓋。其後 factory 啟用及範圍測試另行通過，未再重跑全套。
- 已重啟 Board Vision；`/api/inference/status` 回報 `board.reference_color_roi_enabled=false`，Pi 推論仍 CUDA。HC／HW handoff true、TFT false。
- 重啟前後相機影像均解碼為 1920×1080，平均亮度 128.76 → 127.96，P99 224 → 223，同影格錯配 0；七項 UVC 回讀數值與旗標一致，config SHA 未改。
- 已查看重啟後實際 JPEG，非黑畫面。靜態快照 Pi 40、HC 4、HW 8 pins，TFT searching／0 pins。WebSocket 重新連線；未做瀏覽器 GPIO 對準或手持現場驗收。

## 證據

目錄 `runs/acceptance/2026-09-16/`：

- `pi-handoff-only-v1.json`：交接單獨 A/B，未改善。
- `pi-fresh-fallback-v1.json`：fresh fallback 候選 A/B，未改善。
- `pi-color-roi-v1.json`：採用的顏色裁切 A/B，七段正／負例。
- `runtime-before-pi-roi/`、`runtime-after-pi-roi/`：相機原照、參數與同影格資料。
- `runtime-pi-roi.stdout.log`、`runtime-pi-roi.stderr.log`：重啟紀錄。

回放工具：`tools/replay_pi_boundary.py --pi-color-roi-comparison`；保留 before 的舊裁切與 after 的修正，避免程式預設改變污染比較。

## 下一步與未完成

### 最新：Pi GPIO 顯示改為幾何引導，取消外觀單幀隱藏

使用者再次確認無遮擋仍因角度閃爍後，已修改並重啟：

- 只套用 Webcam Pi 完整 40-pin 引導；不動其他模組與 Eye。
- 板面目前影像追蹤有效且語義定位未過期時，單純外觀比對失敗不再隱藏 GPIO。
- 板面追蹤為 partial 且當地外觀同時失去支撐，連續三個影格才隱藏；連續三幀恢復才顯示。這是疑似遮擋訊號，**不是可靠的手部／線材遮擋分類器**；沒有宣稱可判斷所有遮擋。
- 定位過期、整板失鎖、目標移除的原限制保留；Pi 腳位超出實際影像邊界仍不顯示。沒有延長舊座標期限。
- API 明確標示 `pin_visibility_policy=pi_geometry_debounced_partial_support`、`pin_evidence=projected_geometry_not_contact_verification`。顯示的是幾何推算腳位，不是插接／接觸驗證。
- 新增外觀變化不隱藏、局部支撐三幀消抖／恢复、完整 40 腳整合／過期／失鎖測試；相關套件 **112 passed**。本輪沒有重跑全後端。
- 已重啟確認新 policy 實際生效，静態輸出 40 pins；1920×1080 原圖已查看、同影格錯配 0，七項相機設定／旗標未變，WebSocket 已重連。
- 證據：`runs/acceptance/2026-09-16/runtime-before-pi-visibility/`、`runtime-after-pi-visibility/` 及 `runtime-pi-visibility.*.log`。
- 真實手持角度閃爍與遮擋恢復的複驗仍待完成；以下 J8 小平移紀錄是前一步，不代表這次已驗收。

### J8 局部對齊已實作並重啟（手持回饋後）

- 僅 Webcam Pi 40-pin 模板啟用。其他模組保留原比對；Eye 不使用此 MotionTrack 路徑。
- 原本單一取樣位置未通過時，在目前板面投影附近搜尋整排共同平移。半徑最多追蹤影像 2 px，且不超過最近腳距的 22%；不允許每根腳各自找鄰近紋理。
- 至少 24/40 腳通過原外觀門檻、覆蓋排針長度 70%、比原位置增加至少 6 腳，才採用修正。其他腳仍逐一檢查，遮住的不能因共同對齊而顯示。
- 輸出的 GPIO 座標跟隨量到的偏移；內部板面座標與原始模板不被累積修改，下一幀重新從當前影像比對。未加入自動模板學習，避免把手／線材學入。
- 新增 `test_j8_local_alignment.py`：已知 2 px 位移恢復 40 腳、局部遮擋仍隱藏、整腳距錯位／全遮擋／小片可見不接受、鄰腳距離限制、輸出座標不累積漂移。與原遮擋、已錄紋理變換、MotionTrack、Eye 路徑測試合計 **108 passed**。未在本次重跑全後端套件。
- 合成 40-pin fixture，先熱身 10 次再量測 100 次：對齊檢查 p50 約 4.71 ms／p95 約 6.92 ms（不是整機 FPS 或實拍準確率）。
- 重啟後實際 JPEG 正常、1920×1080、同影格錯配 0；七項 UVC 參數／旗標一致。靜態快照 40 pins、local offset [0,0]，只能證明新輸出路徑與靜態正常，**尚未證明手持消失已修好**。
- 證據：`runs/acceptance/2026-09-16/runtime-before-j8-alignment/`、`runtime-after-j8-alignment/` 與 `runtime-j8-alignment.*.log`。
- 下一步只複驗先前手持姿勢；若偏移非整排共同小平移（例如較大視差／反光），仍可能隱藏，需另核對，不能宣稱任何角度皆完成。

### 手持 GPIO 消失已重現（本輪現場回饋）

使用者回覆「現在」後，已保存 `runs/acceptance/2026-09-16/pi-gpio-now-01/` 的原照及同步資料。照片中 Pi 完整在畫面內、手托住板子，J8 排針可見。

- 首張：板面光流 100 內點、support ratio 1.0；定位來源僅 62 ms 前，輸出 14 pins、隱藏 26 pins，原因 `partial_pin_support`。
- 隨後約 6 秒 136 個不同影格：17 幀 0 pins／`pin_region_changed`，其餘 119 幀只有 1–7 pins／`partial_pin_support`。
- 確認本次消失是在後端 `PinRegions` 局部外觀判定後就已隱藏，不能歸因於瀏覽器畫太慢，也不是首張定位資料逾期。
- `PinRegions` 將每腳附近固定 17×17 取樣區依板面 Homography 映射，比對舊模板；相關係數等條件未通過就隱藏。手持傾斜的視差、反光與模板／腳位對齊誤差各占多少尚未分離，不直接宣稱某一項是唯一根因。
- 下一個修正焦點改為 J8 局部對齊與模板更新條件，先不再調整 YOLO 搜尋或直接降低整體外觀門檻。本次只擷取與診斷，尚未修正此 GPIO 消失問題。

- [x] 找到上游搜尋區域問題，完成既有影片 A/B，選擇性啟用並核對重啟。
- [ ] 一次 Pi 短測：正常拿起／輕轉／放回，觀察藍框與 GPIO 跟手、偏移及恢復。无需重拍整套資料。
- [ ] 量測最終 GPIO 的位移誤差與跟手延遲，不能用本報告 detector locked 代替。
- [ ] 進一步整合 Confidence／Outlier／影像交接與 One Euro；本輪未新增四角平滑或模糊 gate。
- [ ] TFT 反光及局部遮擋初次定位仍未解決。
