# Board Vision 辨識精度改善計劃書

**版本** v1.0（2026-08-01）
**範圍** Tier 0 幾何層的辨識精度：板卡姿態 → 腳位投影 → 線材偵測 → 端點指派 → 導引判定
**標記慣例** `[實測-硬體]` 真實相機/板子量測 · `[實測-本次]` 本輪用真實 OpenCV + 真實 board.json 幾何跑出的量測 · `[程式事實]` 讀碼確認 · `[推導]` 由規格＋實測純幾何推算 · `[推估]` 未驗證的預估

---

## 1. 一頁摘要

### 1.1 根因（比原本的假設更深一層）

最初的發現是「`SNAP_RADIUS_PX = 16.0` 對現在的鏡頭距離大了 3.1 倍」。本輪調研**證實這是真的，但它只是共犯，不是主因**。

真正的主因鏈是三層疊加：

| # | 根因 | 量化 | 依據 |
|---|---|---|---|
| **R1** | `_board_exclusion_mask()` 用 `poly * 0.94`（繞質心的**等向像素**縮放 + z=0 輪廓）切掉板內像素，使骨架端點離真實腳位有一段「切口距離 cut」。**沿排偏移 = cut × tan(進線角)** | cut 深度隨傾角在 **−24.6 ~ +30.8px** 間擺盪；cut=8px + 進線角 40° → 沿排偏移 **+7.0px = 0.66 pitch** → **保證吸附到隔壁腳** | `[實測-本次]` |
| **R2** | 吸附半徑是尺度盲的固定常數 | radius/pitch = **1.56**（設計意圖 0.50）→ 同排兩側鄰居都在圈內 | `[實測-硬體]` |
| **R3** | `ambiguous_tie` 是**死碼**：判定條件是兩距離相差 < `1e-6` px | 浮點雜訊下觸發機率約為零 → 「never guess」承諾在程式層**從未被執行** | `[程式事實]` `wire_tracer.py:408` |
| **R4** | 相機內參焦距偏長 **27%**：`default_camera()` 用 `f = 0.9·W`，C920 官方 hFOV 70.42° 對應 `f = 0.708·W` | 直接污染 solvePnP 的 tvec 與傾角估計 | `[程式事實]`＋`[推導]` |
| **R5** | 沒有時間層：每 tick 發布瞬時幾何 | 靜態單線的 verdict 出現過 **8 種不同 pin_id** | `[實測-硬體]` |

半個 pitch = 5.29px。R1 單獨就能讓端點偏移超過這條線；R2 讓錯誤有地方去（鄰居在圈內）；R3 讓系統對此保持沉默並回報 confidence 0.62；R5 讓它每秒重抽一次籤。**驗收 log 裡 `D5→RESET→D6→D4→BOOT→correct→D9→D8` 那串跳動，是這五層的乘積，不是任何單一 bug。**

### 1.2 兩個推翻先前結論的發現

**① 我原本提的修法（半徑改成 0.45×pitch ≈ 4.6px）會摧毀 recall。**
`[實測-本次]` Monte-Carlo：只把半徑等向縮小到 4.8px → **100% 的真實插線被誤判成 `floating`**——因為骨架端點在**垂直**方向本來就離腳位 5–12px（切口 + 骨架回縮）。
正解是**在 header 排的局部座標系做非等向判定**：沿排 ±0.5×局部腳距（決定身分）、跨排 ±1.5×pitch（決定有沒有插）。理由不是兩排會互相競爭（它們相距 95–205px，永遠不會），而是**誤差預算本身是各向異性的**：垂直誤差大且系統性，沿排誤差小，而**只有沿排座標決定腳位身分**。

**② 「1080p 比 720p 模糊」是量測假象。**
Laplacian variance 是 per-pixel 二階導數，**跨解析度不可比**。真正的成本是 USB 2.0 頻寬（1080p30 ≈3.2 bit/px vs 720p30 ≈7.1 bit/px），但 1.5× 取樣增益對 pin 尺度幾何是淨賺。先前「鎖定 720p」的決定應該被推翻。

### 1.3 「準」在本計畫後的數值定義

| 項目 | 現況 | 計畫後 |
|---|---|---|
| **Headline 指標** | 未量測 | `verdict_dangerous_rate ≤ 0.02`（把錯的說成對、或把對的說成錯的腳） |
| pin 指派正確率 | ≈0.3 `[推估]` | ≥ 0.90 |
| 靜態 verdict 翻轉 | ≫120 flips/min `[實測]` | ≤ 30 flips/min |
| 端點沿排誤差 | 0.3–0.6 pitch `[推估]` | ≤ 0.15 pitch |
| 尺度不變性 | 無（常數綁死某距離） | 2–7 px/mm 全區間指標平坦（合成回歸測試） |

**度量本身也要修**：M4 的「靜態抖動 ≤0.5px」是錯的度量——0.85px 只佔沿排決策半寬 5.29px 的 16%，而且拉近相機降低的是比例不是絕對值。改成 **≤8% pin pitch**（現況 8.0%，目標 4.5%）。

---

## 2. 現況量測基線

改動前的完整存檔，供日後比對。**測量值與推估值嚴格分開。**

### 2.1 尺度與幾何 `[實測]`

| 項目 | 值 | 來源 |
|---|---|---|
| 板寬（投影） | 277px / 68.58mm → **4.02–4.04 px/mm** | 剪影 minAreaRect |
| 腳距（投影） | JDIGITAL **10.21px**（σ 0.009）、JANALOG **10.67px** | 逐對相鄰腳位投影 |
| 半個腳距 | **5.29px** ← 沿排決策邊界 | 推導 |
| `SNAP_RADIUS_PX` | 16.0 → radius/pitch **1.56** | 程式事實 |
| 常數設計時的隱含尺度 | pitch 32px / 板寬 864px / 12.6 px/mm | 由 docstring 反推 |
| 兩排 header 投影距離 | 95–205px | 本次量測 |
| 板子距離／姿態（debug frame） | 298mm；板法線 vs 視線 **21.75°** | 真實 rvec/tvec |

### 2.2 排除遮罩的切口深度 `[實測-本次]`

| tilt | JDIGITAL cut | JANALOG cut |
|---|---|---|
| 0° | +0.8px | +0.8px |
| 20° | +13.8px | −11.2px |
| 40° | +25.9px | −20.9px |
| 50° | **+30.8px** | **−24.6px** |

兩種失效同時發生且方向相反：一排被切 26px（沿排偏移爆掉），另一排完全沒遮住（PCB 藍色重新進入 blue band）。
**修法後**（header 平面 z=8.5mm + 逐邊 mm 內縮）：cut 收斂到 **0.54–1.12mm（≈10x 改善）**，且暴露板面積 **11.6% → 2.7%**——兩個目標同向改善，無 trade-off。

### 2.3 沿排偏移 = cut × tan(θ) `[實測-本次]`（真實 Guo-Hall + 真實形態學，pitch 10.58px）

| cut | θ=0° | θ=20° | θ=40° | θ=60° | θ=75° |
|---|---|---|---|---|---|
| 4px | 0.0 | +2.0 | +3.0 | +6.0 | +13.0 |
| 8px | 0.0 | +2.0 | **+7.0** | **+13.0** | +28.0 |
| 16px | 0.0 | +5.0 | **+13.0** | **+27.0** | 骨架消失 |

### 2.4 姿態平滑 A/B `[實測-硬體]`（靜態 15s locked，per-pin σ 中位數）

| min_cutoff / beta | 靜態 | 移動軌跡測試（上限 5.0px） |
|---|---|---|
| 1.5 / 0.3（原始） | 3.03px | PASS |
| 0.15 / 0.3 | **0.71px** | **13.8px FAIL** |
| 0.3 / 2.0 | — | 5.98px FAIL |
| **0.3 / 4.0（現行）** | **0.85px** | **PASS（4.957px，餘裕 0.9%）** |

The table above is the earlier tuning record. The current default is
`0.3 / 12.0`; the added 270-degree 1920x1080 synthetic case measures
4.32 px median and 7.82 px p95, while the existing static-jitter test remains
under its 1 px per-axis limit. Physical remeasurement is still required.

### 2.5 drape 幻影的幾何 `[實測-本次]`

真實影格重現：一條**完全沒插**的藍線回報 `endpoint_b = pin:5V @conf 0.34`。

| 量測 | 值 |
|---|---|
| 骨架終端 → 5V 腳位投影 | **9.1px，方向 86.6°** |
| 同腳位「L=8mm 接頭軸」的預測投影 | **7.3px，方向 89.5°** |
| **差距** | **2.9° 角度、1.8px 長度** ← 方向測試在真實幻影上**直接失效** |

### 2.6 杜邦接頭外殼的可偵測性 `[實測-本次]`

| 項目 | 值 |
|---|---|
| 接頭 minAreaRect | 39.5 × 15.9px，aspect 2.48，DT 最大半寬 7.8px |
| 線材絕緣層寬 | 6.6px（半寬 3.3）→ **接頭比線粗 2.4×** |
| 接頭 V 值 | **17** |
| 深色 PCB V | **15** → **ΔV = 2**（JANALOG 側幾何必然失效） |
| 白紙背景 V | **180** → ΔV = 163（極佳） |
| header 塑膠 V | 21 |
| LED 矩陣 V | 中位 59，p10 **8**，p90 147（極高變異） |

### 2.7 次像素端點外推 `[實測-本次]`

骨架尾段 `cv2.fitLine` 外推到 header 排線：沿排 RMS 誤差 **3.3–42.4px → 0.3–0.9px**（θ≤45°），成本 **5.7 µs/端點**。

### 2.8 其他 `[實測]`

- 靜態單線的 verdict 出現 **8 種不同 pin_id**（真值 D8）
- 幻影 `IOREF ↔ A0`（實際不存在的連線）發生 1 次
- ridge 通道 RAW 分支數 **26**（麵包板孔列＋紙邊陰影）；紫線經 snap 後 recall **0**
- ORB Lowe survivors：乾淨畫面 **123**（gate 25）；反光時崩到 **9–14**
- 後端測試 **153 綠**；合成 jitter baseline worst per-pin σ **0.147px**

### 2.9 一個必須避開的程式陷阱 `[程式事實]`

`snap_endpoint()` 的半徑是**預設參數**（`radius_px: float = SNAP_RADIUS_PX`）。改模組常數不會影響已綁定的 `__defaults__`——**必須在 `trace()` 顯式傳入**，否則修改看似生效實際無效。

---

## 3. 分層改善方案

按 (精度增益) / (工作量 × 風險) 排序。每項附「改哪個檔案、確切算法、預期增益與依據、成本、風險、如何驗證」。

### G1 — 排除遮罩改成 header 平面 + 逐邊 mm 內縮 ★最高優先

- **檔案** `app/vision/wire_tracer.py:111-123` `_board_exclusion_mask()` 的輸入來源；投影借 `camera_model.project_board()`
- **算法** 不再用 z=0 的 `outline_px` 縮放，改投影一個**位於 header 平面（z = `header_top_z_mm` = 8.5mm）、在 board-mm 空間逐邊內縮**的矩形：
  ```
  inset_header_mm = 1.5   # y=0 與 y=H 兩條 header 邊
  inset_side_mm   = 1.0   # x=0 與 x=W（無 header）
  rect = [(1.0,1.5,8.5), (W-1.0,1.5,8.5), (W-1.0,H-1.5,8.5), (1.0,H-1.5,8.5)]
  ```
- **增益** cut 從 −24.6…+30.8px 收斂到 0.54–1.12mm（≈10x）；暴露板面積 11.6%→2.7% `[實測-本次]`
- **成本** `projectPoints` 4 點 = **8.8 µs** `[實測-本次]`
- **風險** `inset_header_mm` 不可 ≥2.54mm：UNO Q 母排塑膠帶覆蓋 y≈1.3–3.8mm，暴露它會產生 ~10×182px 深色長條，其 DT 半寬 ~5px **低於** `MAX_WIRE_HALF_WIDTH_PX`=14，寬度濾波攔不住 → 變成沿 header 的假線材 `[推估，需實拍驗證]`
- **不可用的近似** 在像素空間對投影四邊形做 lerp 內縮：tilt 40° 時 JDIGITAL 仍被切 20.0px `[實測-本次]`（問題來自 z=8.5 視差，不是內縮量）。**必須在 3D 投影**
- **驗證** 對真板量 header 條的 DT half-width；replay harness 的 `pin_proj_err_pitch` 有號分量

### G2 — `PinLattice` 非等向吸附（取代 `SNAP_RADIUS_PX`）

- **檔案** 新 dataclass 放 `app/vision/camera_model.py` 的 `project_board()`（唯一同時持有 profile 的 `pin.header`/`pin.index` 與該幀投影腳位的地方）；`snap_endpoint()` 改吃 lattice
- **算法** 每腳持有沿排單位向量 `u`（排內相鄰腳差分）與擁有半寬；判定分兩軸：沿排 ±0.5×局部腳距 → **身分**；跨排 ±1.5×pitch → **有沒有插**
- **增益** 直接消滅 R2；`same_row_neighbour_error_rate` 由 ≈1.0 → ≈0
- **風險** 等向縮小半徑會 100% 殺 recall `[實測-本次]`——**這是為什麼不能只改常數**
- **前置** G1（cut 失控時任何半徑都無效）
- **驗證** 合成尺度不變性測試 + `same_row_neighbour_error_rate`

### G3 — 次像素端點：骨架尾段直線外推

- **檔案** `app/vision/wire_tracer.py` Stage C→D 之間
- **算法** 取骨架尾段 N 點做 `cv2.fitLine`，外推到 header 排線求交點
- **增益** 沿排 RMS 3.3–42.4px → **0.3–0.9px**（θ≤45°）`[實測-本次]`
- **成本** 5.7 µs/端點
- **風險** 真實杜邦線末端有 9.9×4.0mm 黑色接頭外殼，會在遮罩邊緣產生比線體寬的 blob，可能改變最佳 `skip` 值 `[推估]`——M33 需用真板掃一次

### G4 — 讓 `ambiguous_tie` 真的會觸發（修 R3）

- **檔案** `wire_tracer.py:408`
- **算法** `tie_tol = max(2.0, 0.20 × pitch_px)`；`margin = d2 − d1 < tie_tol` → `ambiguous_tie`
- **增益** 把「次像素雜訊決定勝負卻回報 confidence 0.62」變成明示的不確定。**這是把 never-guess 從文件承諾變成程式行為**
- **成本** ~8 行
- **代價** `verdict_uncertain_rate` 會上升——這是保守方向，符合反棘輪規則

### G5 — 內參標定（修 R4）

- **檔案** 產生 `camera.json`；`app/vision/camera_model.py` 的 `default_camera()` 只作 fallback
- **算法** `cv2.calibrateCamera` + checkerboard，30 分鐘，零新依賴
- **增益** 移除 27% 焦距偏差 → 直接改善 tvec 與傾角估計，是 pin 投影系統偏差的一個源頭
- **附帶** 把 4px shrink 魔術數字換成公式：`shrink_px = header_top_z_mm × tan(θ_from_nadir) × px_per_mm`（θ 從 rvec 拿）。反推現況 4px → θ=6.6° `[推導]`，與「slightly oblique」吻合
- **硬邊界** 剪影標定法要求 header 視差 < 0.25 pitch → **θ < 4.3°**，也就是**只在幾乎正天頂時有效** `[推導]`

### G6 — 時間層：`WireTrackFuser` + `EndpointVoter` + `VerdictDebouncer`

- **檔案** 新 `app/vision/temporal.py`；接進 `wire_worker.py` tick
- **參數（決斷值，interval_s=0.5）**

| 機制 | 參數 | 使用者可見延遲 |
|---|---|---|
| wire track 確認（M-of-N） | 最近 3 tick 中 2 次 | +0.5s 典型 / +1.0s 最壞 |
| coasting（遮擋容忍） | 連續 3 tick 未見才刪 | — |
| **端點投票離散度否決** | 視窗 6 tick、winner share < 0.70 且 ≥2 個不同 pin → `ambiguous_tie` | 乾淨情境 +0s |
| `→ correct` 晉升 | 連續 2 tick | 總 0.82s 均值 / 1.09s 最壞 |
| `→ wrong_pin` 晉升 | 最近 4 tick 中 3 次且 `actual_pin_id` 相同 | 總 1.32–2.09s |
| `→ uncertain` | 1 tick，零 debounce | +0s |
| 抑制上限（防隱藏真實變化） | published 與 raw 連續不一致 4 tick → 強制 `uncertain(unstable)` | ≤2.09s |

- **關鍵洞察** `winner share` 同時是 **G2 是否調對的線上監測器**：半徑正確時 in-zone pin 只有 1 個，share 恆為 1.0；半徑超大 3.1 倍時無偏雜訊下 share ≈ 0.33。**0.70 這個門檻是從 R2 的 ratio 幾何推出來的，不是猜的**
- **硬性前置：G1+G2 必須先上。** 若在幾何修正前單獨上時間層，結果是「把每 tick 抽籤變成穩定地報出抽籤的眾數」——眾數只在雜訊對稱時等於真值，而 finding #4 證明它不對稱。**那比現在的抖動更危險，因為抖動至少看得出有問題**
- **不對稱設計的理由** `wrong_pin` 是指控性判決，代價不對稱，所以比 `correct` 更慢出現

### G7 — 姿態抖動 0.85 → ~0.70px

- **算法** 80ms **時間窗**中值前濾波 + `tvec_z` 專屬硬濾波
- **增益** `[實測-本次]` 端到端 A/B：靜態 median σ 0.113→0.095px，軌跡誤差 **4.957→4.896px（同時變好）**
- **絕對禁止** 固定 N 的中值（median-3）：軌跡測試 4.96→**6.31px FAIL**（該測試取樣間隔 0.15s）。**必須是時間窗，不是固定筆數**
- **優先度低** 0.85px 只佔沿排決策半寬的 16%，不是精度瓶頸

### G8 — 物理層：framing 8.4 px/mm + 中灰墊 + 鎖曝光

- **目標** 8–10 px/mm（pitch 20–25px）。**12.6 px/mm 在 C920 上物理不可能**（需 Z=72mm）`[推導]`
- **路徑（不花錢）** 切 1080p（×1.5）+ 距離 224mm→**162mm**（×1.38）= **8.4 px/mm，pitch 21.3px** `[推導]`
- **墊子** 換**霧面中灰（L*≈50）**。白紙會讓 AE 把 PCB 壓暗 1–1.5 stop（**很可能是 ORB 123→9 崩潰的共犯**）並把陰影對比拉到最大（**正是 ridge 26 條假分支的來源**）`[估計]`
- **唯一建議採購** US$20–30 霧面 LED 補光板（為了鎖 1/160s 曝光）。**不要**買第二顆相機或 4K
- **代價** DoF 從 ±40mm 縮到 ±20mm，必須鎖手動對焦，治具（夾臂 + L 形定位膠帶）**不是可選項**

### G9 — drape 判別：四道測試 + `attachment` 欄位

| 測試 | 內容 | 在真實幻影上的效力 |
|---|---|---|
| **T1** 方向 | 終端方向 vs 接頭軸投影 | **失效**（只差 2.9°／1.8px）`[實測-本次]` |
| **T2** 遮罩延續 | 終端外是否仍有 mask | 若終端在排除邊界上可攔 |
| **T3** ferrule | 接頭外殼（比線粗 2.4×、aspect 2.48） | **JDIGITAL 可用**（背景白紙 ΔV=163）；**JANALOG 永久失效**（疊在 PCB 上 ΔV=2） |
| **T4** 板子運動視差 | 板子轉 ≥8° 時三角化端點高度 | 唯一能攔 tip-resting 幻影的手段，`σ_z ≈ 1.6mm` `[推估]` |

- **契約決定** 不新增第 4 種 `EndpointKind`（沿用既有設計決定），改在 `WireInstance` 加 `attachment ∈ {inserted, resting, unknown}` + `attachment_confidence`
- **UI 要求** 閘門關閉時必須給可操作訊息（「相機太正對板子，插入判定不可用——請把相機降低約 10°」），否則 `uncertain` 在使用者眼中就是「壞掉了」

---

## 4. 五份報告的衝突與裁決

不迴避，逐條裁決：

| # | 衝突 | 裁決 |
|---|---|---|
| **C1** | 我原本主張半徑改 0.45×pitch；幾何報告實測這會 100% 殺 recall | **採用幾何報告**：非等向 lattice。過渡期（G2 未上線前）半徑用 `1.55 × pitch_px` clamp——現況等於 15.97px ≈ 今日的 16.0，**recall 完全不變**，只讓半徑開始追蹤尺度 |
| **C2** | 時間層報告要求先修半徑；幾何報告要求先修遮罩 | **兩者都對，順序是 G1 → G2 → G6**。時間層在幾何修好前上線會製造「穩定的錯答案」 |
| **C3** | 端點軸向偏移 ~10mm（接頭外殼）該放寬容許量還是扣掉？ | **在 lattice 裡扣掉它**（有號軸向分量 β 是可量測的系統偏差），不是放大容許量 |
| **C4** | 光學報告主張切 1080p；先前實測「720p 更清晰」 | **推翻先前結論**：Laplacian variance 跨解析度不可比。改用 pitch-normalized 指標重新驗證 |
| **C5** | 全域一對一指派（Hungarian）要不要做？ | **不要做**。一條線常被遮罩切成多段，且 M21 雙通道刻意產生重複實例；強制互斥會把其中一個推到隔壁腳，**製造自信的 wrong_pin**——本專案最不能犯的錯。只在「同一 WireInstance 兩端吸到同一腳」這個物理不可能的情形做互斥 |

---

## 5. 波次工作計畫（M31 起，M0–M30 已佔用）

| 波次 | 里程碑 | 內容 | 前置 | 真實硬體驗收 |
|---|---|---|---|---|
| **W1 誠實化** | **M31** | 尺度自適應半徑（`1.55×pitch` clamp，recall 不變）+ `ambiguous_tie` 復活（G4）+ `snap_margin_px` 欄位 + `geometry` 遙測 | 無 | log 每 10s 印 `scale-sanity pitch=10.3 radius/pitch=1.550`；`ambiguous_tie` 計數 > 0（今日恆為 0） |
| | **M32** | 內參標定（G5）+ 鎖 WB/曝光 + 中灰墊 + yellow/green 色帶重採樣 | 無 | checkerboard 標定寫入 `camera.json`；`pin_proj_err_pitch` 有號分量下降 |
| **W2 制度** | **M33** | 真值擷取工具 + replay harness + 合成尺度不變性測試（§6） | M31 | 15 分鐘擷取 ≈225 frames；`--baseline-out` 產生第一份基準 |
| **W3 幾何** | **M34** | **G1 遮罩修正 + G2 PinLattice + G3 次像素外推**（同一 commit） | M33 | `same_row_neighbour_error_rate` ≈1.0 → ≤0.7；`pin_assignment_accuracy` ≥0.90；沿排 `err_pitch` median ≤0.15 |
| **W4 穩定** | **M35** | G6 時間層 + ROI 化（`interval_s` step active 期間降 0.3） | M34 | 靜態 `flips_per_minute` ≤30；`pin_id_entropy` 8→1；`wrong_pin` 1.32–2.09s 出現 |
| **W5 物理** | **M36** | G8 framing 8.4 px/mm + 治具 + G7 姿態時間窗中值 | M34 | 實測 px/mm ≥8；靜態 σ ≤8% pitch；軌跡回歸仍 PASS |
| **W6 drape** | **M37** | G9 四道測試 + `attachment` 欄位 + UI 閘門訊息 | M34, M36 | 插入 → 3s 內 `inserted`；平躺同一腳位 → `resting` + guidance `uncertain`（**不是** `correct`）；`phantom_from_drape` ≤0.05 |
| **W7 召回** | **M38** | ridge 通道重評 | M36 | RAW 分支 26→≤5 且 `empty_scene_fp_per_frame` 不升 且紫線 recall >0，**三項全過才允許預設開啟** |

---

### 5.1 Current implementation status (2026-08-03)

The code-side work for M31/M34/M35 is present, and the capture/replay tooling
now records an offline `PipelineDetector` pose plus endpoint, projection,
same-row-neighbour, empty-scene, recall, and flips/minute metrics. Camera
intrinsics are resolution-aware, the physical default is 1920x1080 with a
C920 FOV fallback, and Windows device capture defaults to DirectShow.
The replay harness now separates `truth-pins`, frozen `recorded`, stateful
`sequential`, and fresh-detector `perframe` modes; sequential/perframe also
run the live stabilizer and attachment classifier so pose-filter regressions
are observable without mixing them into the frozen-pose gate.
Live traces now also have a conservative motion-based attachment classifier:
inserted requires the raw wire endpoint to follow a projected pin across
motion, resting requires the endpoint to remain still while the board moves,
and static, insufficient, or conflicting evidence remains unknown.

Guidance attribution now keeps the source wire and endpoint side for each new
pin observation. One wire contributing two new endpoints, or multiple wires
contributing new endpoints in the same tick, is reported as `uncertain` rather
than being collapsed into a cross-row `wrong_pin`. The remaining work for this
case is physical replay validation, not another flat-set heuristic.

Descriptor matching now also enforces one-to-one reference usage after the
Lowe-ratio test. This prevents repeated header texture from inflating the
homography inlier count; on the saved real frame the raw 118 Lowe survivors
reduce to 113 unique reference matches while the 25-inlier acceptance floor is
still satisfied.

The homography gate additionally requires its inlier convex hull to cover at
least 5% of the board reference area. Measured normal, 180-degree, oblique,
real, and 40%-occluded cases remain above this floor; it rejects a local
repeated-texture patch before PnP can publish a full-board pose.

Resolved wire endpoints now also carry canonical projected pin coordinates in
`normalized_px` and `connection.endpoints[].position`. The raw skeleton end is
kept internally for motion-based attachment classification, so structured
connection data no longer inherits the systematic ferrule/cut offset.

The wire worker now keeps the normal `interval_s=0.5` idle cadence and shortens
to `guidance_interval_s=0.3` while a guidance step is active. This improves
fresh-observation latency without adding a second CV worker; the ROI crop part
of the original M35 label remains a separate optimization and is not claimed
as implemented here.

Board exclusion now uses the same conservative rule for color and ridge
segments: board-only components are removed, but thin components that cross
the projected board boundary are retained. This prevents a real wire lying
over the PCB from being cut into an untraceable fragment; the added regression
test covers both the crossing wire and the board-only colored-blob counterexample.

The checked-in `reference_captured.jpg` currently produces a projected pin
pitch of about 10.7 px (about 4.2 px/mm) at 1280x720, below the physical
8--10 px/mm target. It is retained as a reproducible profile fixture, but it
must not be used to claim the physical accuracy gate; the next real capture
must move the board closer or use the 1920x1080 framing target.

The calibration write path now rejects underscaled captures before feature
extraction or any profile backup/write, returning `pitch_px` and `px_per_mm`
for diagnosis. The frontend guide grows to the recommended scale when the
source frame has room and disables capture when the estimated scale is below
the same physical gate.

The standalone reference-calibration path now applies the same board-region
feature-cache filter as the API path and refuses to write when the filtered
ORB cache is too small; background features therefore cannot silently become
pose matches.

The checkerboard tool also records per-view reprojection errors and coverage,
and refuses to install `camera.json` when those quality gates fail. A rejected
calibration is ignored by the runtime loader and falls back to the configured
FOV model.

The Windows capture path now negotiates MJPG before requesting width/height,
and the camera probe uses the same order. A live probe on the current host
still reports the first USB webcam at 1280x720, the C920 index as a black
1920x1080 stream, and OBS as a non-black 1920x1080 virtual stream. These are
device-selection observations, not an accuracy pass; the C920 must first
produce a real non-black frame and the board must meet the 8--10 px/mm framing
target.

The capture path now retries a black MJPG/YUY2 candidate with the driver-default
mode. On the current host that recovers a real 640x480 C920 frame, which is a
useful stream-recovery result but still correctly fails the physical scale gate.
The signal guard now also rejects near-black frames by mean 8-bit intensity,
not only exact all-zero frames; this prevents sparse sensor noise from making a
held or underexposed camera appear available.

The live source and camera picker now share a bounded three-frame UVC warm-up,
so a transient black first frame cannot make the two entry points disagree
about camera availability. Autofocus is no longer disabled unconditionally:
it stays enabled while framing and can be explicitly locked, with an optional
driver-specific focus value, after a sharp image is obtained. A dedicated
30-degree oblique synthetic regression remains within the pin error gate;
this verifies perspective/height parallax without claiming a physical-camera
pass.
The SIFT rescue path also now has a dedicated 60-degree side-oblique
regression: only its descriptor ratio is widened after ORB fails; the same
inlier coverage, PnP, and reprojection gates still decide whether a pose is
accepted.

The pose filter default `filter_beta` is now 30.0. A regression covers
90-degree and 270-degree board rotations at both 1280x720 and 1920x1080; the
latter exposed motion lag at beta 8.0 (5.08 px median pin error), while beta
30.0 brings the same 270-degree 1080p case to 2.74 px median / 5.19 px p95
without weakening the static-jitter gate (synthetic noise remains below
0.25px). This is still synthetic evidence, not a physical-camera claim.

Detection WS messages now expose pose evidence separately from aggregate
confidence: the accepted inlier count, mean reprojection error, reference-board
inlier coverage, and whether the pose came from full detection, LK tracking, or
a stale hold. This is diagnostic telemetry only; it does not silently turn a
low-scale profile into a physical pass or change the existing acceptance gates.

The live wire worker now adds a second, runtime scale safety gate for real
`pipeline` sources: when the delivered adjacent-header pitch is below 18px or
the density is below 8px/mm (or either measurement cannot be made), it clears
temporal wire state, publishes no endpoint candidate, and reports
`suppressed_reason:"scale_below_minimum"`. Active
guidance becomes `uncertain` with `reason:"scale_unready"`; the synthetic/mock
demo keeps the gate off unless explicitly configured. This prevents a locked
but underscaled pose from becoming a false wiring verdict.

The wire stabilizer now honors its configured confirmation and vote windows
when allocating per-track history buffers. Previously those buffers were
silently fixed at 3 and 6 samples, which made temporal tuning appear to work
while leaving the runtime behavior unchanged.

Guidance now also vetoes an `ambiguous`/junction-crossing wire when that wire
can contribute the target or a new endpoint to the active step. A resolved pin
id alone is not enough to claim a crossed skeleton path is correct; unrelated
baseline wires remain non-blocking.

Guidance activation now separates L2 `confirm` from L3 `auto`: `confirm` is
the default, while `auto` is rejected until the profile physical-quality gate
passes. The response explicitly distinguishes this profile gate from the
still-required labeled real-camera accuracy dataset.

M32 physical checkerboard calibration, M33 real labeled capture, M36 framing
measurement, M37 physical attachment classification, and M38 ridge recall
gating remain unverified until a real camera session is captured. Synthetic
tests and offline replay cannot be reported as passing those hardware gates.

## 6. 量測制度

### 6.1 為什麼制度先於修正

R1 之所以能活到今天，是因為**沒有任何測試以 pitch 為單位斷言過任何事**。制度的目標不是「多一組數字」，而是讓 R1 這一整類 bug（尺度盲常數）**自動現形**。兩個機制承擔這件事：

1. **尺度理智檢查線**：每次 harness 執行都印 `snap_radius_over_pitch`（現況 1.543）。成本為零。
2. **合成尺度不變性測試**：同一條線在 z=120…400mm 渲染，px/mm 掃過 7…2，斷言 `pin_assignment_accuracy` 在整個區間**保持平坦**。**這是整份計畫中價值最高的合成測試，而且只有合成做得到**（你不可能在 15 分鐘內把真線在 12 個距離重插一次）。

### 6.2 真值擷取：一行宣告 + 8 次點擊

真值有兩種，成本完全不同：**接線真值**（人類插線時就知道 → 一行 shorthand）與 **pin 投影真值**（沒有免費來源）。

第 2 項的解法：**header row 是 3D 直線且 pitch 嚴格均勻，3D 直線投影後仍是 2D 直線（恆真），沿線的參數化是 1D 投影變換**：
```
x(u) = (ax·u + bx)/(c·u + 1)      y(u) = (ay·u + by)/(c·u + 1)      u = pin index，5 個未知數
```
交叉相乘後對未知數線性，**每次點擊給 2 條方程** → **每排點 4 個 pin（兩端 + 兩個內部）= 8 條方程解 5 個未知數**，最小平方解 + 殘差可回報（過定 → 誠實性自檢）。兩排共 **8 次點擊**即可精確生成全部 32 個 pin 的真值 px。
**為什麼不是每排 2 點線性內插**：43mm 的 row 在 10° 傾角、200mm 距離下深度差約 7.5mm（3.7%），線性內插的中點誤差約 **0.8px ≈ 0.08 pitch** `[推估]` —— 和我們要量的抖動同量級，會污染指標。

**`tools/capture_groundtruth.py`**（沿用 `tools/wire_trace_debug.py` 已驗證的 `grab_frame()` 從 `http://127.0.0.1:8100/video` 抓 MJPEG，零新依賴）：

| 按鍵 | 動作 |
|---|---|
| `g` | 開新 scene：依序提示點 8 個 pin；即時算殘差與 `pitch_px` 並印出 |
| 一行文字 + Enter | 宣告真值並擷取一個 burst（15 frames @~3fps） |
| Enter（空行） | 用**同一份宣告**再抓一個 burst（temporal stability 用，零打字） |
| `q` | 收工，寫 manifest + 摘要 |

宣告語法（每個 config < 25 個按鍵）：
```
D8-GND_D blue          一條藍線，兩端在 D8 與 GND_D
A0 red                 一端在 A0，另一端出框
D8-GND_D blue; A0 red  多條線
~IOREF,A0 blue         DRAPE：藍線橫躺在板上靠近 IOREF/A0，但沒插進去
!                      場景中完全沒有線（量 false positive）
%hand                  附註：手在畫面中
```
**`~`（drape）是一等公民欄位，不是註解** —— 這是把 §2.5 的幻影從軼事變成數字的唯一辦法。

**儲存格式**
```
C:\Project\PnP\board-vision\datasets\wire-truth\s01-2026-08-01\
  manifest.json                    含 code_constants + profile_snapshot sha256 + camera 設定回讀值
  profile\                         ← 校正快照（board.json + reference_captured.jpg + features.npz + camera.json）
  scene-01\pin_truth.json          clicks / rows.fit_residual_px / pins_px / pitch_px / px_per_mm
                                   / snap_radius_over_pitch  ← 尺度理智檢查線
          cfg-01\truth.json        raw_input / declared / draped / hands_in_frame
                 pose.jsonl        每 frame 一行 DetectionResult
                 f000.jpg…f014.jpg
```
**`profile\` 快照是關鍵設計決定**：profile dir 已有 10 份 `board.json.bak-*`，證明重新校正是常態事件。若 replay 讀 live repo 的 profile，下一次校正就會讓整個資料集的 pose recompute 失去意義。約 1MB / session，換來永久可重播。
**`code_constants` 必存**（`snap_radius_px`、`max_wire_half_width_px`、`min_branch_length`、`min_mask_pixels`）：日後指標變動時才能歸因到「常數改了」而不是「資料不同」。
**Git 策略**：`datasets\` 整體不入版控，但 commit 一份 `golden-v1`（約 40 frames、8MB）作為 CI gate 固定基準。

15 分鐘時程：0–2 起後端確認 locked｜2–3 scene-01 八次點擊｜3–7 六個 config｜7–8 移動板子換距離角度 → scene-02 點擊｜8–11 五個 config｜11–12 改光線或斜角 → scene-03｜12–14:30 四個 config｜14:30–15 寫 manifest。產出 `[推估]` ≈225 frames、≈1000 個標註 endpoint、≈45MB。

### 6.3 指標定義（精確到分母）

**M1 pin 指派正確率** —— 配對演算法必須先定義，否則指標會自我美化：
1. 真值 endpoint 集（所有 `kind=pin` 的宣告端點，px 來自 `pin_truth.pins_px`）
2. 回報 endpoint 集（含 floating / ambiguous_tie）
3. **僅用幾何距離配對**，硬截斷 `2.0 × pitch_px`，按距離排序貪婪配對
4. **絕不用 pin_id 參與配對** —— 否則指派錯誤會偽裝成「未配對的 FP」，讓正確率虛高。**這一條是誠實 harness 與自利 harness 的分界。**
5. 顏色記錄但不參與配對 → 顏色錯誤獨立成 `colour_accuracy`
```
pin_assignment_accuracy = (回報 pin_id == 真值 pin_id 的端點數) / (已被配對上的真值 pin 端點數)
```
**必須同時報告分母與 `unmatched_truth_endpoints`。偵測到 1/10 條線但那條對了，不是 100% 準確。**
診斷子指標：`same_row_neighbour_error_rate` = 錯誤指派中「回報 pin 與真值 pin 同 header 且 index 相鄰」的比例。**M34 前應接近 1.0，M34 後應接近 0** —— 它直接指向 R1/R2。

**M2 endpoint 定位誤差** —— `err_pitch = err_px / pitch_px`（誠實指標）。報 median 與 p95，兩種單位都印，理由寫進 docstring。額外報**有號沿排分量**與**有號軸向分量 β**：若軸向 median 是 +10mm（接頭外殼），正解是**在 lattice 裡扣掉它**（§4 衝突 C3），不是放大容許量。

**M3 wire recall / precision** —— 以 pin-pair 為識別鍵（`_merge_cross_method_duplicates()` 已這樣做）。FP 分兩類：**`phantom_from_drape`**（端點 pin ∈ `draped[].near_pins`）與 `FP_other`；`wire_precision` 只除以 `FP_other`，drape 幽靈**單獨報**。`empty_scene_fp_per_frame`（`!` config 的平均回報 wire 數）是最便宜的 FP 指標，也正是當初把 black/blue 打掉的那個數字。

**M4 判定混淆矩陣** —— 從真值**獨立**推導期望判定，**絕不呼叫 `evaluate_guidance_step()` 來算期望值**（那是套套邏輯），harness 內寫一份 30 行 spec 參考實作。
```
verdict_dangerous_rate = P(correct | 期望 wrong_pin) + P(wrong_pin 但 actual_pin_id 錯 | 期望 wrong_pin)
                       + P(correct | 期望 pending)
verdict_uncertain_rate = 落入 uncertain 的比例          ← 成本，不是缺陷
wrong_pin_names_right_pin = P(actual_pin_id == 真值 | 實際 wrong_pin)   ← 驗證「比裸 ✗ 更豐富」是否成立
```

**M5 時序穩定性** —— 在 `sequential` mode 重播 burst：
```
flips_per_minute = flips/(N−1) × 60 / interval_s = flips/(N−1) × 120
```
**用 tick 正規化，不用 burst 的 wall time**（burst 抓 3fps，worker 是 2Hz）。另報 `pin_id_entropy`（同一物理端點在整個 burst 出現過的不同 pin_id 數；驗收 log 中是 8，目標 1）與 `endpoint_stddev_pitch`（機制層原因）。

**M6 真實 frame 上的 pin 投影誤差** —— `pin_proj_err_pitch` median/p95 覆蓋全 32 pin，報有號 inboard/outboard 分量。**這正是能抓到 header 塑膠外框校正 bug 的指標**（那個 bug 產生約 0.5 pitch 的系統性方向性偏移，median 一看就知道）。

### 6.4 三種 pose mode

| mode | 做法 | 用途 |
|---|---|---|
| `recorded` | 直接用 `pose.jsonl` 的凍結 pose | **主要回歸 gate**。隔離 Stage A–E + guidance，pose 改動不污染 wire 指標 |
| `sequential` | 一個 `PipelineDetector` 依序吃 burst frames（LK + One-Euro 生效） | 端到端 + 時序穩定性的忠實重現 |
| `perframe` | 每 frame 獨立 `detect()` | 純診斷（pose 雜訊上界），**不設 gate** |

**分離 `recorded` 與 `sequential` 是必要的**：否則改 pose 濾波器會讓 wire 指標一起動，無法判斷哪一層退步了。
無相機執行完全成立 —— replay 只呼叫 `wire_tracer.trace()`、`evaluate_guidance_step()`、`occupied_pin_ids()`、`create_detector("pipeline", profile, dataset/profile)`，**從不建立 `FrameSource` / `CaptureService`**。

**檔案配置**（指標程式碼**不放 `app\`**，那會被打包進 server）：
```
backend\tests\accuracy\{__init__,dataset,metrics,replay,report}.py
backend\tests\test_accuracy_dataset.py               ← pytest gate（skipif 缺資料集）
backend\tests\test_vision_wire_scale_invariance.py   ← 合成，永遠執行，不需資料集
tools\replay_accuracy.py                             ← 薄 CLI
```
`pyproject.toml` 加 `markers = ["accuracy: 重播擷取的 ground-truth 資料集（較慢，需要 datasets\\）"]`。
用 `skipif` 而非 fail：乾淨 clone 必須維持全綠；但 golden 子集入版控，所以 skip 實際上只在有人刻意刪除時觸發。執行時間 `[推估]` `recorded` ≈12s + `sequential` ≈1s ≈ **15s**，可留在預設 run。
測試函式**一個指標一個 assert**（失敗時直接指名指標）。

### 6.5 門檻：程序而非我編的數字

**正確做法**：M33 第一次擷取後跑 `--baseline-out baseline.json`，把實測值寫成基準，再依實測值加餘裕設門檻；同時提供 `--fail-under baseline.json --tolerance 0.05`，在絕對目標還達不到前先擋住退步。

以下起始值除註明外**全部是 `[推估]`**，由已實測事實推導：

| 指標 | M34 前預期 | **今天就能設的 gate** | M34 後棘輪 | 最終目標 |
|---|---|---|---|---|
| `pin_assignment_accuracy` | ≈0.3（radius/pitch 1.56，3 個 pin 競爭） | ≥ 0.60 | ≥ 0.90 | ≥ 0.95 |
| `same_row_neighbour_error_rate` | ≈1.0 | 僅報告 | ≤ 0.7 | ≤ 0.5 |
| 沿排 `err_pitch` median | 0.3–0.6 | ≤ 0.60 | ≤ 0.15 | ≤ 0.10 |
| 沿排 `err_pitch` p95 | ≈1.0 | ≤ 1.50 | ≤ 0.35 | ≤ 0.25 |
| `wire_recall`（啟用色） | ≈0.8（僅 3 色實採樣過） | ≥ 0.70 | ≥ 0.85 | ≥ 0.90 |
| `wire_precision`（排除 drape） | ≈0.9 | ≥ 0.80 | ≥ 0.90 | ≥ 0.95 |
| `phantom_from_drape` / config | ≥0（已實測 1 次） | 僅報告 | ≤ 0.5 | ≤ 0.05 |
| `empty_scene_fp_per_frame` | 未知 | ≤ 0.5 | ≤ 0.2 | ≤ 0.05 |
| **`verdict_dangerous_rate`** ← **release gate** | 未知，log 暗示不小 | **≤ 0.10** | **≤ 0.02** | ≤ 0.01 |
| `verdict_uncertain_rate` | 未知 | **僅上界 ≤ 0.50** | ≤ 0.50 | ≤ 0.50 |
| `flips_per_minute`（靜態） | ≫120（實測） | ≤ 60 | ≤ 30 | ≤ 2 |
| 靜態 σ（% pitch） | 8.0%（實測換算） | ≤ 8.5% | ≤ 8.0% | ≤ 4.5% |
| `pin_proj_err_pitch` median | ≈0.083 + 校正偏差 | ≤ 0.25 | ≤ 0.15 | ≤ 0.10 |

**Release gate（單一）**：`verdict_dangerous_rate ≤ 0.02`（M34 後）／`≤ 0.01`（M36 後），在 `golden-v1` 的 `recorded` mode 上。其餘指標是 `--fail-under` 的防退步棘輪，不是發布閘門。
**反棘輪規則**：`verdict_uncertain_rate` 只有上界，**永遠沒有下界 gate**——不得為了讓數字好看而把不確定硬轉成確定。

### 6.6 合成與真實的分工（寫進 docstring）

> **合成擁有尺度、pose、幾何不變性（幾何鏈路的 recall 與決策邊界）；真實擷取擁有色彩、precision、drape。兩者不可互相替代。**

**合成能誠實驗證**：尺度不變性（最高價值）／snap 決策邊界成為受測契約／遮擋降級行為／交叉線 junction（M18 缺口）／drape 幾何（渲染一條在 header 頂端上方 +3mm 通過、不終止於孔位的線 → 真值說「無連線」；**它不能告訴你真實 drape 長什麼樣，但能證明 pipeline 是否具備任何拒絕「不終止線」的機制** —— 今天答案是沒有，值得先寫成紅燈測試）／pose 掃描下的 pin 投影誤差。

**合成不能誠實驗證（必須明寫）**：
1. **色帶正確性 —— 這是套套邏輯。** renderer 用我們挑的 RGB 畫線，我們寫的 HSV 帶當然會 match。**推論：合成通過絕不可用來合理化在 `wire_trace.colors` 啟用 `yellow`/`green`。**
2. **False positive 率 —— 零預測力。** 真實 FP 來源（暗角 25.7/50.5px 團塊、麵包板孔列、筆電邊框、桌面陰影、紙邊、ridge 的 26 條分支）在合成中由構造上不存在。**Precision 是純真實硬體指標。**
3. ridge 通道的現場行為。4. 感測器雜訊特性（MJPEG 痕、rolling shutter、AE 擺盪）。5. ORB 特徵真實性（反光導致 survivors 崩到 9–14 無法重現）。6. 插入深度與 header 塑膠遮擋。

---

## 7. 誠實限制：本計畫不會修好什麼

### 7.1 結構性不可解（單目 + 手持視角的物理極限）

| # | 殘留失效 | 原因 | 處置 |
|---|---|---|---|
| **L1** | **tip-resting drape 幻影**（線頭剛好停在孔位正上方、方向剛好沿接頭軸） | `[實測]` 那條幻影與「插入」的預測幾何只差 **2.9° 角度、1.8px 長度**。`sin(21.75°)=0.37` 使 out-of-plane 與 in-plane 位移在畫面上成為同一方向族。**這是投影退化，不是調參問題，提高腳位投影精度不會改善** | T2（若終端在排除邊界）可攔；T1/T3 攔不到；最終靠 T4（需板子動 ≥8°）。M34 後仍會有這一類，`phantom_from_drape` gate 只降到 ≤0.5/config |
| **L2** | **跨排跳動 `wrong_pin(RESET)` / `wrong_pin(BOOT)` 未被解釋** | 這些屬 JANALOG，與 D8 相距投影 95–205px。**任何 ≤16px 半徑都不可能跨排。** 只能來自 (a) 重新校正前整排錯位（已修）或 (b) **同一條線的另一端**吸到下排，而 `evaluate_guidance_step()` 的 `new_pins` 集合差**不分端點** | **這是「我的修正可能不夠」的唯一已知缺口，優先度高於任何微調。** M34 上線後必須用 `snap_margin_px` + 每個 verdict 的來源端點記錄重跑同一場景確認是哪一種。若是 (b)，M35 需額外修 guidance 的端點歸屬 |
| **L3** | **ferrule 偵測在 JANALOG 側永久失效** | 走廊疊在 PCB 上，ΔV = **2**。且這是幾何必然：任一視角下一排的接頭殼落在背景（好），另一排必然疊在 PCB（壞） | 偵測器自己回 `None`（不是 `False`）。該排永遠得不到 ferrule 加分 |
| **L4** | **絕對 0.5px 靜態抖動達不到** | `[推估]` 特徵定位誤差在像素空間大致與距離無關，拉近相機降低的是**比例**不是絕對值。M36 預期只到 0.68–0.72px | **改度量**（≤8% → ≤4.5% of pitch）。堅持絕對 0.5px 是在追一個沒有物理意義的數字 |
| **L5** | **同一 pin pair 的兩條實體線會合併成一條** | `_merge_cross_method_duplicates()` 的既有、有文件記錄的限制 | 不修。時間層的顏色多數票至少讓 payload 帶出「這個 track 看到過兩種顏色」 |
| **L6** | **8mm 級插入深度無法量測** | 插入深度本質需要基線，本專案沒有第二台相機 | 用「會移動的板子」取代第二視角（T4）。三角化 `[推估]` `σ_z ≈ 1.6mm`，但需要板子被轉 10° |

### 7.2 召回率完全沒有改善（本計畫不碰的部分）

- **purple / black / white / gray 線材**：purple 不在啟用色，black 因桌面陰影 ~97 條假線被排除，white/gray 從未評估。ridge 通道對紫線的實測 recall 是 **0**（snap filter 後）。
- **yellow / green 色帶仍是室內場景猜測**，M32 的重新採樣只在鎖 WB 後才有跨 session 意義，且需要真的有黃綠線可採樣。
- **Stage A' ridge 通道的實機假陽性率從未被特徵化**（RAW 26 條分支）。M38 的重評有明確 gate，若未達則**維持 DISABLED**。
- 時間層**不改善召回率**，它只讓「已經看得到的東西」的回報變穩定且誠實。

### 7.3 校準薄弱處（數字可信度不足）

| 項目 | 問題 | 需要什麼 |
|---|---|---|
| `confidence` 門檻 0.50 / 0.30 | **只有 n=1 的實測錨點**（0.62–0.64）。可能把合法偵測擋在 `correct` 之外 | M33 資料集的真實 confidence 直方圖 |
| `inset_header_mm = 1.5` | **只有幾何推算，沒有實拍驗證。** 若母排塑膠帶覆蓋比推估更寬，暴露的黑塑膠可能被 brown band 吃掉，而其 DT 半寬 ~5px **低於**門檻，寬度濾波攔不住 | M34 驗收必須用 `tools/wire_trace_debug.py` 對真板量一次 header 條的 half-width |
| 所有骨架／外推數字 | 來自**合成線材**。真實杜邦線末端有 9.9×4.0mm 黑色接頭外殼，`[推估]` 會在遮罩邊緣產生比線體寬的 blob，可能改變 `skip` 最佳值 | M33 用真板單線量一次 `skip` 掃描 |
| `SIGMA_POSE_PX = 0.85` 硬編 | 隨相機距離變化，未量測距離依賴性。更正確是從 `_PoseObs.reproj_px` 推導，但需把 reproj 誤差往上曝露到 `DetectionResult` | 先用常數，在 config 開旋鈕 |
| 合成靜態基準 0.113px vs live 0.85px | **差 7.5 倍。** 合成場景雜訊遠比真實桌面溫和，所以 §2.4 表格只能證明「不弄壞驗收軸」，**不能預測 live 改善量** | live 改善量 −12%~−18% 屬 `[推估]`，M36 實測 |
| 軌跡回歸餘裕 0.9% | baseline 4.957px / 上限 5.0px。**任何增加延遲的改動都在鋼索上走** | 這是為什麼「時間窗」而非「固定筆數」是唯一可接受寫法 |

### 7.4 產品層的已知代價

- **M31 過渡期 `verdict_uncertain_rate` 會明顯上升**。這是保守方向，M34 修掉。依反棘輪規則不得因此回退。
- **M35 之後 `wrong_pin` 最快 1.32s、最壞 2.09s 才出現。** 這是刻意的不對稱（指控性判決的代價不對稱），不是效能問題。
- **M37 之後 drape 會產生 `uncertain` 而非 `correct`。** 必須同時把「閘門為什麼關著」變成可操作的 UI 訊息，否則 `uncertain` 會變成使用者眼中的「壞掉了」。
- **M36 的 framing 改動要求使用者重新擺放相機到 162mm。** DoF 從 ±40mm 縮到 ±20mm，且必須鎖手動對焦——治具不是可選項。

---

## 8. 立即可做的第一步

**M31 的核心 30 行：讓 `ambiguous_tie` 從死碼變成會觸發的分支，並讓半徑追蹤尺度。**

選它的理由：唯一同時滿足「直接降低 headline 指標」「一次坐定可完成」「不需硬體重新擺位」「無任何前置」「風險極低（半徑數值在現況不變，只增加誠實度）」的改動。它也是後續每一項的共同前置（`pitch_px` 是 M34 lattice、M35 voter cell、M36 常數去像素化、M33 metrics 的共同輸入）。

**動工清單（依序，全部在 `backend/app/vision/wire_tracer.py`）**

1. **新函式 `_median_adjacent_pin_spacing(pins, profile, outline_px) -> float`**（約 20 行）
   - 依 `pin.header` 分組、依 `pin.index` 排序，取排內相鄰投影點距離，全體取中位數
   - 排除 UNO Q 的兩個寬間隙：丟掉 > 1.35 × 初步中位數的樣本後重算
   - 可見腳位 < 10 時退化：`pitch_px = 2.54 * ‖outline_px[1] − outline_px[0]‖ / 68.58`
   - `outline_px is None` 時回 `0.0`

2. **`trace()` 改成顯式傳半徑**（繞過 §2.9 `__defaults__` 陷阱的**唯一**方法）
   ```python
   pitch_px  = _median_adjacent_pin_spacing(pins, profile, board_outline)
   radius_px = float(np.clip(1.55 * pitch_px, 8.0, 26.0)) if pitch_px > 0 else SNAP_RADIUS_PX
   endpoint_a = snap_endpoint(path[0],  pins, radius_px, pitch_px=pitch_px)
   endpoint_b = snap_endpoint(path[-1], pins, radius_px, pitch_px=pitch_px)
   ```
   `1.55` 是刻意選的：在現況 pitch 10.3px 下等於 15.97px ≈ 今日的 16.0，**recall 完全不變**。

3. **`snap_endpoint()` 簽章加 `pitch_px: float = 0.0`**（keyword + 預設值 → `tools/wire_trace_debug.py` 與 153 個測試零改動）

4. **`wire_tracer.py:408` 的死碼換掉**（約 8 行）
   ```python
   tie_tol = max(2.0, 0.20 * pitch_px) if pitch_px > 0 else 1e-6   # pitch 未知時退回舊行為
   margin  = (within[1][0] - within[0][0]) if len(within) > 1 else float("inf")
   if margin < tie_tol:
       kind = "ambiguous_tie"
       candidates = [within[0][1].pin_id, within[1][1].pin_id]
       pin_id = None
   ```

5. **`WireEndpoint` 加 `snap_margin_px: float = 0.0`**（additive）；`wire_worker._endpoint_message()` 序列化它

6. **遙測**：tick 發布處加
   ```python
   "geometry": {"pitch_px": round(pitch_px, 2),
                "px_per_mm": round(pitch_px / 2.54, 3),
                "snap_radius_over_pitch": round(radius_px / pitch_px, 3)}
   ```
   並每 20 tick `logger.info("scale-sanity pitch=%.2fpx px/mm=%.3f radius/pitch=%.3f", ...)`

7. **`docs/api-contract.md §2`** 補 `wire_trace.geometry` 與 `endpoint.snap_margin_px` 兩個 additive 欄位

8. **新檔 `backend/tests/test_vision_wire_scale_invariance.py`** + `app/vision/synthetic.py` 的 wire renderer（約 60 行），標 `@pytest.mark.xfail(strict=True)`

**驗證（一次坐定內完成）**
```
pytest backend/tests            # 153 綠 + 1 xfail
```
然後起後端 + 真相機 + 真板，插一條線到 D7，觀察 60 秒：
- log 出現 `scale-sanity pitch=10.3 px/mm=4.06 radius/pitch=1.550` → **R1/R2 從此每 10 秒自動現形一次**
- `ambiguous_tie` 計數 > 0（今日恆為 0）
- `wrong_pin` 翻轉次數與 M31 前基線對照，記進量測 log

**不要在這一步做的事**：不要把半徑改小（會殺 recall，§4 衝突 C1）、不要動 `_board_exclusion_mask()`（必須與 lattice 同一 commit）、不要動任何 pose 濾波參數（軌跡測試餘裕只有 0.9%）。

---

## 引用

- 本輪五份研究報告（幾何／drape／時間／量測／光學）的完整原文存於 session scratchpad
- 既有設計文件：[software-architecture-plan.md](software-architecture-plan.md)、[wire-recognition-design.md](wire-recognition-design.md)、[color-agnostic-wire-and-guidance-design.md](color-agnostic-wire-and-guidance-design.md)、[api-contract.md](api-contract.md)、[vlm-grounding-playbook.md](vlm-grounding-playbook.md)
- C920 官方 hFOV 70.42°（Logitech 規格）
- 相關程式：`app/vision/wire_tracer.py`、`app/vision/pose_tracker.py`、`app/vision/camera_model.py`、`app/vision/guidance.py`、`app/wire_worker.py`
