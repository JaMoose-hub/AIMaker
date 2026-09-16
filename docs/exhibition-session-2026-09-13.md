# 2026-09-13 三小時集中優化工作單

## 16:47 接線過程準確性（未驗收完成）

使用者要求每次接線過程仍準確辨識，不接受僅靜態框顯示。因此擴展驗收到接近／線遮擋／小幅移動／移手後恢復；**不宣稱每次保證或任意角度已达90%**。

- 先重放原始保存序列，無新相機或雲端呼叫：3個60秒手持片段以300ms間隔取樣、3組10秒雜物線遮擋片段。從正式ComponentPoseWorker執行，同一模型raw observations缓存、照片SHA256及來源幀／時間戳保持配對。
- `S04-process-components.json` 原版手持：HC184幀locked1/stale6/searching177；HW184幀1/6/177；TFT183幀1/6/176。主要awaiting_consensus（155/130/162幀）要求四次幾乎不動，與手持移動衝突；另有model_missing、手遮擋、HW角序不明。
- 新 `vision/motion_consensus.py`：在連續清楚候選間以局部LK／RANSAC證實PCB實際移動，前後有分散特徵且非partial，四角最大殘差≤原3px才延續原4幀計數。無速度外推、無加大搜尋，沒有調低手遮擋／模型閾值。模型角序錯或抖動仍會拒絕；新 `pose_quality.reacquisition` 可追蹤誤差與計數，缺影格不攜帶舊證據。
- `S04-process-components-motion.json` 同輸入重放：HC仍1/6/177；HW變16/36/132（4次reacquired）；TFT仍1/6/176。線遮擋固定片段不退化：HC31/31locked，HW30/31locked＋1stale，TFT29/31locked＋2stale。**不是足以滿足手持需求的改善，不能把軟體修正當手持驗收通過。**
- `S04-process-pi.json`：使用 `replay_pi_boundary.py --reference-only` 執行當前完整Pi主／備定位；手持181幀locked68/stale5/searching108，線遮擋31/31locked。沒有Pi before對照，不計改善率；取樣回放不是整條同步顯示管線。
- 查實拍：手持片段包含零件靠近鏡頭與大幅转動。HC/TFT移動時模型角點與影像特徵的差距常超過3px，未以提高容忍度硬算通過。剩餘方向與精準定位問題保留，不回填手持完成。
- 新10項測試涵蓋三模組邊移動邊重新鎖定、錯角序／錯位置／全遮擋／時間倒退／重複幀／間隔失效；全量後端1028 passed，52.98秒（1項既有httpx棄用警告），前端本輪未改。
- 已重啟部署本機版本（啟動器36972、服務49672，`gpio-process-backend.*.log`）；`S04-process-postrestart` 固定擺位5秒111幀，四件各111/111locked、22.2FPS，確認未破壞原固定接線顯示。這仍是靜態複驗，非現場接線循環。瀏覽器保留原藍色GPIO及人工12/14；已重載頁面連接新服務。
- 下一步：現場先做Pi30秒正常接線動作短測，不拔線；再依HC、HW、TFT各做相同測試。逐件核對實體腳位位置及手移開恢復時間，目標9/10循環、1秒内恢復、偏差小於半腳距；未標註真值不能填準確率。已向使用者詢問是否準備好，尚未記為現場完成。

## 最新交付 16:33：接線後恢復原藍色 GPIO 疊圖

使用者澄清「不是多綠色框，是一樣藍色、GPIO能顯示」。16:10只做本體框屬需求誤解，不是 GPIO 完成；以下历史保留。

- 本輪基線 `S04-gpio-restore-before`：58幀中 Pi/HW 均 searching，HC/TFT均locked；四件本體存在不能替代腳位。
- 移除 BodyOverlay／綠色狀態及其CSS，StatusBar恢復真實腳位定位狀態；停用 `body_fallback_model_path`，保留原 PinOverlay、ComponentPinOverlay、共用同步串流和手動12/14。
- Pi：handheld-v2找不到或幾何不一致時，舊Pi模型只提供搜尋ROI；原 `reference_captured.jpg`＋校準 mm_to_px 建立有方向參考。SIFT雙向比對、至少16內點、分布覆蓋≥18%且跨≥3象限、中位誤差≤2px、拒絕反射／異常幾何。只在有分散對應時回到既有GPIO投影／J8修正及時序路徑，不放寬原姿態閾值、不從框猜腳位。
- HW：原排針方向檢查不過時，用既有真實 `hw123-header-row.png`（先前16種旋轉／角序驗證）升格為profile內 `reference_header.png`，方向／來源寫在 `reference_pose`。本輪照片得到69/74內點、誤差約0.26px；舊方向檢查與新特徵法皆失敗才隱藏腳位。HC/TFT原定位不變。
- 模型ROI維持CUDA；SIFT/RANSAC與LK是局部CPU工作，沒有宣稱所有運算都交給GPU。Pi在同步實跑的一筆恢復耗時218.67ms，HW27.28ms；快速影像仍獨立更新，不能把SIFT速度冒充影片FPS。
- `tools/verify_gpio_reference_recovery.py`：Pi使用正式0.30物件閾值，4張既有接線照逐張清空時序，各有Pi40/HW8腳位；16張灰／白／圖案／雜物空背景無誤輸出。JSON：`S04-gpio-reference-replay.json`。不是20次現場獨立驗收，也不是逐腳誤差真值。
- 重啟後 `S04-gpio-restored-live`：10.031秒216幀，Pi/HC/HW/TFT各216/216 locked，逐幀可見腳位數40/4/8/8；21.53 delivered FPS，processing p50/p95=16/31ms、capture-to-response32/63ms（含存檔負擔）。已看到四件原藍框及腳位，無額外綠框；人工12/14未改。新服務PID45488／啟動器41220，`gpio-reference-backend.*.log`。
- 後端1018 passed（53.05秒）、前端78 passed、592語系key、build通過。新測試涵蓋旋轉＋線遮擋、空圖、鏡像、過度局部匹配、證據不跨幀、實拍參考可独立部署；仍屬軟體回歸。
- 未完成：移動／重新進畫面的實體恢復率、每支GPIO絕對位置誤差、任意背景或第一人稱泛化、雲端接線正確率與硬體導通。下一步只需短測移開再放回，不需重拆接線或重收整套背景。

## 歷史 16:10：本體框版（非使用者要的 GPIO 交付，已撤掉顯示）

使用者縮小本次目標：保持目前接線，先確保 Pi5／HC-SR04／HW-123／TFT 本體被辨識。暫停端點／雲端判讀，不要求拔線或追加接頭近照。以下原時間窗及15:37雲端紀錄保留為歷史。

- 基線 `S04-wired-body-before`：10.016秒239個同步畫面，Pi搜尋239/239；HC/HW/TFT各locked239/239。查原照，Pi大部分板面仍可見，但多條線遮住PCB／排針。
- 原handheld-v2模型同照最高object score約0.12且框偏，不放寬0.30閾值。90／180／270度及局部取圖未改善。既有Pi專用 `board-pose-pi5.onnx` 同照約0.919能框住本體；其四角不準，因此**只取物件框，不替換GPIO姿態模型**。另兩個generic板模型雖約0.94，框錯物件，未採用。
- Pi備援0.55閾值、原影像CUDA前處理／CUDA device0獨立工作線最多2.86Hz；三模組在原推論結果的方向檢查前保存本體框，不增加三套推論。辨識與腳位狀態分開，UI四件狀態＋本體名稱，失鎖時只顯示本體框；StatusBar不再在本體存在時只說「搜尋板卡」。React檢查採共用同步串流、純衍生顯示與boolean狀態訂閱，未新增輪詢或相機串流。
- 來源幀與body結果原子配對；局部LK／RANSAC映射到当前JPEG，650ms來源時效、不外推／擴大搜尋。匹配失敗、重啟／解析度／revision變更清除，不讓body填入pose outline或pins，不改接線確認／部署。
- 中間版 `S04-wired-body-after` 留存：Pi本體181/223（81.17%），其他223/223。離線查缺失幀模型仍約0.92，主因body推論掛在耗時Hybrid特徵搜尋後，發布間隔大於時效。改為獨立工作線，**未延長650ms時效**；並測試相機333ms取樣與350ms工作排程不會雙重限頻漏一輪。
- 最終 `S04-wired-body-independent`：10.016秒221個同步畫面，**四件本體各221/221可用**，body frame錯配0；22.06 delivered FPS，processing p50/p95=16/31ms、來源到回應46/63ms（含JPEG磁碟錄製）。初版無body基線為23.86FPS，未宣稱加速。Pi named-pin仍searching221；HW named-pin locked150／searching71，但本體221/221，證明兩者分離；非逐Pin正確率。
- 補充離線抽樣：灰／白／圖案／雜物空背景各4張共16张，Pi備援均無檢出；原一般四件／目前接線照各4張都有Pi，白背景4/4，圖案四件僅1/4。**不據此宣稱多背景達90%**。這些為本輪讀取既有照片的模型輸出，非新訓練或人工真值評分。
- 全量後端1009 passed（47.60秒），前端78 passed、592語系key parity、build通過。新增來源配對、獨立工作線不受Pin失鎖影響、runtime切換、過期／移除／異常框、位移映射與相機取樣限頻測試；軟體測試不冒充實拍驗收。
- 服務已重啟：後端PID47872／啟動器49928，`body-independent-backend.*.log`；`/api/inference/status`明列body_fallback CUDA／GPU前處理，平均20.67ms（非逐operator GPU審計，LK仍CPU）。瀏覽器確認名稱／框對到四件，人工紀錄12/14保留，沒有觸發雲端或部署。
- 下一項只需短測四件各自移開再放回、觀察框消失／恢復；不重做整套背景與接線。任意角度、多背景、手持及第一人稱視角、精準Pin／整線判斷仍分開列未完成。

工作窗：台灣時間 10:56–13:56。這是時間上限與優先序，不保證九階段全部達標。
主驗收定義仍以 exhibition-demo-roadmap.md 為準；本日快篩不能代替其正式次數。
9/13最新指示：以約90%可用的Demo先推進，不再在單項反覆迴圈；依主清單「最新決策」執行。未達標如實列限制，不阻擋人工接線與雲端特寫流程。
零件固定 Pi 5、HC-SR04、HW-123、MRD-TF240；排除光敏電阻。第一人稱視角延後。

## 時間與交付

| 時間 | 工作 | 對應階段 | 交付 |
|---|---|---|---|
| 10:56–11:11 | 恢復服務、核對模型／相機、準備連續影格擷取 | 1、7、9 | 基線、版本、未完成項目 |
| 11:11–11:51 | 四件、空背景、換背景／光線、手持／遮擋集中收集；成像及校正前提核對 | 1–5、7 | 同步序列、具體失敗案例，不要求逐一現場修到通過 |
| 11:51–12:16 | 三組接頭特寫、插拔及人工答案；無辨識時操作檢查 | 6、8、9 | 原圖、實際端點答案、流程問題 |
| 12:16–13:16 | 重播案例、按根因批次修正與程式回歸 | 2–8 | 同案例新舊比較、未解決限制 |
| 13:16–13:26 | 修正版重啟與關鍵失敗現場複驗 | 7、9 | 四件啟動／恢復結果 |
| 13:26–13:56 | 核心流程驗收、可行時 20 分鐘連續展示、整理交付 | 9 | 可展示／未達標／下一輪清单 |

## 執行規則

- 每次只交代一段明確操作；先開始錄製，再叫使用者動作。
- 同一失敗有足夠同步證據後停止重擺，改離線診斷；最多兩輪相同現場複驗。
- 達到下一個時間分界即整理切換，不因單一 HW 問題吞掉全部時段。
- 固定案例用於開發；另留未調參數的實拍驗收片段。四件分別評分。
- locked 是系統狀態，不是人工認證的正確率；誤框、方向、Pin 誤差另評。
- 連續 JPEG 記錄包含磁碟開銷；效能正式量測關閉記錄。顯示影格不冒充上游模型同幀。
- 雲端比較只在已核對答案的小批照片先做，沿用選定模型；不在此工作單授權無上限雲端批次。
- 不自動部署或更改通電接線；視覺、連線、程式與硬體結果分開，不增加 Demo 操作門禁。
- 若缺校正板、硬體規格、人工答案或第二場地，標為待補，不悄悄刪除驗收條件。

## 當日基線

- [x] 起始 8100 未監聽，啟動現有後端後 PID 48852，首頁 HTTP 200。
- [x] `/frame.jpg` 可取得相機影像，保存 `runs/acceptance/2026-09-13/session-start.jpg`；HW 單件可見。
- [x] 設定 device / ffmpeg / 1920×1080，Pi 5 hybrid；三模組啟用。
- [x] `/api/inference/status` 四模型與前處理均 CUDA，fallback_reason=null；非全運算 GPU 保證。
- [x] 既有 `verify_motion_tracking.py` 新增可選 `--record-frames`。2 秒 smoke test 保存 40 張連續 JPEG 與 40 筆顯示結果，無缺圖，板卡結果 frame_id 配對；來源 `recorder-smoke-01`。這不是完整相機管線重播器，也不是正式辨識驗收。
- [x] 配對診斷：smoke-01 發現 1 筆 HW frame_id=0，原因是離線合成重播改寫了共用的第一筆結果；改以 deepcopy 隔離重播時間軸。smoke-02 的 38 張影像全部存在，四件共 152 筆顯示結果 frame_id 均匹配 packet。上游模型來源仍可能較舊，不與顯示配對混淆。
- [ ] 相機校正有效：目前 `camera_calibrated=false`，camera.json 缺失。API pitch=10.28px 為 Profile 檢查值，不是今日現場 Pin 精度。
- [ ] 瀏覽器渲染／互動、雲端實際判讀、部署與硬體功能尚未於今日驗證。

## 下一個使用者操作

目前不需要使用者操作：四件保持原位、不接新線、不通電。已完成本輪集中收集，轉入已保存素材的批次重播／根因修正；程式與回歸檢查完成再給下一個現場動作，不以「好了」代替實際驗收。
三組仍包含Pi↔HC、Pi↔HW、Pi↔TFT，但HW現場沒有排針，無法取得真實杜邦線插入排針案例；TFT已收未插照、已插例尚缺。這些及逐Pin人工真值、正式雲端裁圖／判讀繼續列待補，不延後12:16修正時段及13:56截止。目前尚未呼叫雲端判讀。

## 11:04 四件同場基準

- 使用者擺位確認：`four-parts-placement-01.jpg` 四件完整入鏡、未重疊、無手，未插線；板面／金屬部分反光，未以人為方法量測 Pin。
- 來源：`runs/acceptance/2026-09-13/S01-four-parts-baseline-01/`，10 秒、253 張顯示來源 JPEG、253 筆結果；四件顯示 frame_id 全部匹配。
- Pi：0/253 locked，253 searching，下游 reason 全為 `corner_box_inconsistent`；需離線釐清是候選錯誤還是拒絕規則過嚴，不能直接放寬。
- HC-SR04：226/253 locked（89.33%），27 stale / `awaiting_model_confirmation`。
- HW-123：243/253 locked（96.05%），10 searching，上游 `pin_orientation_unverified`。
- TFT：253/253 locked（100%）。上述是單次狀態占比，不是人工正確率或整階段通過。
- 25.3 delivered packets/s、capture-to-response p95 63ms；含記錄磁碟開銷，非相機到實際顯示端到端效能验收。
- 照片與失敗序列已收，不在此階段反覆調 Pi 擺位；下一步空背景。

## 11:10 灰色空背景負例

- 擺位照 `gray-empty-placement-01.jpg` 與異常配對影格 `S02-gray-empty-01/frames/000208.jpg` 均已實際檢視，無四件零件或手。
- `S02-gray-empty-01` 保存 10.031 秒、225 張 JPEG 與結果；無缺圖，四件顯示結果 frame_id 全匹配。
- HC、HW、TFT 各 225/225 searching；Pi 224 searching、1 stale、0 locked。
- Pi 異常 frame_id=23813，outline_only=true、0 Pin；上游 frame 23811 卻 locked/yolo、image_confirmed=true。這是背景上的疑似框，保留缺陷，不以「下游沒有 locked」當作完全沒有誤報；上游來源並非顯示影格同幀。
- 本樣本無持續 1 秒以上下游假鎖定，但仍有 1 幀背景輪廓異常，不能據此結案 Pi 全部假陽性問題。也未量測實際移出起點與清除時間。
- 22.43 delivered packets/s、capture-to-response p95 47ms；含記錄開銷。
- 下一步白色背景四件同場，延續集中收集而非逐案反覆重試。

## 11:15 白色背景四件同場

- 已檢視 `white-four-placement-01.jpg`：四件完整且未重疊、無手；白紙與部分金屬／腳位高光偏亮。相較灰背景，零件位置與部分方向也變更，非只換背景的嚴格 A/B。
- `S02-white-four-parts-01`：10.031 秒、252 張 JPEG、252 筆結果；無缺圖、四件顯示 frame_id 全匹配。
- Pi、HW、TFT 各 252/252 locked（100%）；HC 223/252 locked（88.49%）、29 stale / awaiting_model_confirmation。
- Pi 首筆 outline 範圍對應影像中 Pi 所在區域，但未做人工 Pin 誤差標註；不可把 locked 當作 Pin 正確率。灰背景 Pi 0/253 缺陷仍待修，本輪未改辨識程式。
- 25.12 delivered packets/s、capture-to-response p95 47ms，含記錄開銷。
- 附帶合成紋理重播 TFT 20 幀有 5 lost；這不是實體移動測試，單列待查，不以靜態 100% 掩蓋。
- 下一步保留白紙、四件移出，收白紙負例。

## 11:17 白紙空背景負例

- 已檢視 `white-empty-placement-01.jpg`：白紙上無四件零件或手。
- `S02-white-empty-01`：10.032 秒、216 張 JPEG、216 筆結果；四件各 216/216 searching，沒有 locked、stale 或非空 outline。
- 無缺圖，四件顯示 frame_id 全匹配；本輪白紙空背景未見下游誤框。
- 21.53 delivered packets/s、capture-to-response p95 32ms，含記錄開銷；並未測得實际移出起點至消框時間。
- 白紙負例樣本完成，不代表所有背景皆通過，也不覆蓋灰背景 Pi 缺陷。
- 下一步收有圖案背景四件同場；使用手邊現有背景即可。

## 11:19 擺位確認（尚未取樣）

使用者回覆好了後，兩次取得的 `pattern-four-placement-01.jpg`／`02.jpg` 仍只有空白紙，未見四件或圖案背景。串流 seq/frame_id 40579→40581 持續增加，但不以此單獨證明實體相機影像沒有停滯。未開始圖案背景測試，也未新增通過紀錄；請使用者核對相機視野與擺位。

## 11:23 印刷圖案背景四件同場

- `pattern-four-placement-03.jpg` 已確認四件完整、未重疊、沒有手；背景有藍色印刷圖案與文字。畫面高光偏亮，擺位與角度也不同於白紙樣本，不能將差異只歸因背景。
- `S02-pattern-four-parts-01`：10.016 秒、226 張 JPEG 與結果；無缺图且四件顯示 frame_id 全匹配。
- HC、HW 各 226/226 locked（100%）；Pi、TFT 各 226/226 searching（0% locked）。這是狀態占比，不是人工位置精度。
- Pi 全為 corner_box_inconsistent；TFT 下游全 recovery_timeout，上游全 insufficient_material，首筆 model_confidence=0.5685、visible_fraction=0.0147、hand_fraction=0.0435。照片中沒有真實手遮擋，不要求使用者重新擺到成功；離線須區分局部影像判定與模型姿態錯誤，暫不直接放寬門檻。
- 22.56 delivered packets/s、capture-to-response p95 47ms，含錄製開銷。
- 取樣後另保存 `tft-model-source-after-sample.json`：PNG 及模型结果同 frame_id=48698，此筆 reason 已為 awaiting_consensus，不能冒充前面 226 筆 insufficient_material 的來源。
- 下一步同一印刷圖案紙的空背景負例；仍按集中收集時程，不在此反覆修單件。

## 11:25 印刷圖案空背景負例

- 已檢視 `pattern-empty-placement-01.jpg`：無四件零件或手，印刷圖案與文字清楚可見，較前一四件樣本高光少；未據此推斷曝光變化原因。
- `S02-pattern-empty-01`：10.031 秒、217 張 JPEG、217 筆結果；四件各 217/217 searching，無 locked、stale 或非空 outline。
- 圖片無缺失，四件顯示 frame_id 全匹配。本輪圖案空背景未見下游誤框，不代表灰背景的 Pi 異常已修好，也未量測實際移出至消框時間。
- 21.63 delivered packets/s、capture-to-response p95 47ms，含錄製開銷。
- 下一步圖案背景加入四件與未插接線材／筆；先測旁邊雜物干擾，不與遮擋、實際接線混淆。

## 11:29 印刷圖案＋線材局部遮擋

- 已檢視 `clutter-four-placement-01.jpg`：四件完整入鏡、無手；鬆散杜邦線跨過 Pi 板面及 TFT 螢幕，未見筆，Pin 列沒有明顯插接。依實際場景歸類「雜物＋線材局部遮擋」，不當作無遮擋純背景驗收，也不是已接線端點驗證。
- `S02-clutter-wire-occlusion-01`：10 秒、247 張 JPEG 與結果；HC/HW/TFT 各 247/247 locked，Pi 247/247 searching，reason 全為 semantic_lease_expired。此訊息描述下游狀態，根因尚待離線查明。
- 無缺圖、四件顯示 frame_id 全匹配；24.7 delivered packets/s、capture-to-response p95 47ms，含錄製開銷。
- 未修改辨識程式，TFT 本輪成功不代表前一印刷背景失敗已修好；光線呈現、擺位與方向均有差異，非嚴格 A/B，也未標註 Pin 精度。
- 下一步僅移出四件、保留紙與鬆散線材，收集線材空景負例，之後轉入光線／手持素材。

## 11:31 印刷紙＋鬆散線材空景

- 已檢視 `clutter-empty-placement-01.jpg`：只見印刷紙與鬆散杜邦線，四件與手均不在畫面；線材擺位相較先前有移動，不推算實際移出至消框時間。
- `S02-clutter-empty-01`：10.031 秒、227 張 JPEG 與結果；四件各 227/227 searching，無 locked、stale 或非空 outline。
- 圖片無缺失、四件顯示 frame_id 全匹配；22.63 delivered packets/s、capture-to-response p95 47ms（含錄製開銷）。本輪未見線材造成下游誤框，不代表所有雜物皆能排除。
- 本輪已收灰底、白紙、印刷紙、印刷紙＋線材的正負樣本。這是集中快篩／開發素材，不是四背景×四件的正式十次冷啟動驗收；灰底 Pi 及其他失敗繼續保留。
- 轉入第 3 階段光線素材：先固定灰底四件的新擺位並取起始樣本，再保持位置比較照明；第 2 階段仍未勾選完成。

## 11:36 光線比較起始樣本

- `light-baseline-placement-01.jpg` 已確認四件完整、灰底、無印刷紙／鬆散線材／手；畫面較前一印刷場景暗。這是新的固定擺位，不拿不同擺位直接當作只改光線的 A/B。
- `S03-light-baseline-01`：10 秒、253 張 JPEG 與結果；Pi/HC/TFT 各 253/253 locked，HW 253/253 searching。無缺圖、四件顯示 frame_id 全匹配。
- HW 下游全 pin_orientation_unverified；上游顯示引用中 157 筆 pin_orientation_unverified、96 筆 awaiting_consensus。這是顯示幀計數，不是獨立模型推論次數。
- 取樣後另以既有工具保存 3 份真正模型同幀 HW 方向失敗 PNG／JSON，於 `HW-light-baseline-model-failures/`。後續離線重播用此批配對來源；不把它們冒充前述 253 幀全部失敗影像。
- 25.3 delivered packets/s、capture-to-response p95 47ms（含錄製）。沒有照度計或相機曝光實測，稱為本次起始照明，不宣稱特定 lux 或光線範圍達標。
- 不改辨識程式、也不要求 HW 換位置；下一步固定擺位，只增加照明。

## 11:40 較亮照明對照

- 已檢視 `light-brighter-placement-01.jpg` 及 `S03-light-brighter-01/frames/000000.jpg`、`000261.jpg`：四件仍在灰底相同擺位、無手／線材遮擋。
- 對比起始擺位照，以 OpenCV BGR→GRAY 在固定背景 ROI 量測：上方 ROI（正規化 x=.4–.6、y=.03–.12）平均灰階 57.85→72.75；下方 ROI（x=.4–.6、y=.85–.94）61.76→76.57，約增加 24–26%。全圖平均 63.47→78.29。這是影像亮度對照，非照度 lux，也未分離自動曝光的影響。
- `S03-light-brighter-01`：10.015 秒、262 張 JPEG 及結果；Pi/TFT 各 262/262 locked（100%），HC 250/262 locked（95.42%）、12 stale / awaiting_model_confirmation；HW 262/262 searching，下游全 pin_orientation_unverified，上游引用 252 筆同原因、10 筆 awaiting_consensus。
- 無缺圖、四件顯示 frame_id 全匹配；26.16 delivered packets/s、capture-to-response p95 47ms（含錄製開銷）。鎖定狀態占比不是人工辨識或 Pin 正確率。
- 加亮後 HW 仍全程方向未確認，故不能以「再開燈」當作已解決；保留起始照明的三份真正同幀 HW 失敗来源做離線追查。本輪未改辨識程式，亦不把 HC 單次差異歸因為光線改善。
- 停止同擺位重複光線快篩，接續四件各一段手持素材；維持 13:56 截止和集中修正時段。第 3 階段第二環境／照明範圍、第 4 階段校正仍未完成。

## 11:42–11:43 Pi 手持／傾斜／手指遮擋素材

- 準備照 `handheld-pi-ready-01.jpg` 確認 Pi 正面手持、整板入鏡，距離較桌面近，部分影像偏糊；Pi 與手遮到後方其他零件，不能把其餘三件的整段狀態當各自可見性驗收。
- 先啟動錄製，再於工作中依序提示左右慢轉約 30°、前後傾斜約 30°、手指遮四分之一板面約 2 秒後移開並保持。這些角度／時長為指令，不是實測真值。
- `S05-Pi-handheld-01` 保存 60 秒、1362 張 JPEG 與结果；四件顯示 frame_id 全匹配、無缺圖。22.7 delivered packets/s、capture-to-response p95 47ms，含磁碟錄製開銷。
- Pi：475 locked（34.88%）、848 searching、39 stale。Searching 中 786 次 corner_box_inconsistent、55 spatial_support、7 lk_support；主拒絕分支與先前靜態失敗相同，具體根因待重播，不能直接放寬閾值。
- 實際檢視 frames/000000、000400、000750、001000、001361：拍到角度變化與手指局部遮擋。000400（16.86 秒）Pi 大部分正面清楚入鏡時 searching / corner_box_inconsistent；000750（32.235 秒）傾斜時 locked / partial_pin_support。001000（43.157 秒）亦 locked / partial_pin_support。未逐幀人工標註可見範圍與 Pin 誤差，34.88% 是整段混合狀態占比，不能當可見幀正確率或正式階段達標率。
- 最後 50 幀均 searching；末幀仍有手指遮擋且板上緣超出畫面，沒有得到可確認的「遮擋完全移開後固定露出」收尾，故本次不能報遮擋解除後恢復 p95。整段仍可用作開發失敗素材，暫不要求使用者重錄。
- 同場其餘狀態：HC 62 locked／105 stale／1195 searching，HW/TFT 各 1362 searching；場景有手及 Pi 擋住它們，不以此宣稱三件在完整可見時全面失效。
- 本輪未修改辨識程式，Pi 手持穩定性仍未達成；下一件 HC-SR04，接著 HW、TFT，按集中收集時段推進。

## 11:46–11:47 HC-SR04 手持／傾斜／單探頭遮擋素材

- `handheld-hc-ready-01.jpg` 已確認模組正面完整入鏡、雙手握邊。先啟動錄製才提示慢轉、前後傾斜，接著遮一個探頭數兩秒後移開、正面保持到錄完。角度與兩秒是操作指令，未以逐幀真值驗證。
- `S05-HC-handheld-01` 保存 60 秒、1492 張 JPEG 與結果，無缺圖、四件顯示 frame_id 全匹配；24.87 delivered packets/s、capture-to-response p95 47ms（含磁碟錄製）。
- HC 狀態：259 locked（整段 17.36%）、228 stale / awaiting_model_confirmation、1005 searching（983 recovery_timeout、22 lk_support）。上游被引用結果：1219 awaiting_consensus、126 model_missing、88 skin_on_component、59 無 reason。這是顯示影格引用次數，不是獨立模型推論次數；確認鏈與追蹤銜接待離線分段追查，不直接把原因全部歸為手遮擋。
- 已檢視 frames/000000、000400、000750、001000、001200、001491：有手持角度與透視變化，部分影像偏糊／反光；001000（40.094 秒）手指遮左側探頭時 locked；001200（47.937 秒）及末幀（59.781 秒）雙探頭露出但 stale / awaiting_model_confirmation。握持手仍在板邊，不稱完全沒有手。
- 最後約 10 秒（50 秒以後）247 幀有 97 locked、150 stale，收尾仍不穩。未標註遮擋解除的精確影格、不報恢復 p95，也不能將整段 17.36% 當可見幀正確率或 Pin 精度；這輪是開發素材而非正式階段通過。
- 同場 Pi 1240 locked／252 stale；HW 429 locked／3 stale／1060 searching；TFT 1492 searching。握持手與模組遮到其他零件，不以這些比例當其他三件完整可見驗收。
- 附帶合成平面紋理重播 HC 20/20 lost；這不是額外的實體手持測試，與首個 locked 種子品質／追蹤初始化一併留待離線診斷。
- 本輪未改辨識程式；已保存明顯失敗，不要求 HC 重錄。下一件 HW-123，最後 TFT，仍按三小時集中收集／批次修正規則推進。

## 11:49–11:50 HW-123 手持與方向失敗素材

- 準備照 `handheld-hw-ready-01.jpg` 晶片面與焊孔入鏡但偏糊。先啟動錄製，再提示向桌面退一些、慢轉、傾斜及短暫遮擋後保持；距離／角度／兩秒遮擋是指令，未當成已量測真值。
- `S05-HW-handheld-01`：60.015 秒、1467 張 JPEG／結果，無缺圖、四件顯示 frame_id 匹配；24.44 packets/s、capture-to-response p95 47ms（含錄製開銷）。HW 1467/1467 searching，下游全部 pin_orientation_unverified；上游引用 921 同原因、326 awaiting_consensus、167 model_missing、53 skin_on_component。是顯示狀態而非獨立模型推論統計，不以放寬方向規則冒充修正。
- 抽查 frames/000000、000400、000750、001100、001466：有距離／擺位與角度變化，750（30.75 秒）焊孔列已轉到上方，相比初始方向約轉半圈，並非只轉指定 30°。部分影像偏糊，手指覆蓋板邊／安裝孔，末幀仍部分遮邊；不能當作全程完整露出的定位測試或精確遮擋恢復驗收。
- 16.609 秒（400）及59.812秒末幀均 searching / pin_orientation_unverified。全程無 locked 種子，未產生 HW 合成追蹤重播，與「重播成功」區別；現有靜態真正同幀方向失敗 PNG／JSON 仍用於離線追查。
- 同場 Pi 1426 locked／41 stale，HC/TFT 各1467 searching；後方零件被手擋住，不作其完整可見驗收。未改辨識程式，不要求重錄；最後一件 TFT 後即轉接線資料。

## 11:52–11:53 TFT 手持／反光／遮擋素材

- `handheld-tft-ready-01.jpg` 四角及排針入鏡。先啟動錄製，再依序提示慢轉、前後傾斜、手指局部遮擋後保持，角度與遮擋兩秒僅為指令，非實測真值。
- `S05-TFT-handheld-01`：60 秒、1411 張 JPEG／結果，無缺圖、四件顯示 frame_id 匹配。TFT 1411/1411 searching / recovery_timeout；上游引用 1298 awaiting_consensus、74 model_missing、39 skin_on_component。這是顯示影格統計，不是独立模型次數；確認鏈／手持候選穩定性待離線查明，不能直接放寬門檻。
- 抽查 frames/000000、000400、000750、001000、001200、001410：有旋轉、透視與顯著反光變化，部分影格偏糊；50.672 秒（1200）手指覆蓋部分螢幕，末幀59.766秒螢幕中央露出但手仍握邊、上角被手指覆蓋，仍 searching。最後約10秒225幀全 searching，不宣稱解除遮擋後恢復 p95；整段未逐幀標可見性／Pin誤差。
- 無 TFT locked 種子，沒有 TFT 合成重播結果；23.52 packets/s、capture-to-response p95 47ms（含錄製）。同場 Pi 522 locked／58 stale／831 searching，HC/HW各1411 searching；TFT及手擋到其他零件，不將其比例作完整可見驗收。
- 本輪未改辨識程式。四件手持開發素材齊備，不代表手持驗收通過；結束此輪重複取樣，轉接線端點資料。較11:51切換目標晚約3分鐘，不延後12:16批次修正開始及13:56截止，不新增相同手持重錄。

### 手持批次待修摘要（全部已保存完整顯示來源序列）

| 零件 | locked / 總顯示幀 | 重點排查 |
|---|---:|---|
| Pi 5 | 475 / 1362 | corner_box_inconsistent；分離框角錯誤、手持成像與拒絕規則 |
| HC-SR04 | 259 / 1492 | awaiting_consensus 與追蹤確認銜接；露出後仍 stale |
| HW-123 | 0 / 1467 | pin_orientation_unverified；模糊、焊孔／安裝孔可見性與方向判定 |
| TFT | 0 / 1411 | awaiting_consensus 與 recovery_timeout；反光、模糊及手持姿態 |

各段包含動作／遮擋／不同可見性，上表只描述系統狀態，不是同條件模型準確率。未改參數或訓練；正式恢復時間、Pin精度、独立保留集驗收仍未完成。

## 11:55–11:56 HC 雙端未插接負例

- 已檢視 `wiring-hc-unplugged-ready-01.jpg`：Pi與HC在灰桌面並排、無手，两邊排針未插接，旁邊是橘／黃／綠／藍四色鬆散排線。TFT/HW不在畫面，不要求再放回、不作其辨識評分。
- `S08-HC-unplugged-01` 保存3秒64张顯示來源JPEG／結果；無缺圖、四件顯示frame_id匹配，首尾影像已檢視仍為雙端未插接。這是1個靜態案例，不是64個獨立案例。
- `visual-reference.json` 指向首幀及SHA256，記錄助手視覺確認的雙端無接頭；未冒充人工逐Pin真值。手動端點答案、正確插接／相鄰錯腳對照尚待補。
- HC64 locked，Pi47 locked／17 stale，屬物件定位狀態而不是線已接通；不以桌面HC成功覆蓋手持失敗。21.33 packets/s、capture-to-response p95 47ms（含短樣本錄製），非性能驗收。
- 本輪僅本機收圖，未送雲端，也未取得正式AI檢查的裁圖包。已確認既有 `/api/guidance/cloud-checks` 會直接進入最多3次雲端分段檢查，沒有擷取專用模式；後續使用現有流程與小批固定照片，不另建新雲端API。舊capture_groundtruth需互動標記且預設舊板排針，不直接拿來宣稱本次Pi端點已標註。
- 下一例單端GND已插、Pi端未插。線色只用於指定拍攝對象，不作接對證據；尚未要求Pi接線／通電／部署。

## 11:58–11:59 HC 單端接頭／Pi 未插對照

- 已檢視準備照與 `S08-HC-single-end-01/frames/000000.jpg`、`000062.jpg`：橘色線黑色接頭位於HC排針端部的一腳，其餘三根金屬腳露出；Pi排針裸露，橘線另一端在桌面。無手，HW/TFT不在此例範圍。
- 本機錄製3秒63張顯示來源JPEG／結果，無缺圖、四件顯示frame_id匹配。Pi61 locked／2 stale；HC63 searching，下游全 `recovery_timeout`，上游引用全 `insufficient_material`。此為待查失敗分支，擺位／方向也與未插例不同，不能直接斷言是插線造成。
- `visual-reference.json` 保存首幀SHA256與可見接頭事實；請求目標為GND，但標字反光、尚無獨立逐腳確認，`confirmed_component_pin=null`。不因腳號未定而抹掉可見接頭，也不因使用者回覆好了就把指令當真值。插入深度／導通未驗證。
- 21 delivered packets/s、capture-to-response p95 62ms（短樣本含錄製），不作性能驗收。63幀屬1個靜態案例；未呼叫雲端、未取得正式雲端裁圖包，階段8尚未通過。
- 下一步只補標字與接頭可讀的角度，保持Pi未接，不重複錄完整手持或等待鎖定才繼續；維持12:16批次修正及13:56截止。

## 12:03 HC 單端補角度參考照

- 已保存並檢視 `wiring-hc-label-ready-01.jpg`：模組已轉動，PCB及黑接頭交界較前照少反光；橘線接在排針端部，其餘三腳露出，Pi端仍未插，無手遮擋。
- 依模組正面方向與既有 `hc-sr04/vision_profile.json` 的VCC/TRIG/ECHO/GND順序，接頭位置與GND相符；小字仍未獨立逐字辨讀，參考JSON分列 `inferred_component_pin=GND`、`confirmed_component_pin=null`，不將方向推論當人工真值。保留原單端案例，不回寫為已確認。
- 同名 `.reference.json` 記錄原圖SHA256、可見接头與推論依據。這次只補1張原圖，未重錄手持／定位，未送雲端、未取得正式裁圖包，不算新增通過案例。
- 已對照Pi現有board.json及reference_captured.jpg：Pin6為GND、偶數外側排、從Pin1端數第3對；目前USB／網路孔朝左、GPIO朝下的照片對應外側排右起第3根。下一步請使用者核對HC的GND標示後，僅接橘線至實體Pin6、其他線留空且不通電，收雙端對照；不預先宣稱接線正確。
- 不再要求同一單端反覆調到辨識成功；12:16集中修正與13:56截止不延後。

## 12:08 HC 雙端插接外觀對照

- 已檢視 `wiring-hc-both-ends-ready-01.jpg` 與 `S08-HC-both-ends-01/frames/000000.jpg`、`000062.jpg`：橘線從HC端部接頭延伸到Pi GPIO右端附近的黑接頭，兩端均可見，其他三條線鬆置、HC其餘三腳露出，無手；HW/TFT不在此例。
- 已保存3.015秒63張JPEG／結果，無缺圖、四件顯示frame_id匹配；Pi/HC各63 locked，其他兩件searching不評分。20.90 delivered packets/s、capture-to-response p95 62ms，短錄製不作正式性能驗收。
- `visual-reference.json` 保存原圖SHA256、兩端接頭與橘色路徑可見事實。目標為HC GND→Pi實體Pin6，使用者回覆已完成操作；未提供獨立逐Pin標註，確切插孔及插入深度仍保留待核，不把指令或locked當真值。尚未送雲端／取得正式裁圖包／驗證導通。
- HC已有未插、單端、雙端三種外觀及1張補角度照片，不代表3個接線判讀通過。雙端例擺位／方向也改變，不用本輪鎖定來否定前一單端 `insufficient_material` 缺陷或證明插線改善辨識。
- 結束HC重擺，下一步同時放入TFT與HW、標字面朝鏡頭但不接新線，快速核對端點硬體條件；12:16切換離線批次修正，不延後13:56截止。正式逐Pin人工答案、雲端樣本量與其餘待補條件繼續保留。

## 12:10–12:11 TFT／HW 未插接與硬體條件

- 已檢視準備照與錄製末幀：TFT排針及旁邊標字可見、沒有接頭；HW-123可見未焊排針的焊孔列，沒有可供杜邦線插入的針，不能偽造已插對照。Pi／HC橘線保留，無手遮擋。
- `S08-TFT-HW-unplugged-01` 保存3.016秒73張JPEG／結果，無缺圖、四件顯示frame_id匹配；Pi/HC/TFT各73 locked，HW73 searching / pin_orientation_unverified。24.20 packets/s、capture-to-response p95 47ms（含錄製），不是端點正確率。原圖SHA256及硬體條件存於visual-reference.json。
- 收集到可重播失敗後不再要求重擺HW；TFT已插接、HW裝針後的已插接、逐Pin人工真值及正式雲端裁圖／判讀仍未完成。停止集中現場取樣，使用者暫不需操作。
- 開始批次診斷：先檢查HC/TFT重新鎖定是否被固定座標共識卡住，再查HW方向、Pi框角拒絕及既有負樣本。新增 `tools/replay_component_sequences.py` 以原時間戳重播現有工作緒，保存原始模型觀察值及圖片hash，讓改前／改後使用相同輸入；不是相機全管線或雲端重播。

## 12:16 起批次根因修正（非全部階段通過）

### 已實作

- **HW 暗藍PCB邊界**：實際失敗原圖的藍板HSV V約36，舊強藍遮罩V>=80留下不足100點；且四邊形色彩包絡會切過第一批焊孔。保留強遮罩優先，新增較暗藍色提案與最小外接矩形備選，仍須完整焊孔列、唯一方向及兩安裝孔證據。`HW-light-baseline-model-failures/1..3.png/json` 三組配對來源皆能恢复；第1組改前已實際重現None，不把三張當三種環境。
- **HW 附近藍色杜邦線污染**：`S08-TFT-HW-unplugged-01` 原模型框涵蓋右上HW及下方藍線，舊色彩集合外框被拉到y≈306，而板底約262。加入有限的分離色塊候選；形態學僅用來分組，邊界只採原始藍像素。分組提案另要求安裝孔在板上方的實際列、兩孔對齊，防止遮擋時縮框到晶片／焊點。早期分組試版曾破壞遮孔負例，已攔截修正，不套用該試版。
- **兩處CPU運算縮減**：material fraction僅轉換投影多邊形ROI；PCB修邊僅轉換模型ROI、遮罩保留零值halo及真實影像邊界條件。沒有改模型權重、信心門檻或把這些OpenCV運算宣稱為CUDA。
- **可重複模型／工作緒重播**：`tools/replay_component_sequences.py` 檢查模型hash、設定、來源圖hash、frame_id及時間戳，原始模型觀察值可快取重用。每>=300ms抽1張、冷啟動工作緒；這是開發重播，不等於原本25Hz下游追蹤或正式驗收。

### 改前／改後與負例證據

- 運算縮減前後 `batch-before-refinement-roi.json` → `batch-after-refinement-roi.json`，HC184、TFT183、HW184，共551張**完整輸出逐筆相同**。另有合成遮罩測試涵蓋各邊裁切，防止局部運算改變舊幾何。
- 同一1080p原圖、固定四邊形、OpenCV兩執行緒、110次捨前10次，material fraction舊全圖中位4.502ms/p95 5.414ms，ROI中位0.041ms/p95 0.045ms，比例值相同。只是單一函式微基準，不是整體FPS／CPU下降倍數。
- HW最後分組版本 `batch-hw-light-and-negatives-03.json`：一般光線23/30 locked、較亮28/31；TFT/HW未插場景由上一固定輸入版本0/9 locked變4/9 locked，仍2張方向未確認、3張等待共識。這是原始模型快取重播率，不是人工Pin正確率。
- 灰、白、圖案、雜物四個空背景各抽30張，HW全部searching、沒有locked/stale。仍不代表所有類別或所有環境的假陽性已解決。
- `batch-final-hw-handheld-01.json`：HW仍1/184 locked、3 stale、180 searching，其中125方向失敗。**手持未改善，不勾階段5通過。**

### 已排除的假修正與未解根因

- `batch-after-motion-01/02.json` 的移動共識／影像對齊試改最多只讓HC/TFT各增加1張locked，不能改善整段；已移除試改程式，原共識行為保留。這兩份JSON是失敗實驗，不是現行版本。
- HC手持第20張：實際HC在中央，原模型最高分卻位於旁邊HW，信心約0.355；同張CUDA與OpenCV CPU输出基本相同。真正HC候選約0.123低於0.25，屬候選身份／模型問題，不是GPU沒運作；不能只放寬移動或信心門檻宣稱修好。
- Pi `corner_box_inconsistent`：模型四角縮到板內／不合理時被拒絕，原規則亦攔截TFT或空背景的Pi誤候選。尚無獨立可靠的替代角點證據，沒有刪掉規則冒充提升。
- 正式雲端裁圖與判讀本日仍未執行；收集圖片不等於雲端已驗證。九階段原验收條件不變。

### 本批回歸／重啟

- 最終後端全套 **930 passed**（45.08秒，1筆既有httpx/Starlette棄用警告）；包含HW新增暗光來源3例、藍線干擾4方向、分組不造像素，以及ROI邊界等效測試。後續相機設定保存另跑相機相關72測試通過。測試通過不代表四件現場／九階段全部通過。
- 重啟前5秒 `S07-pre-batch-restart-01`：105張，HC全locked、HW/TFT全searching、Pi91stale/14searching。已檢視首張，TFT角度及線位置和12:11不同，因此不冒充與較早場景嚴格A/B。當時仍是10:56啟動的舊PID48852。

### 重啟後實際複驗與相機設定（12:38–12:46）

- 已停止本專案旧PID48852及其相機／app-server子程序，啟動新後端PID37256（venv啟動器23216）；保留其他程式。首頁200、WebSocket重新連線。4模型及前處理actual_backend皆cuda、fallback_reason=null，稍後四者inference_count均持續增加，非僅載入provider。沒有再次啟動訓練／部署／雲端判讀。
- `S07-post-batch-restart-01`：10.046秒242張，影像無缺失、四件顯示frame_id配對；Pi59locked/165stale/18searching，HC241locked/1stale，HW1stale/241searching，TFT144locked/98stale。**已檢視TFT首幀外框位置在桌面／線旁、不是左方真實螢幕，這些locked不能當成功。** HW稍早短暫有正確位置的外框，後續semantic_lease_expired。24.09 packets/s含錄製，非正式效能驗收。
- 重啟前後實物未大幅重排，但照片明顯變亮、金屬高光裁切。使用者明確回覆「剛剛是自動變亮的，我又調回預設」，不是使用者調燈。尚未取得變亮當下的驅動屬性，不能斷言是某一個曝光／增益值；以獨立相機重啟一致性缺陷追蹤。
- 恢復預設後 `S07-camera-default-restored-01`：5.016秒132張，無缺圖、四件frame_id全匹配。Pi/HW皆132locked，HC132searching/semantic_lease_expired，TFT132searching/recovery_timeout。已檢視同幀外框，Pi/HW位置對應實物，未測逐Pin誤差。26.32 packets/s、capture-to-response p95 47ms含錄製；不能用兩段不同設定、不同時長推算性能提升。
- 新增只讀 `tools/read_windows_uvc_controls.ps1`：不呼叫Set、不建啟動中的擷取圖、不協商解析度；直接讀取指定C920的UVC值與模式、失敗HRESULT。`camera-default-controls-01.json` 紀錄12:43實際曝光-5/manual、gain0、focus10/manual、亮度／對比／飽和／銳利128、白平衡5705/auto、backlight0，裝置枚舉index1符合既有設定。模式旗標依[Windows相機屬性介面](https://learn.microsoft.com/en-us/windows/win32/directshow/configure-the-video-quality)；null不作0解讀。
- **已保存、尚未重啟驗證**：config.yaml設lock_auto_exposure=true、exposure=-5、gain=0，僅保存使用者恢復後已存在的模式和值；focus10及自動白平衡保持不變。解析／相機測試72passed，依告知不再重開相機，因此不能宣稱下次開啟的硬體read-back已驗證。

### 舊模型交叉快篩（不切換現場模型）

- 新增 `tools/evaluate_pose_model_identity.py` 與 `model-identity-probe.json`；9張已檢視來源（部分前後影像相關），以助理粗略實物範圍查漏掉、錯位置及空背景原始候選。不同零件只評有標註部分，遮住／未標者不當負例。不是使用者真值、Pin驗收、代表性測試集或訓練集。
- `model-identity-results-01.json` 保存8個既有模型的SHA、圖片SHA、原始四角／框／信心及粗略判定。HC v2在5張正例中3張粗對應，但4張空背景有2張原始假候選；v3無這4張空背景候選，正例仍多錯位。其餘替代也沒有同時解決正／負例；不基於這個小樣本直接換權重。
- TFT `mrd-tf240-8p-cs-pose-v2-robust.onnx` 與現用檔SHA256完全相同（E196A72D…DFF99），換檔名不會改善；stage1另測但未達可取代條件。
- **下一優先序**：HC/TFT候選身份與局部重定位、Pi不合理角點的可靠替代證據；以已存原圖處理，暫不要求使用者再拍相同擺位。之後才驗保存的相機設定能否在重開後維持，以及正式雲端端點照片。所有未過項仍保留；本批只交付已實測的HW／CPU局部運算修正和診斷工具，不宣稱九階段已完成。

## 第二批：HC 重新鎖定＋相機重啟設定（12:57–13:15）

### 根因與已實作範圍

- `S07-HC-reacquire-before-01` 保存8秒181張，HC全searching，HW/TFT全locked，Pi全searching。這是新取樣，不能沿用前一次Pi119/119鎖定作目前結果。影像無缺失、四件顯示frame_id配對。
- 同序列每300ms選一張，24張同圖／同模型快取：原HC角點相鄰幀平均移動約0.3–1.42px；`blue_pcb`顏色輪廓修正反而跳3.79–44.70px。不是模型完全沒找到，而是後處理反覆打斷4幀共識。
- `bound_hc_corner_refinement`：只針對HC四角模型，顏色微調的每角及投影Pin位移均不得超過模型估算相鄰腳距的1/4；不符就保留原模型幾何。**這是修正幅度預算，不代表實體Pin誤差已小於1/4腳距。** 同時輸出`corner_refinement`證據，未修改共識／信心門檻及其他模組路徑。
- 白底HC金屬圓筒佔大面積，原blue fraction約.24低於.25。新增局部360×200雙圓筒證據：兩個位置／尺寸相符的亮環與暗芯、至少.12藍色支持、無明顯手遮，才補足啟動／重新鎖定的材質判斷。藍色基準值仍是原始量測，不把Hough分數混入歷史基準。這不是接頭／電氣驗證，也不是通用身份分類器。
- 不切換模型、不訓練、不改零件清單、不增加demo操作門檻；光敏電阻仍排除。

### 同輸入回放（不是現場逐Pin驗收）

最終檔案：`hc-regression-before-01.json`、`hc-recovery-before-01.json`、`hc-regression-after-03.json`。中間`after-01/02`是試驗，不是最終結果。

| 來源 | 張數 | 修改前locked | 最終locked |
|---|---:|---:|---:|
| 當前靜止HC | 24 | 4 | 24 |
| 白底四件 | 31 | 22 | 31 |
| 花紋四件 | 30 | 30 | 30 |
| 雜物／線遮擋 | 31 | 31 | 31 |
| 原照明 | 30 | 29 | 22 |
| 較亮照明 | 31 | 19 | 27 |
| HC未插／單端／兩端 | 各9 | 9／0／8 | 9／9／9 |
| 四組空背景 | 合计120 | 0 | 0 |

- 原照明案例locked減少，原模型自身有約13px雙位置跳動；新策略不以大幅顏色修正蓋過它。這項仍不達標，未宣稱所有光線皆改善。
- HC手持184張仍1locked／6stale／177searching，沒有改善，保留階段5未完成。
- HW184張、TFT183張與`batch-before.json`完整輸出逐筆相等。Pi本輪未改其定位程式；現場仍有間歇失鎖。
- 新增HC27項測試、原生UVC9項測試。最終全套 **966 passed**（43.70秒，1筆既有Starlette棄用warning）。

### 相機重啟缺陷：這次取得硬體值而非猜測

- 13:06第一次重啟載入HC後，`hc-fix-camera-before/after-restart.json`讀回：曝光仍-5/manual，gain從0→91、飽和度128→119、銳利度128→255，圖像變亮／雜訊增加。`S07-HC-reacquire-after-01`251張HC/TFT全locked，但HW215searching/36stale，Pi全searching；不能以HC成功忽略其他零件。
- 透過DirectShow屬性介面恢復原值，未開第二擷取串流。新增可選`native_uvc_controls`路徑，啟動前及正式FFmpeg收到第一張非黑影像後套用、整批讀回；舊OpenCV控制串流不再用於此路徑。helper先驗唯一装置／完整範圍，失敗記錄而不冒充成功、不封鎖demo。
- 保存使用者原值：曝光-5、gain0、focus10、亮度／對比／飽和／銳利128；白平衡維持auto。詳見[相機啟動設定](camera-startup-controls.md)。
- 13:12:42再次重啟，現行後端PID35912（啟動器8988），日志`native-uvc-backend.*.log`。13:13獨立只讀`native-uvc-after-restart-01.json`確認上述7個設定與模式都符合；`/api/camera/focus`的整批read-back verified=true。這是原生路徑 **1次** 重啟確認，不是階段9十次重啟通過。
- `S07-HC-native-uvc-after-01`10秒240張：HC/HW/TFT各240locked，Pi30locked/210searching；圖像無缺失、四件frame_id配對。已檢視原圖與瀏覽器，框線對應三種零件，不當作逐Pin真值；Pi仍須處理。
- 隨後靜止複驗 `S07-HC-native-uvc-settled-01`：10.015秒239個同幀結果，四件皆239locked；只保存種子／失敗參考圖，未錄製全部JPEG。代表這一段靜止畫面已恢復四件鎖定，不抹除剛重啟Pi失鎖，也不是239次獨立成功。每件20張已知影像變換重播均未失鎖，但不當作實體手持或逐Pin精度測試。
- 四個模型及前處理仍為CUDA、fallback=null；Pi/HC/HW/TFT inference_count升至690/177/171/171。局部Hough／幾何仍在CPU，不宣稱整条管線全GPU。24 packets/s含錄製，非正式性能提升數據。
- 瀏覽器重連後GPT-5.5及「AI檢查本步」恢復可用；本批沒有送雲端照片、重登入或執行部署。

### 下一個使用者動作與未完成項

接下來僅做一次HC「移動後放穩」複驗：同一背景、同一相機設定，把HC平移5–10公分並旋轉約90°，放下後手離開；無需重接線。它驗證的是重新鎖定，不是任意角度／完整遮擋已完成。

後續程式優先仍是Pi間歇失鎖、HC手持候選跳動／TFT誤框與局部重定位；已有素材先回放。四件動態、逐Pin精度、正式雲端端點真值與照片、第二環境、HW装針及完整重啟／長時間測試仍未達標；13:56截止不延後，未完成項不得勾成通過。

## HC 移動後複驗（13:20）

- 使用者完成平移／旋轉後才開始取樣；`S07-HC-moved-settled-01`保存10秒260張JPEG及成對定位結果，無缺圖、四件顯示frame_id均匹配。這不是移動全程錄影，不能量測從手離開到重新鎖定的時間。
- HC、HW、TFT各260locked；Pi86locked／160stale／14searching。HC上游在212筆下游紀錄中為locked，48筆為stale/awaiting_consensus；沒有將下游穩定顯示等同於每次模型皆成功。
- 已檢視原始同幀影像與瀏覽器：HC移到原圖左下方且長邊接近垂直，橘線仍連著、無手遮；三模組框線粗略對應實物。未量測逐Pin真值、沒有雲端判讀、不算正式10次重定位驗收通過。
- Pi失敗紀錄包含awaiting_model_confirmation及semantic_lease_expired；failure-001顯示局部光流仍有100內點、appearance支持尚在，但上游為stale，顯示層已隱藏40個Pin。尚不能歸因相機或板上線束，更不能直接延長舊Pin有效期作為修正。
- 下一個單一變因對照：Pi與其他模組位置、相機、背景皆保持不變，只把橫跨Pi板面的藍／黃／綠線束挪到板旁，橘色已接線保留，不拔接頭。這是確認線束干擾的診斷對照，不把「必須移開線」當最終Demo限制；階段6仍要求接線時可用。

## Pi 線束移開後診斷（13:24 起）

- `S07-Pi-wires-aside-01`：10.016秒251張JPEG／成對定位，無缺圖、四件顯示frame_id全匹配。Pi251searching；HC/TFT各251locked；HW244locked／7searching。Pi沒有locked種子，因此沒有它的合成重播，不能把缺項算通過。
- 已檢視首張：Pi中央板面露出，線束移到旁邊，橘色已接線保留，無手。但其他模組的位置亦有改變，不能宣稱嚴格單一變因A/B或量化線束的因果效應；只確認移開線束仍不足以恢復Pi。
- 下游251筆皆semantic_lease_expired，其中37筆引用上游locked/deadband、214筆引用stale/jump_hold。後續獨立8秒唯讀WebSocket樣本亦有57locked/deadband、73stale/jump_hold，並非上游從未產生定位。
- 上游locked例frame23299的框為[(659,280),(1884,280),(1884,1079),(659,1079)]，明顯過大且碰畫面底邊。以相同1920×1080幾何、0.5追蹤縮放重現`PlanarFlow.seed`回false/seed_outside_frame。此檢查在像素特徵之前即失敗；不把稍晚WS訊息與先前JPEG冒充同幀。
- 碼上`MotionTrack.observe`種子失敗時沒有把`flow.failure_reason`更新到`track.failure_reason`，所以對外仍可能報舊semantic_lease_expired；這是診斷可觀測性缺陷。不可藉允許越界框或延長Pin有效期掩蓋。
- 依實際Pi專屬confidence=0.30、keypoint=0.35、960/CUDA重跑首張，原模型四角已偏斜；顏色修邊又擴到x≈687..1776，而不是緊貼Pi。原有corner/box面積比檢查兩者均通過。冷重跑JPEG不是現場原始模型幀，不宣稱已完全重現變成邊界大框的時間序列。
- 詳細值保存`runs/acceptance/2026-09-13/pi-wires-aside-diagnosis.json`。本輪是現場驗證與診斷，**未修改定位程式、未重啟、未送雲端、未算此项通過**。
- 下一步轉程式處理Pi板邊候選擴張與種子拒絕原因，使用已保存的兩個擺位及既有空背景／TFT負例；使用者暫不需重擺、調光或重拍同樣場景。仍需實作＋回歸後才能再次驗收。

## 90% Demo 收斂：Pi 必要修正與首次正式雲端檢查（13:36 起）

使用者決定先以約90%可用推進，不再逐背景反覆修到完美；依主清單最新決策，保留失敗但切換下一項。此決策不是已測得90%。

### Pi 修正、同輸入回放與啟動確認

- Pi四角路徑的PCB顏色修邊新增候選證據：輪廓佔外接矩形不足0.65、或碰搜尋ROI邊界時拒絕該候選，回報`pcb_boundary_unverified`。新的拒絕狀態清除舊追蹤；只有新鮮locked特徵定位可接替，stale不能恢復異常大框。其他模組、Pi八點／UNO舊呼叫路徑不套用此檢查。
- `PlanarFlow.seed`分開回報幾何無效、越界、太小、紋理不足；`MotionTrack`同步本次種子失敗原因，不再沿用先前semantic_lease_expired。沒有放寬越界、延長舊Pin有效期或訓練／切換模型。
- 新增13項回歸，這批後端全套 **979 passed**（45.16秒；1筆既有Starlette棄用warning）。
- `tools/replay_pi_boundary.py`保存模型／照片SHA、原始模型快取與前後輸出；相同輸入、同一模型、每至少300ms抽一張，完整資料在`runs/acceptance/2026-09-13/pi-boundary-before-after-01.json`。白背景31/31 locked保持；灰空背景原2/30 locked改後0/30；HC移動場景24/30 locked保持，但4stale改searching；Pi線束移開場景原5locked/22stale/3searching改為30searching。**這是攔下錯誤候選，不是把該場景修到能找到Pi。** 花紋／其他空背景未因此恢復假鎖；未重跑手持驗收。
- 13:36:12重啟本專案後端為PID49100（venv啟動器4060），首頁與WebSocket恢复；日志`pi-boundary-backend.*.log`。相機原生UVC批次讀回verified=true，保存曝光-5、gain0、focus10及亮度／對比／飽和／銳利128。本批沒有另跑獨立DirectShow讀取，不冒充10次重啟驗收。
- 新取樣`S07-Pi-boundary-live-01`10.031秒240張：Pi192locked/48searching（80%狀態比例），HC/HW/TFT各240locked；不是獨立取得定位次數，也不是逐Pin正確率。23.93 packets/s含錄製，處理p50/p95為15/16ms、capture-to-response為31/62ms；不是無錄製FPS基準。**Pi仍未達本次90%目標，不再阻擋進入雲端檢查。**

### 真實雲端基線與人工答案

- 使用者明確確認橘色線為 **HC-SR04 GND → Pi實體Pin6（GND）**，不用重接；答案只用於評分，不加入雲端prompt。
- 實際按「AI檢查本步」，job `62b652ea045d4bfa9d47ecfc1ab376a6`，13:36:32取像、13:37:12完成，GPT-5.5／low，總40.16秒，兩次獨立端點呼叫；沒有schema錯誤。當下走overview退路，送的是 **1張1920×1080原圖，不是3張特寫**。短連拍8候選選第4張，畫質分數不作接頭正確證據。
- Pi端正確看到Pin6上的黑色接頭與橘線；HC端把朝右的排針當朝左，順序反轉，判橘線在VCC而GND空著。整條接線判為suspected_issue，與人工答案不符，**完整接線正確0/1**。沒有把Pi端正確或線色正確當整條答對。
- 已用現有工具保存原始照片、SHA、完整結果至`runs/acceptance/2026-09-13/S08-HC-cloud-overview-01/`，`ground-truth.json`只作評分。助理檢視保存的同一張全景：HC兩圓筒正面可見，排針根部在板心右邊，橘線接最上方；與前述方向誤判一致。
- 本次限定提示詞試驗：由既有vision_profile的左右腳序產生四方向對照，先要求定位PCB中心與排針根部，再取旋轉後腳序；背面／鏡像／地標矛盾不能硬套。HC/HW底側排針、TFT頂側排針分開處理；Pi仍用原來兩排計數規則。不新增第二份腳位表、不依線色或本次答案指定接到GND。
- 同原圖／SHA、同GPT-5.5／low、僅1次component端點回放`orientation-positive-01`仍誤認左右，還把旁邊黃色／綠色／藍色線當成HC已插的接頭。雖回`target/GND`，卻指錯位置及藍線，**判為失敗，不當正確**。本次無需再花額度做負例，停止此方向的提示詞迴圈。
- **已撤回該提示詞及其4項測試，未載入正式後端**；試驗prompt／request／照片／結果仍保存在fixture目錄。試驗版全套983passed只代表契約，不證明辨識變好；正式版本維持已通過979項的Pi修正及原雲端prompt。
- 下一步轉階段9頁面／操作流程快篩；保留雲端方向與接頭誤認、Pi未达90%為未解項。以後優先比較真正的模組局部特寫／較強推理與獨立測試集，不能只繼續加長prompt；今天不重拍已收背景，不自動重試到碰巧通過。

### 階段9：瀏覽器流程快篩與下一個現場動作（13:44–13:46）

- 已實際切換接線→Blueprint→製作步驟→設計→部署→接線，沒有重新產圖、套用待確認作品、改零件或清除進度。設計v5候選仍未套用，Blueprint／部署使用既有v1作品，符合確認後才更新的流程。
- Blueprint材料與製作步驟兩分頁可顯示；四個必要零件均保留。設計文字／圖片入口仍在；沒有重新生成或驗證新圖片品質。
- 部署頁顯示未連線、尚未部署，程式仍含HW/TFT未核實提示；本次沒有SSH登入、上傳、改程式或啟動硬體，不把頁面開啟當部署通過。
- 回接線頁，人工進度仍1/14；短期AI結果隨離開該頁卸載後顯示尚未檢查，原結果已另存fixture。沒有把此結果變化當新的AI判讀或抹除失敗證據。
- 在顯示「Pin定位暫停」時實際按開始接線，仍可手動繼續、AI全景按鈕可用。接著**依使用者明確確認的橘線GND→Pin6**按人工下一步；進度仍1/14、當前切至HC第2/4步TRIG→Pin11（GPIO17）。沒有代替使用者確認尚未接的線，也沒有把GND記為AI成功。
- 撤回雲端試改後，雲端契約＋Pi新增回歸 **40 passed**；最終正式Pi版本此前完整979passed。沒有再次重啟或改相機曝光。
- **現在只需使用者接一條HC-SR04 TRIG→Pi實體Pin11（GPIO17）**，使用不同於橘色的線方便核對；GND保留，VCC／ECHO先不動。接好回覆後往下一步，不重做背景／手持驗證。完整九階段、90%統計與硬體功能仍未完成。

### TRIG 人工完成與 ECHO 備料（13:48）

- 使用者回覆「好了」對應上一輪要求的HC TRIG→Pi實體Pin11（GPIO17）。已看目前瀏覽器與相機縮圖；能看見HC新增接線，但沒有用縮图宣稱數清兩端腳號，人工回覆才是本次進度依據。
- 在Pi仍顯示定位不足時，實際按「我已接好，下一步」，頁面2/14人工進度、HC第3/4步ECHO→分壓→Pi實體Pin12（GPIO18）；AI仍尚未檢查。這次未拍雲端、未改程式／模型、未重啟，不增加AI準確度樣本。
- 現有引導用330Ω串接ECHO至節點、470Ω由節點至GND，節點接GPIO18。先確認現場有這兩顆電阻與麵包板，不要求ECHO直接插GPIO；若缺料，留未完成、先進其他展示項目，不以此重跑辨識迴圈。GND／TRIG保留、VCC先不接。

### 兩顆470Ω替代分壓的備料確認（待接線／功能驗證）

- 使用者已確認有兩顆470Ω與麵包板。先準備三個互不相通的5孔接點組，以兩顆470Ω串接、共用中間節點；本輪只插電阻，Pi、ECHO、VCC均不新增接線，原GND／TRIG保留。放進鏡頭後再核對孔排，未按ECHO完成。
- 470Ω／470Ω在名目5V輸入時，理想中點為2.5V、總電阻940Ω、電流約5.32mA；這是電路計算，不是實測，也不是Pi5各條件邏輯輸入保證。現行程式／Blueprint仍是330Ω／470Ω，本輪沒有改共享零件表、UI或生成程式，不把現場替代值當原BOM相符。
- 已查[RP1官方資料](https://datasheets.raspberrypi.com/rp1/rp1-peripherals.pdf)與[Pi GPIO電壓文件](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#voltage-specifications)：不能把Pi4的VIH=2.0V表直接當Pi5。另[Adafruit接法](https://learn.adafruit.com/distance-measurement-ultrasound-hcsr04?view=all)示範等值電阻減半，但建議合計大於1kΩ；其使用10kΩ／10kΩ，並非這兩顆470Ω的完整背書。官方Pi舊教學亦有330Ω／470Ω較低總阻值實例；模組差異與Pi5實際輸入裕量仍待核對，不能只憑計算宣稱通電測試通過。
- 下一步僅檢視麵包板孔排與電阻連接，仍保持2/14人工紀錄；不因有兩顆電阻就接VCC、啟動部署或自動通過雲端。若今日只做展示，這段維持不供電示意；功能版的替代料／實測另列，不拖回背景辨識迴圈。

### 使用者略過ECHO分壓，轉下一模組

- 使用者明確要求「先跳過這個步驟」，停止麵包板／470Ω替代接法的現場準備，不再要求補拍電阻。
- 實際瀏覽器操作：展開「接線說明與紀錄」→「暫停並看總覽」→「下一模組」。HC總覽顯示2/4，進入HW-123第1/4步GND→Pi實體Pin9，整體人工紀錄仍2/14。
- 沒有按ECHO或VCC的完成確認，兩者保留未完成；原GND／TRIG人工紀錄保留。沒有改程式、模型、零件清單、供電或部署。
- 本輪只驗證跳過未完成模組仍可前進的UI流程，不新增雲端准确度或硬體通過紀錄。HW的實體排針／功能仍依原未完成項追蹤，不因跳到該頁就代表能插接或已完成。

### 「下一步」意圖校正：開始HW，再到TFT

- 使用者要求下一步後，助理誤解為也略過HW，曾操作開始→暫停總覽（0/4），但尚未按下一模組。使用者立即澄清HW-123與TFT都還沒做。
- 已按「回看」恢復HW-123第1/4步GND→Pi實體Pin9的active引導，整體仍2/14。HW/TFT沒有任何新增完成紀錄，沒有切到TFT，也未改實體接線、模型、供電或部署。
- 正確後續順序是帶使用者開始HW，完成相應實作後再做TFT；「下一步」不應再自動解讀成略過未做模組。HC目前只記GND、TRIG完成，ECHO／VCC尚未完成，使用者口語「完成超音波」不覆寫既有未完成證據。
- 目前螢幕縮圖不足以核實HW接頭／排針的機械連接；開始GND實作前須留意板上是否已焊好排針，不能要求把母頭硬插裸焊孔。不重收背景、不重跑整輪辨識。

### HW GND人工確認，進入SDA

- 使用者在單條杜邦線GND→Pi實體Pin9的指引後回覆「好了」。依此人工確認按下「我已接好，下一步」，瀏覽器已顯示3/14與HW第2/4步SDA→Pi實體Pin3（GPIO2 / SDA1）。
- 本次沒有執行雲端檢查，不把人工進度計為AI辨識成功或導通／硬體功能通過。HC ECHO、HC VCC與TFT仍未完成。
- 下一個操作只加一條SDA線，保留原有接線，HW VCC先不接；等待使用者接好再記錄，不自動跳過模組。

### HW SDA人工確認，進入SCL

- 使用者回覆SDA已接好，依其人工確認操作「我已接好，下一步」。瀏覽器顯示4/14與HW第3/4步SCL→Pi實體Pin5（GPIO3 / SCL1）。
- 下一個操作只加一條SCL線，既有GND、SDA及HC接線保留，HW VCC先不接。本次未執行AI照片檢查或硬體測試，不新增辨識通過紀錄；TFT與先前略過的HC步驟仍待完成。

### HW SCL人工確認，進入VCC接線準備

- 使用者回覆SCL已接好，依其人工確認操作「我已接好，下一步」。瀏覽器顯示5/14與HW第4/4步VCC→Pi實體Pin1（3.3V）。
- 下一步依既有引導，在Pi未供電時加一條VCC線到實體Pin1，不是Pin2的5V；原有接線保留，接好先不供電。HW晶片／驅動未核實，接線完成不可視為可上電或硬體測試通過。
- 本次未執行AI照片檢查、供電或部署。HW VCC尚未記錄完成；TFT與先前略過的HC步驟仍待完成。

### HW四條線人工記錄完成，開始TFT GND

- 使用者回覆HW VCC已接好，依其確認記錄完成；瀏覽器顯示整體6/14、HW人工4/4，且仍註明尚未整合功能測試。
- 操作「下一模組」與「開始接線」，已進入MRD-TF240 TFT第1/6步GND→Pi實體Pin20（GND）的active引導，TFT沒有新增完成紀錄。
- 下一個操作只加一條TFT GND線，保留HC與HW既有接線，保持未供電；TFT VCC／BLK先不接。本次未執行AI照片檢查或硬體測試，不把人工4/4計為HW功能驗證通過。

### TFT GND人工確認，進入SCL

- 使用者回覆TFT GND已接好，依其確認記錄GND→Pi實體Pin20。瀏覽器已顯示整體7/14與TFT第2/6步SCL→Pi實體Pin23（GPIO11 / SCLK）。
- 下一步只加一條TFT SCL線到Pin23，勿混用HW SCL的Pin5；原有線保留、保持未供電，TFT VCC／BLK先不接。本次未執行AI照片檢查或硬體測試，不新增辨識通過紀錄。

### TFT SCL人工確認，進入SDA

- 使用者回覆TFT SCL已接好，依其確認記錄SCL→Pi實體Pin23。瀏覽器已顯示整體8/14與TFT第3/6步SDA→Pi實體Pin19（GPIO10 / MOSI）。
- 下一步只加一條TFT SDA線到Pin19，勿混用HW SDA的Pin3；原有線保留、保持未供電，TFT VCC／BLK先不接。本次未執行AI照片檢查或硬體測試，不新增辨識通過紀錄。

### TFT SDA人工確認，進入CS

- 使用者回覆TFT SDA已接好，依其確認記錄SDA→Pi實體Pin19。瀏覽器已顯示整體9/14與TFT第4/6步CS→Pi實體Pin24（GPIO8 / CE0）。
- 下一步只加一條TFT CS線到Pin24；原有線保留、保持未供電，TFT VCC／BLK先不接。本次未執行AI照片檢查或硬體測試，不新增辨識通過紀錄。

### TFT CS人工確認，進入RES

- 使用者回覆TFT CS已接好，依其確認記錄CS→Pi實體Pin24。瀏覽器已顯示整體10/14與TFT第5/6步RES→Pi實體Pin22（GPIO25）。
- 下一步只加一條TFT RES線到實體Pin22；原有線保留、保持未供電，TFT VCC／BLK先不接。本次未執行AI照片檢查或硬體測試，不新增辨識通過紀錄。

### TFT RES人工確認，進入DC

- 使用者回覆TFT RES已接好，依其確認記錄RES→Pi實體Pin22。瀏覽器已顯示整體11/14與TFT第6/6步DC→Pi實體Pin18（GPIO24）。
- 下一步只加一條TFT DC線到實體Pin18；原有線保留、保持未供電，TFT VCC／BLK先不接。本次未執行AI照片檢查或硬體測試，不新增辨識通過紀錄。

### TFT六條線人工完成，轉入HW／TFT照片驗證準備

- 使用者回覆TFT DC已接好，依其確認記錄DC→Pi實體Pin18；瀏覽器與截圖均顯示整體12/14、TFT人工6/6。HW人工4/4已於前輪完成，剩餘兩步為先前暫緩的HC ECHO與VCC。
- 停留TFT模組總覽，沒有按「前往部署」、沒有新增AI或硬體通過紀錄；TFT VCC／BLK仍未接，保持未供電。
- 後續先驗HW、再驗TFT雲端接頭照片。請使用者露出HW與Pi兩端排針及接頭後方線色，保留既有接線、手移開後再取圖；人工接線答案只供驗收核對，不注入雲端作為照片觀察答案。這兩個模組的雲端檢查尚未執行。

### 15:00–15:04 HW／TFT各一例真實雲端快篩

- 使用者完成擺位後，先由瀏覽器查看畫面；Pi顯示定位不足。為不以「回看」刪除下游人工紀錄，直接使用既有`/api/guidance/cloud-checks`，沿用作品v1、GPT-5.5 low及目前Profile，不更換雲端API、不修改人工12/14。
- HW GND→Pi Pin9：job `467ca5c31ae84136a8f004a13f686d5e`，15:00:52取frame152271；62.81秒完成。零件／Pi／線路3段均只用`pi_overview`一張1920×1080全景。兩端uncertain，整線uncertain；相對使用者人工答案，本例0/1成功作答，並非證明實際錯接。
- TFT GND→Pi Pin20：job `e7735bc5f2bf499db64c548766d384fc`，15:03:07取frame156340；70.62秒完成。同樣3段、1張全景、沒有端點特寫。模型聲稱TFT GND已插，但Pi腳位未確認，整線uncertain，本例0/1成功作答。模型另聲稱TFT VCC位置有外殼，與人工VCC未接紀錄衝突，保留疑點，不能據此要求改線或宣稱TFT端正確率通過。
- 完整照片、圖片hash、原始stages與result保存在`runs/acceptance/2026-09-13/S08-HW-cloud-overview-01`和`S08-TFT-cloud-overview-01`；各有`ground-truth.json`記錄人工來源，未把人工答案灌入模型。未執行第二輪重試，不加總相近照片為多次独立成功。
- 已核對程式原因：`wiring_capture.capture_best_images`只有兩端`locate_capture`均成功才走端點特寫，否則整包退為全景；故全景的清晰度評分不代表接頭有足夠像素或可見。`cloud_connector_inspection.endpoint_prompt`與一致性判斷主要要求母頭直接覆蓋指定針脚，沒有表達麵包板同列間接連接的合適欄位。照片可見HW在麵包板上，但具體孔列／導通尚未獨立核實，不能直接當作模型誤判的唯一原因。
- 後續修正優先：端點獨立取圖或手動ROI，不依賴Pi整板locked且保留方向全景；再支援麵包板端點／孔列证據，仍由雲端判讀、未知則保留uncertain。此輪只是實拍檢查與診斷，沒有實作以上改善。使用者暫不需重接或重拍相同擺位；HC ECHO／VCC仍暫緩，未上電、未部署、未重啟、未訓練。

### 15:37 失鎖端點裁圖與麵包板契約實作／有界複驗

- [x] 保留原本有效定位的裁圖；缺端點特寫時新增一次同模型雲端區域定位，地端獨立驗證兩個框、從原始全景解碼像素裁PNG，保留全景與來源frame／crop紀錄。任何一端定位失敗不丟掉另一端。`context_crops`不冒充精準逐Pin定位，亦不因從未取得pose立即把結果標舊照。
- [x] 麵包板欄位：模組插入孔、跳線插入孔、可見性與編號／板型證據。支援同一A–E或F–J端子組的兩個不同孔；不同列、跨中央縫、電源軌或不可見插入仍待確認。沒有母頭直接套模組排針不再是唯一判準；所有觀察仍由雲端提出，本機只驗契約，不作線色辨識。
- [x] 保持按鈕觸發、模型GPT-5.5 low、原有接線／部署行為。最多增加一次定位呼叫（最多60秒），總流程仍210秒上限；端點／線路單段最多90秒、無自動重試。兩端未都確認target時跳過線路呼叫。前端顯示定位階段、最多3或4次、孔位證據。
- [x] 修正真实provider schema限制：首輪HW的ROI成功，但nullable `breadboard`未列required造成400，失敗輸出保留於`roi-breadboard-v1`。已明確列出全部required、移除default並保留bare $ref；舊結果本地反序列化仍可接受缺少新欄位。新增測試檢查完整schema限制。改正後完整雲端流程不再有400。

| 相同原照／相同模型 | 改前 | 新版一次完整複驗 | 結果 |
| --- | --- | --- | --- |
| HW GND→Pi9 | 1全景、62.81秒、uncertain | 定位6.27＋零件28.89＋Pi31.86＝67.02秒；保留全景及2端PNG／閱讀圖 | 仍uncertain；描述麵包板與線色，但孔列對應與Pi9未確認；Pi逐針盤點與接頭參照有矛盾，未採信精確腳位 |
| TFT GND→Pi20 | 1全景、70.62秒、uncertain | 定位11.89＋零件35.91＋Pi34.34＝82.14秒；保留全景及2端PNG／閱讀圖 | 仍uncertain；模型聲稱TFT GND target，但Pi20未確認；VCC／BLK盤點仍與人工未接紀錄有待釐清，不計端點驗收通過 |

- 新版時間為三個模型階段合計，不含啟動／檔案輸出；不是速度改善證據。每例實際3次呼叫，因端點未都成立，未追加route模型。每個端點模型收到自己的閱讀特寫＋原全景，定位模型只收到原全景；原始照片SHA-256未變。讀圖副本只是像素放大，遮住的針腳不會因此出現。
- 複驗檔案：`runs/acceptance/2026-09-13/S08-HW-cloud-overview-01/roi-breadboard-v2.*`、`S08-TFT-cloud-overview-01/roi-breadboard-v2.*`以及各自`*-views/`。看過HW特寫，模組／麵包板確實在裁圖內；未將黑色接头或可见线色当作孔位正确的证据。保留所有失败基线，不再刷同张。
- 後端全量997 passed（59.87秒）；前端77 passed、589個i18n key parity、build通過。涵蓋跨frame來源、錯框／小框／NaN／缺框、單端保留、逐像素裁圖、無重試、JSON schema、麵包板跨縫／不同列／同一孔／遮擋拒絕，以及新舊UI相容。這些是軟體測試，非997個實拍成功。
- 15:37:17重啟原8100服務，新後端PID36788（啟動器40276）；日志`cloud-roi-backend.*.log`。`/api/camera/focus`顯示camera_open=true、UVC verified=true：曝光-5、gain0、focus10，亮度／對比／飽和／銳利128，均manual旗標2。瀏覽器重新載入後12/14人工紀錄仍在；當前TFT介面回到第1步準備（既有暫態導引狀態），沒有清除已接紀錄，未按回看／開始接線／部署。
- [ ] 未完成：90%整線辨識、麵包板真实導通、TFT功能／供電規格、手動ROI UI。下一現場動作只需先露出HW GND插入孔與對應跳線孔的近照證據，不拔線、不重收所有背景；若今天不方便，這項保留限制，繼續Demo流程收尾。
