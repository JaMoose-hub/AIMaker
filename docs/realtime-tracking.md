# 即時追蹤試版（Pi 5＋HC-SR04＋HW-123＋TFT）

在鏡頭右上方「即時追蹤（試用）」切換；預設開啟。按鈕顯示實際收到並解碼的
追蹤畫面 fps；底部原有偵測速率／姿態狀態仍屬於慢速模型，不是同一個指標。
關閉可立即切回原本 MJPEG／快照＋模型標記。校正與光學 HUD 沿用原模式。
`backend/config.yaml` 的 `realtime_tracking: false` 可停用整個試版。

## 行為與邊界

- 保留模型工作緒、防抖與接線驗證。另起按需執行的顯示追蹤緒，最多 30 Hz，
  沒有客戶端讀取時休眠。Pi、HC-SR04、HW-123 與 MRD-TF240-8P-CS
  分別保有特徵、位置與失效狀態；遮住一個不會清除其他零件的追蹤。
- 只從 **locked 的同幀模型結果與來源影像**初始化。不從猜測位置啟動。
  延遲送達的模型結果會與其原始幀的追蹤歷史比較，而非直接蓋上目前畫面。
- 每幀使用 LK 前後向驗證與 RANSAC；至少 16 個有效內點，特徵須分布於
  板面而非集中在一個小區塊。異常形變、出框、影像間隔超過 350 ms、
  尺寸／相機序號／控制器版本改變均使追蹤失效。
- 局部支持不足時可走**外框專用**路徑：保留至少 16 個匹配、80% RANSAC
  內點一致率、至少 20% 板面特徵分布，以及原有前後向、形變與邊界檢查。
  不再因有效特徵少於原數量的 65% 就一律清框；不足以支撐幾何時仍隱藏。
  追蹤特徵少於清楚參考影像的 90% 時改為黃色虛線、`stale`、`pins: []`；
  回復至少 95% 才重新顯示 Pin，避免反覆跳動。這不是遮擋面積百分比。
- 局部追蹤持續對照遮擋前的清楚影像，不補入手上的新特徵。
  未達精準條件時只保留外框參考；接線卡與影像共用同一份顯示狀態，
  暫停高亮與確認操作，不沿用慢速模型或舊版的短暫 ready 寬限。
- 較快平移／旋轉使 LK 失敗時，以局部擴大搜尋的 ORB 雙向特徵配對提出
  位置候選，再對齊舊影像，重新通過嚴格的 LK 前後向與 RANSAC 驗證。
  不會只憑粗略配對就畫出 Pin；搜尋仍受板面形狀、位移與畫面邊界限制。
- LK 金字塔、參考影像變形與特徵擷取改在各目標的加邊局部區域運算；
  裁切原點對齊金字塔格點，所有回傳座標仍轉回原始影像座標。
  不降低相機解析度、內點數量、匹配一致率或定位門檻。
- 擴大搜尋每個目標至多每 200 ms 一次，全畫面每幀至多一次，
  輪替優先順序避免某個遮擋目標佔滿搜尋。一般局部追蹤仍每幀執行；
  清楚影像若能局部匹配，立即恢復，不必等待擴大搜尋的冷卻期限。
  需要擴大搜尋才能接回時，可能增加約 200 ms 的等待；不是硬即時保證。
  遮擋時不重跑同一張影像上已失敗的相同參考匹配。
- 在追蹤工作緒啟動階段預熱 ORB／數值函式，避免第一次重新搜尋時
  才載入運算核心。預熱資料不作為相機定位或硬體證據。
- 短暫失敗保留最近有效影像／特徵最多 1,500 ms，讓下一張清楚影像直接接續；
  **失敗幀不顯示舊座標**，不是把舊框延長顯示。超時仍需模型重新定位。
  此期限要求相機仍連續送幀，斷線／幀間隔超過 350 ms 不沿用。
  定期補充特徵只在支持度至少 97% 時進行，失敗不清除原有效資料。
- 原始模型的同幀候選四角只能延長追蹤資格，不能直接替換顯示或接線座標。
  若 2 秒都無模型佐證，停止 Pin 引導；仍有當前影像匹配時最多延續 8 秒
  外框專用追蹤，超時全部隱藏。遮擋失效時不外推位置、不沿用舊高亮。
- Pi 5 的顯示特徵老化可能一直低於 95%，即使另一條模型／J8 定位仍穩定。
  對此新增受限的參考影像更新：只在局部外框狀態且非失敗搜尋中，連續取得
  **三個不同來源幀**的 locked 模型結果，且獨立 J8 與板面影像各至少 95%
  特徵成立、90 百分位移不超過 1 個來源像素，才可重建顯示特徵。
  新模型的原始與已接受四角都必須通過原有同幀歷史幾何比對；確認間隔及
  來源影像相對最近有效追蹤幀的時間差均不超過 250 ms。
  使用模型**實際配對的來源影像**，更新失敗保留舊資料，重試至少間隔 500 ms；
  再以 LK 檢查目前顯示幀，避免模型影像之後才出現的遮擋被略過。
  單靠模型信心值／持續 locked 不會觸發；90%／95% 遮擋門檻不變。
  此路徑目前僅限具有獨立 J8 影像佐證的 Pi 5，不擴及其他模組。
- 本版沿用既有 J8／模組 Profile 的初始 Pin 位置，再隨平面變換移動；
  **尚未加入每幀獨立 J8 孔中心追蹤或完整 3D 遮擋處理**。
  大傾角、背面、嚴重模糊、接腳與板面高度差仍可能偏移。
- HW-123 保留排針方向驗證，允許整排共同平移最多正規化板寬／高的 4%
  搜尋焊點，不降低 7/8 焊點對比與方向唯一性門檻，不單獨挪動每顆 Pin。
  這只解決方向判定，不修改 Profile 腳位或宣稱電氣接通。
- TFT 模型的安裝孔座標會先經同一份 Profile 轉成外框，才能與顯示追蹤比對。
  原有供電／背光／驅動待確認限制不變；追蹤不會啟動螢幕或寫入 GPIO。
- 其他未列入試版的模組仍走原模型並只顯示淡化參考，過期隱藏。
  切回原模式仍保有既有功能。沒有保證任意零件或任意拿法都對準。
- **純顯示結果**：不覆寫 `DetectionState`、接線辨識、人工確認或電氣驗證。
  移動中的跟隨框不是接線成功或安全供電證據。

## 同步接口

### 零件定位恢復（2026-09-09）

- HC-SR04、HW-123、TFT 的模型追蹤器現在只在零件四邊形內計算膚色，
  不把外圍桌面或經過旁邊的手算成遮住零件。沒有降低模型信心門檻。
- 超過原有 2 秒保留期限仍未接受新定位，清除該零件的舊座標、最高可見比例
  與待確認候選。其他零件不受影響。影像尺寸、時間或幀號重置也清除舊狀態。
- 過期後重新取得連續 4 個不同幀的穩定候選才恢復 Pin；模型遺失、無效四角、
  實際膚色遮擋及不足的可見材質仍會中斷確認，不能靠重複讀取同一幀湊數。
  每幀間隔不得超過 1 秒。首次啟動同樣檢查本體材質，不接受只有桌面的候選。
- 可見比例基準改為已接受畫面的移動平均，不再永久保留歷史最高值。
  Profile、Pin 座標、HW-123 的排針方向檢查與顯示 LK 門檻不變。
- 模型 WS 的 `pose_quality` 新增 `reason`、`model_confidence`、`hand_fraction`、
  `visibility_baseline`、`reset_count`、`reset_reason`；能區分模型未找到、
  排針方向未確認、本體膚色遮擋、材質不足與等待重新鎖定。
  這些數值是演算法訊號，不是遮擋機率或校準過的準確度。

### 封包

`GET /api/tracking/frame?after=<seq>`：最多等候 250 ms，回傳最新一組 JPEG
data URL、Pi detection、components、frame_id、ts_ms、runtime_revision、seq、
processing_ms 及 `display_only: true`。無新幀回 204；停用或非 Pi 回 404。
不建立影像排隊；只保存最新一組。同時保留原有 `/video`、`/frame.jpg` 與 WS。
`pose_quality.recovered` 標示成功接回；失敗時 `recovering` 標示尚在短暫搜尋，
`reason` 提供影像支持不足、超時或形變等診斷原因，不代表硬體檢測結果。
局部外框使用 `stability: optical_flow_partial`、`outline_only: true`、
`support_ratio`；原有精準狀態維持 `optical_flow`。失敗的 `flow_lost` 搭配
`interrupted` 表示曾追到但目前無有效位置；前端顯示「遮擋／定位不足」，
不宣稱已分類出手部或知道遮住的位置。
`timing_ms` 提供灰階準備、各目標與 JPEG 封裝耗時；`recovery_searches`
回傳本幀擴大搜尋次數（至多 1），`recovery_deferred` 列出因冷卻／排程
延後搜尋的目標。這些是診斷資訊，不改變定位或接線狀態。
模型 WS 的 `pose_quality.image_confirmed: true` 表示該來源幀通過較強的
J8＋板面影像佐證；凍結／無新辨識幀不沿用此旗標。顯示結果中的
`pose_quality.rebase_count` 是目前追蹤物件累計成功更新參考影像的次數，
不代表接線驗證次數；重啟或建立新追蹤物件會歸零。

前端一次只發一個請求／解碼；JPEG 完成解碼後才提交對應標記。Pi 與上述三個零件
必須與 JPEG 使用同一 frame_id。切換版本、亂序資料直接捨棄，600 ms 未更新
就清空顯示標記並重新取得序號；請求逾時 1 秒，失敗後重試，不必手動重整。
同幀模式的 Pin 與接線線段也跳過舊版前端平滑動畫，避免再產生一幀延遲；
原模式的平滑動畫不變。

## 驗證與重現

2026-09-09 恢復修正驗收：

- 新增 23 項 regression cases，覆蓋暖色桌面、真實遮擋的合成情境、舊可見比例、
  靜止／移位後重新鎖定、漏幀／重複幀、相機尺寸／時間／序號重置及模組隔離。
  240 項相關後端測試、48 項前端測試、i18n 檢查與前端建置通過。
- 實際 C920 畫面兩次重啟後各取樣 12 秒：HC-SR04 與 Pi 分別為
  296/296、295/295 幀 locked，約 24.6 fps；瀏覽器確認超音波四 Pin 與外框顯示。
  統計見 `runs/diagnostics/component-recovery-20260909-restart1/summary.json`
  及 `runs/diagnostics/component-recovery-20260909-restart2/summary.json`。
- 當時畫面只有 Pi 與 HC-SR04，HW-123／TFT 不在畫面；三者 CUDA 模型均正常載入，
  後兩者尚未進行這次實物重新放入／重啟驗收。測試中的影像平移旋轉回放，
  不代表實際手持、不同光源、逐孔絕對精度或電氣接通測試。

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_motion_tracking.py -q
.\.venv\Scripts\python.exe ..\tools\verify_motion_tracking.py --seconds 15 --out ..\runs\diagnostics\motion-check
```

測量工具只讀本機影像／API，不操作硬體；會保存一張來源影像、封包統計及已知
平移旋轉縮放的影像回放結果。回放不是實際手持、逐孔絕對精度或電氣測試。
本次結果見 `runs/diagnostics/motion-trial-20260907/summary.json`。

快速移動回歸測試（共用同一張實拍影像，不重新取得模型結果）：

```powershell
.\.venv\Scripts\python.exe ..\tools\verify_fast_motion.py --fixture ..\runs\diagnostics\fast-motion-20260907\fixture.json --out ..\runs\diagnostics\fast-motion-check.json
# 四個目標都必須先有真正 locked 的同幀姿態，工具不會補造定位。
.\.venv\Scripts\python.exe ..\tools\verify_fast_motion.py --objects raspberry-pi-5 hc-sr04 hw-123 mrd-tf240-8p-cs --fixture ..\runs\diagnostics\four-objects\fixture.json --out ..\runs\diagnostics\four-objects\replay.json
```

前後比較見 `runs/diagnostics/fast-motion-20260907/RESULTS.md`。擴大搜尋比一般
LK 費時，首次特徵計算也可能有冷啟動延遲，不保證快速移動時維持固定 fps。
四目標上線驗收另見 `runs/diagnostics/multi-motion-20260907/RESULTS.md`。
局部遮擋修正見 `runs/diagnostics/occlusion-motion-20260907/RESULTS.md`。
追蹤效能優化與套用狀態見 `runs/diagnostics/tracking-optimization-20260908/RESULTS.md`。
Pi 5 舊特徵重新鎖定修正見 `runs/diagnostics/pi5-reacquire-20260908/RESULTS.md`。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_motion_rebase.py tests/test_pi5_pin_stability.py -q
.\.venv\Scripts\python.exe ..\tools\verify_pi5_rebase.py --fixture ..\runs\diagnostics\pi5-reacquire-20260908\live --out ..\runs\diagnostics\pi5-reacquire-check.json
```

此離線回放使用實拍紋理加上合成模糊／遮擋，刻意讓 J8 獨立參考影像比
顯示參考影像新。逐幀執行真正的影像檢查，但沿用已保存的語意姿態，
不重跑模型，也不宣稱為實體手持、遮手或逐孔絕對精度驗收。

使用者可先讓四個目標正面清楚可見，再分別緩慢平移與平面旋轉，檢查框線與
標記是否跟隨；遮住大半個零件應隱藏標記，放回清楚視野後才重新定位。
不要為測試追蹤而拉扯帶電接線。
