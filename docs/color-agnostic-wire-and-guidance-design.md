# 顏色無關（Color-Agnostic）杜邦線偵測 + 導引式單腳位核對 — 調研與設計

延續 [wire-recognition-design.md](wire-recognition-design.md)（已解決：v1 範圍決策、HSV 分色管線、VLM 路徑追蹤的拒絕理由）與
[wiring-verification-architecture.md](wiring-verification-architecture.md)（已解決：WiringWorker 架構、ComponentSpec、verdict/verify API、診斷分類法）。

本文件回答使用者提出的三個初步功能中，尚未有設計的兩塊：

1. 杜邦線辨識要「不管顏色」——現有管線是 HSV 分色，色相無關要怎麼做，不能重蹈 black/blue 頻段的假陽性覆轍
2. 導引任務「插到腳位 X，判斷對錯打勾」——是否該用 AI 模型做這個判斷

Design-only：撰寫本文件時未修改或建立 `board-vision` 下任何程式檔案。

---

# 第一部分：技術調研

## 1a. 色相無關偵測技術評估

### TL;DR

**不要用單一「色相無關」技術取代現有 HSV 分色管線；加一個額外的、hue-agnostic 的備援 Stage A，插進現有骨架化→吸附管線，零新架構。** 具體建議：用**基於灰階梯度的平行邊緣/ridge 分數**（不是背景相減、不是訓練模型），因為它能重用本專案已經證明過的關鍵洞察——「吸附到已知腳位半徑內」（`SNAP_RADIUS_PX = 16.0`px，見 `wire_tracer.py:68`）——把「桌面上任何細長物體都可能誤判」的開放問題，收斂成「只有終止在 32 個已追蹤腳位附近才算候選」的封閉問題。背景相減在這個專案裡結構性地站不住：本專案自己的姿態追蹤（ORB+solvePnP）存在的理由就是板子會被移動，而背景相減對「板子被移動」跟「使用者的手在插線」這兩個最常見的真實互動都會產出巨量假陽性，且**背景相減本身分不出「變化的東西」跟「線」**——它是一個候選區域提案器，不是分類器，同樣需要下游的形狀判斷。

### 邊緣/形狀基礎偵測——平行邊緣、Ridge 偵測

**原理**：杜邦線絕緣層是固定外徑（~2-3mm）的圓柱體，在畫面上永遠呈現「兩條大致平行、間距大致固定的邊」，跟色相無關——這跟血管/導管偵測用的 Ridge/Frangi 濾波器（基於灰階 Hessian 矩陣特徵值，設計上就是色相無關）解決的是同一類幾何問題。細線偵測領域也有直接先例（Canny→Hough 三段式偵測 0.2mm 極細線）。

**與其他細長物體的區分能力，老實評估**：

- **陰影邊界**——本專案已經真實吃過兩次虧的案例（`black` 頻段匹配桌面陰影；`blue` 頻段在零藍線畫面上匯出 ~22,000px 假陽性 vs 真實紅線僅 ~7,800px）。平行邊緣/ridge 法**在這一項上明確優於純色相分色**：陰影邊界是單一柔和漸變邊，沒有配對的第二條邊；ridge 濾波器要求「兩條方向一致、間距恆定的陡峭邊」才給高分，結構上會拒絕陰影。這是這個技術路線值得加的核心理由。
- **板子邊緣**——UNO Q 板緣通常只有一側陡峭邊接桌面背景，另一側接板面（同色系、低對比），不太會產生「兩條平行陡峭邊」的訊號；且已有 `_board_exclusion_mask()`（`wire_tracer.py:71-83`）可直接重用排除板子輪廓，跟色相分色一樣。
- **手指邊緣**——寬度不固定、曲率變化大，跟杜邦線「固定 2-3mm、大致平直分段」的先驗不完全吻合，但**不能保證排除**，要誠實列為已知限制。
- **其他真實電纜（USB/電源線）**——這是這個技術路線**最誠實的弱點**：USB 線、電源線本質上也是「固定寬度圓柱體」，跟杜邦線是同一個幾何家族，ridge/平行邊緣偵測**設計上就無法單靠形狀把兩者分開**。這跟色相分色的失效模式性質不同：色相分色只有電纜顏色恰好落入頻段才誤判（有條件）；純形狀線索對任何寬度相近的電纜都給同樣高分（無條件）。**光靠這個線索,"regardless of color" 換來的代價是新增了一整類本來被顏色頻段擋掉的假陽性來源。**

  **但本專案已有的關鍵洞察正好補上這個洞**：`wire-recognition-design.md §2c` 已經證明「吸附到已知腳位」比「開放空間座標解析」容易得多的理由，同一個論證原封不動適用在這裡——USB/電源線幾乎不會恰好終止在 UNO Q 排針座標的 16px 半徑內（它們接的是電腦/牆插，不是這塊板子的排針），所以只要把 ridge 訊號跟現有的 `snap_endpoint()` 串接，大部分真實桌面電纜會被 Stage D 免費濾掉。

  **誠實聲明**：以上假陽性率是根據本專案已測得的可比數字（97 條 shadow 假線、22,000px vs 7,800px 的黑/藍頻段比例）推理出的估計值，**不是**這次任務重新拍攝驗證過的數字——出手前應該用 `tools/wire_trace_debug.py` 對著真實桌面 + USB 線 + 杜邦線的畫面實測校正，跟本專案對每個既有頻段做過的事一樣。

**OpenCV 現況**：OpenCV 本身沒有內建 Frangi/vesselness 濾波器（需要 `scikit-image`——這會是一個新依賴，跟本專案目前只用 `cv2`+`numpy`+`cv2.ximgproc.thinning` 的極簡依賴紀律不一致）。**建議走自製的、純 OpenCV 的平行邊緣分數**：灰階模糊→Sobel/Scharr 梯度→尋找「一段固定像素距離內兩條反向梯度符號的陡峭邊」的簡化 ridge-ness 度量，輸出跟 `segment_color()` 完全一樣形狀的二值 mask，直接接進現有的 `skeletonize_mask()`。

### 背景相減/幀差——結構性不適合這個專案，不是細節問題

兩個**結構性**問題：

1. **板子被移動是這個專案的常態，不是邊角案例**——本專案的姿態追蹤機制存在的唯一理由就是板子會被移動、旋轉、拿起放下。板子一移動，整塊板子輪廓在幀差裡就是一大團「新的前景」，跟真正的線材訊號無法區分；且移動後要花數十幀讓背景模型重新收斂，這段收斂期正好是使用者最可能在插線的時刻。
2. **變化 ≠ 線材**——手在插線的那一刻，手本身也是「新出現的東西」，跟線材同樣被幀差標成前景。背景相減只是候選區域提案器，不是分類器，不能單獨解決問題。

**結論：不採用背景相減作為主要或次要偵測手段**，最多留作未來可能的粗篩加速器，不放進 v1/v1.5 正式管線。

### 局部對比度/自適應二值化

本專案自己在 debug 咖啡色線時已經非正式用過這個技巧——`WIRE_COLOR_BANDS["brown"]` 註解的推導方式（「比局部欄背景明顯更暗」）本身就是一個局部對比度偵測器,只是當時只用來當一次性取樣輔助。可以用 `cv2.adaptiveThreshold` 正式化，在灰階/亮度通道上跑，天生色相無關。但跟 ridge 法一樣分不開真的電纜/手指邊緣，一樣要靠 Stage D 吸附半徑收斂假陽性空間，也一樣對局部反光/高光沒有免疫力。**評估結論：ridge 法對陰影（本專案吃過最大的虧）有結構性優勢，局部對比度沒有，優先選 ridge。**

### 混合式集成——去重靠既有的離散身分

**建議採用**：現有 4 色頻段（red/yellow/green/brown，已在真實測試驗證過）繼續當主力 + 加一個色相無關備援（ridge），只在色相頻段這一 tick 沒抓到訊號時補位。兩者互補：色相頻段負責高信心多數案例，色相無關備援負責少數案例（不常見顏色、飽和度被光照壓低的既有色）。

**去重比一般 NMS/IoU 合併簡單很多，是本專案架構送的紅利**：本專案的最終輸出空間已經被 Stage D 離散化——一條線一旦吸附成功，它的「身分」就是 `(endpoint_a.pin_id, endpoint_b.pin_id)` 這對已知腳位 ID，不是連續座標。去重不需要幾何 IoU 判斷，只要比對這個離散 key 是否相同即可合併，兩個獨立訊號源都同意同一個結論時直接把 confidence 上調。**邊界情況**：若兩條路徑對*同一物理端點*吸附到不同 pin，不能悄悄選一邊，要誠實保留成兩條獨立回報的紀錄，延續本專案「絕不亂猜」的既有慣例。

### 不要建置的

- 背景相減／幀差（結構性失效，不是調參能解的問題）
- Frangi/`scikit-image` 之類需要新依賴的方案
- 期待任何古典色相無關技術「解決」白/灰/黑或近中性色場景——**一條躺在黑色桌墊上的黑色線，同時低飽和度又低對比度，是真實存在、任何純古典影像技術都無法保證解決的殘餘案例**，必須誠實列為已知限制，不能宣稱解決
- 色相無關偵測到的線，`color` 欄位必須誠實回報 `unknown`，不能瞎猜顏色

---

## 1b. 導引式單腳位比對——AI 適用性評估

使用者的具體場景：導引任務說「把杜邦線插進 GPIO 腳位 X」，系統要判斷「線的端點是不是恰好在腳位 X」，顯示勾/叉。

### 這跟 §5 已否決的 VLM 路徑追蹤，形狀上不一樣，但結論方向相同

- `wire-recognition-design.md §5` 否決的是**開放場景路徑追蹤**——模型要從線的一端追蹤到另一端，中途要在多條相似候選路徑裡選對。《VLMs Trace Without Tracking》(arXiv 2605.15672) 的失效模式「相鄰線跳躍」正是因為候選路徑太多、太像，模型追蹤時被鄰近干擾物拉走——直接讀取該論文原文確認：這個失效機制明確是「mid-trace continuation failure」，不是「initial-localization failure」，論文本身沒有測過「單一已知座標的二元判斷」這種任務。
- 使用者這次問的問題，結構上是**「這個已知、極小、已經給定座標的區域裡，有沒有一個線材端點」**——不是「這條線最終走到哪」。裁切到單一已知腳位座標，等於從影像裡直接移除了「鄰近替代線」——沒有可跳的對象。

### 但更根本的事實：這個問題本來就不需要模型，已經有精確、免費、已驗證的幾何解法

`snap_endpoint()`（`wire_tracer.py:250-274`）做的正是這件事：拿到線材端點像素座標後，檢查是否有恰好一個已知腳位在 `SNAP_RADIUS_PX`（16.0px，已有真實驗證數字：紅線一端吸附距離 15.8px，未接觸端點回報 289.6px floating）內——這是精確的歐幾里得距離比較，不是估計，不會像模型一樣「有信心地答錯」。導引任務要問「線是否接在腳位 X」，只要把 `snap_endpoint()` 已算出的 `pin_id` 拿去跟目標腳位字串比較（`==`）就是完整答案——**這一步不需要影像理解，是字串比較**。

### Benchmark 證據（三個不同任務家族，數字差異很大）

| 任務家族 | 最佳實測數字 | 來源 |
|---|---|---|
| 麵包板線材**路徑追蹤**（既有設計文件已引用） | 6.2%（Claude Sonnet 4.5）→ 71.0%（Gemini3-Flash），模型間差距巨大 | arXiv 2605.15672 |
| 一般**指物/grounding**（在正常場景中指出命名物體） | Molmo-72B ~75% precision/recall；MolmoPoint 70.7%（PointBench） | arXiv 2409.17146, 2603.28069 |
| **局部視覺差異偵測**（前後 crop 比對「這裡有沒有變化」） | 最佳模型（Gemini 3.1 Pro）僅 **40.7% recall**，Hard 難度每個模型 recall < 23% | DiffSpot, arXiv 2605.29615 |

**局部視覺差異偵測**這個任務家族，跟「這個腳位是否剛冒出一個線材端點」的實際性質最接近（是跟預期/參考狀態比對，不是開放場景搜尋）——即使完全沒有路徑追蹤,recall 依然低於 41%。這是「單純裁切小範圍比對」不能自動假設可靠的證據。DiffSpot 同時測到 recall 跟變化的視覺顯著程度不相關（r = -0.08），所以「杜邦線很大很明顯」不足以保證模型會可靠抓到；但好消息是誤報率很低（1.6%）——模型更傾向「保守漏報」而非「自信答錯」。

### AI 唯一可能有真實增量價值的縫

當**整條古典管線（色相頻段 + 色相無關備援）在這一幀完全沒有偵測到任何線材候選端點像素**時——這種情況下 AI 要做的其實是「偵測」不是「核對」，重新落回開放場景定位範疇，只是場景比麵包板路徑追蹤基準簡單一些。**這個更窄的定位任務沒有被單獨測過**——不能直接套用 71% 這個數字當它一定不行的證據（那個數字測的是路徑追蹤），但也不能反過來假設它安全。誠實立場：值得未來單獨測，不能現在假設安全。

### 結論

**100% 古典幾何解決導引式打勾核對，AI 在這個判斷的決策路徑裡角色為零。** 唯一被允許的角色是狹窄、低頻、明確標成「粗略提示」的偵測復原角色——且必須跟權威的勾/叉判斷分開顯示，絕不能被拿來當作/取代那個判斷本身。

---

# 第二部分：概念設計

## 2.1 色相無關偵測：Stage A' 附加通道，不取代現有 HSV Pipeline

**決策：supplement，不是 replace。** 現有 `DEFAULT_COLORS = ["red","yellow","green","brown"]`（`wire_worker.py:73`）與 `WIRE_COLOR_BANDS` 九色頻段（`wire_tracer.py:35-64`）原封不動保留，新增**一個**色相無關的 Stage A' 通道，並在 Stage E 加一段離散去重。

### 具體改動位置（對照 `wire_tracer.py` 既有 Stage A-E 結構）

- **Stage A（既有，不動）**：`segment_color()`（`wire_tracer.py:86-117`）逐色 HSV 分色，簽名/行為完全不變。
- **Stage A'（新增）**：`segment_edge_ridge(frame_bgr, board_outline=None) -> np.ndarray`，跟 `segment_color()` 平行、同層級的新函式，簽名故意去掉 `color` 參數（沒有色相概念）：
  - 灰階 → 輕度高斯模糊 → Sobel/Scharr 梯度（純 `cv2`，不引入 `scikit-image`/Frangi，維持本專案既有的極簡依賴紀律）
  - 尋找「固定像素距離內、方向相反的一對陡峭邊」的簡化 ridge-ness 分數（線材絕緣層固定寬度 ~2-3mm 的幾何先驗），輸出跟 `segment_color()` **完全同形狀**的二值 mask（uint8, 0/255）
  - 重用既有 `_board_exclusion_mask()`（`wire_tracer.py:71-83`）排除板子輪廓
  - 新常數 `EDGE_PARALLEL_WIDTH_PX = (3, 12)`（**誠實聲明：需要用 `tools/wire_trace_debug.py` 對真實畫面實測校正後才能定案**，本次研究沒有相機可用，數字是根據線材實際寬度換算估計值，不是已驗證常數，跟 `SNAP_RADIUS_PX` 當年的驗證方式不同，上線前必須補測）
- **Stage B/C（既有，不動）**：`skeletonize_mask()`、`trace_branches()`——`segment_edge_ridge()` 輸出跟 `segment_color()` 同形狀，直接餵進同一組函式，零改動。`trace_branches()` 目前簽名要求一個 `color` 字串；Stage A' 呼叫端傳入哨兵值 `"unknown"` 作為 `color`。
- **`trace_wires()`（既有，小改）**：新增一個獨立布林參數 `include_edge_agnostic: bool = True`，跑完既有色相迴圈後，若為真，額外跑一次 `segment_edge_ridge()` → `skeletonize_mask()` → `trace_branches(skeleton, color="unknown")`，併入同一個回傳的 `dict[str, list[SkeletonBranch]]`（key 為 `"unknown"`）。呼叫端（`WireTraceWorker`）新增對應開關 `wire_trace.edge_agnostic_enabled`（預設 `True`，可用既有 nested env override 機制關閉）。
- **Stage D（既有，完全不動）**：`snap_endpoint()`（`wire_tracer.py:250-274`）逐字重用，色相分支跟 ridge 分支的端點都餵給同一個函式——這正是「零新架構」的關鍵：Stage D 本來就不知道端點是哪個 Stage A 通道生出來的。
- **Stage E（既有，擴充一段去重）**：`trace()`（`wire_tracer.py:277-321`）新增合併邏輯，用離散 key 而非幾何 IoU。

### `WireInstance` 的新增欄位（additive，向後相容）

```python
@dataclass
class WireInstance:
    wire_id: int
    color: str                              # 既有；ridge-only 偵測時填 "unknown"（誠實，不瞎猜顏色）
    path_px: list[tuple[float, float]]
    endpoint_a: WireEndpoint
    endpoint_b: WireEndpoint
    confidence: float
    ambiguous: bool
    crossed_junction_count: int = 0         # 既有
    detection_methods: list[str] = field(default_factory=lambda: ["color"])  # NEW
```

`detection_methods` 是純新增欄位、有預設值，不影響任何既有呼叫端；WS `_wire_message()`（`wire_worker.py:101-110`）多序列化一個 key，前端對訊息內未知欄位本來就不需要處理。

### 去重規則（Stage E 新增子步驟）

本專案的輸出空間已經在 Stage D 被離散化成 `(pin_id_a, pin_id_b)`，去重不需要幾何 IoU，只需比對這個離散 key：

```python
def _merge_cross_method_duplicates(wires: list[WireInstance]) -> list[WireInstance]:
    """Stage E extension. Merge a color-band WireInstance with an
    edge-agnostic one iff BOTH endpoints resolved to kind=="pin" and the
    unordered pin pair is identical. Never merges anything involving
    floating/ambiguous_tie - those stay as separate, honestly-reported
    entries (a partial resolve from one method is not evidence the other
    method's full resolve is wrong, but it's also not proof they're the
    same wire)."""
    by_key: dict[frozenset[str], list[WireInstance]] = {}
    passthrough: list[WireInstance] = []
    for w in wires:
        if w.endpoint_a.kind == "pin" and w.endpoint_b.kind == "pin":
            key = frozenset({w.endpoint_a.pin_id, w.endpoint_b.pin_id})
            by_key.setdefault(key, []).append(w)
        else:
            passthrough.append(w)
    merged: list[WireInstance] = []
    for key, group in by_key.items():
        if len(group) == 1:
            merged.append(group[0])
            continue
        # 2+ methods agree on the same pin pair - trust it more, not less
        colored = [w for w in group if w.color != "unknown"]
        base = colored[0] if colored else group[0]
        base.confidence = min(1.0, max(w.confidence for w in group) + 0.1)
        base.detection_methods = sorted({m for w in group for m in w.detection_methods})
        merged.append(base)
    return merged + passthrough
```

**衝突（非重複）的邊界情況——誠實聲明**：如果色相通道跟 ridge 通道對「同一個物理端點像素」各自吸附到**不同** pin（例如色相判 D7、ridge 判 D8），上面的 key 比對邏輯不會把它們當同一組合併——它們會各自留在 `passthrough`/各自的 `by_key` 條目裡，成為兩條獨立回報的 `WireInstance`。這是刻意的：不猜哪個對，讓下游看到兩個矛盾的候選，比悄悄選一邊誠實。**這次不新增 `EndpointKind` 第四個值**——保持三值不擴充，衝突用「兩條 WireInstance 同時存在、pin_id 不同」這個既有可表達的形狀就講清楚了，新增列舉值會牽動 `api-contract.md §2` 明確列出的三選一契約，成本大於好處。

### 成本影響（相對既有 45-90ms/frame 預算）

一個 ridge pass 的量級跟一個色相 pass 相近（灰階梯度 mask 換 HSV mask，同樣要走形態學清理+骨架化）。4 色 + 1 ridge = 5 pass，仍比全 9 色頻段方案更便宜。**但這是估計值，上線前必須用 `tools/wire_trace_debug.py` 對真實畫面實測**。

---

## 2.2 導引任務 + 打勾核對：100% 古典，AI 角色精確限定在窄復原縫

**核對步驟本身不需要 AI**，因為 `snap_endpoint()` 已經產出帶身分的、精確的、免費的答案；唯一可能有價值的 AI 縫，是古典管線這一 tick 完全沒找到候選端點時的復原角色，而且經過 §2.1 的 Stage A' 加強後，這個縫比純 HSV 時期更窄。

### `GuidanceStep` 資料模型（新檔 `backend/app/vision/guidance.py`，peer of `wire_tracer.py`）

```python
@dataclass
class GuidanceStep:
    step_id: str
    expected_pin_id: str            # 這一步驟要求插入的目標腳位——唯一權威依據
    expected_role: str | None = None    # 選填,純顯示用（例如 "TRIG"),不參與比對邏輯
    component_id: str | None = None     # 選填,串接 wiring-verification-architecture 的 ComponentSpec/plan_id,純上下文
    hint_color: str | None = None       # 選填,教學文案用的建議顏色,絕不作為比對依據

@dataclass
class GuidanceResult:
    step_id: str
    expected_pin_id: str
    status: Literal["pending", "correct", "wrong_pin", "uncertain"]
    actual_pin_id: str | None = None       # 僅 status=="wrong_pin" 時填
    confidence: float = 0.0
    as_of_ms: float = 0.0
    ai_hint: dict | None = None            # 僅窄復原縫觸發時填,見 §2.2c——絕不影響 status
```

四種 `status`（刻意不是布林勾/叉——沿用本專案「絕不用二元值假裝有確定性」的既有慣例，跟 `wire_tracer.py` 的 `floating`/`ambiguous_tie`、`wiring-verification-architecture.md` 的 `not_testable`/`stale` 同一個精神）：

- **`correct`** — 目標腳位上偵測到吸附的線材端點
- **`wrong_pin`** — 偵測到一個新出現的端點吸附到別的腳位，誠實點名 `actual_pin_id`（比裸叉更有用，且幾乎免費）
- **`pending`** — 還沒偵測到任何新端點，不是錯，是還沒插
- **`uncertain`** — 證據衝突或不足以下判斷，絕不硬猜成 `correct` 或 `wrong_pin`

### 比對邏輯——純函式，重用 `WireTraceResult`/`WireEndpoint`，零感知判斷

```python
def evaluate_guidance_step(
    step: GuidanceStep,
    wire_result: WireTraceResult,
    baseline_pin_ids: frozenset[str],
) -> GuidanceResult:
    now_ms = wire_result.ts_ms
    if wire_result.board_tracking == "searching":
        return GuidanceResult(step.step_id, step.expected_pin_id, "uncertain", confidence=0.0, as_of_ms=now_ms)

    endpoints = [ep for w in wire_result.wires for ep in (w.endpoint_a, w.endpoint_b)]

    # 目標腳位本身是不是某個端點的 ambiguous_tie 候選之一?落在兩個腳位正中間、
    # 剛好其中一個是目標腳位——不能悄悄當 "pending" 忽略,那是有證據但證據衝突
    for ep in endpoints:
        if ep.kind == "ambiguous_tie" and step.expected_pin_id in ep.candidates:
            return GuidanceResult(step.step_id, step.expected_pin_id, "uncertain", confidence=0.0, as_of_ms=now_ms)

    occupied_now = {ep.pin_id for ep in endpoints if ep.kind == "pin"}
    if step.expected_pin_id in occupied_now:
        conf = max(ep.confidence for ep in endpoints if ep.kind == "pin" and ep.pin_id == step.expected_pin_id)
        return GuidanceResult(step.step_id, step.expected_pin_id, "correct", confidence=conf, as_of_ms=now_ms)

    new_pins = occupied_now - baseline_pin_ids
    if len(new_pins) == 1:
        actual = next(iter(new_pins))
        conf = max(ep.confidence for ep in endpoints if ep.kind == "pin" and ep.pin_id == actual)
        return GuidanceResult(step.step_id, step.expected_pin_id, "wrong_pin", actual_pin_id=actual, confidence=conf, as_of_ms=now_ms)
    if len(new_pins) > 1:
        # 同一個 tick 內冒出 2 個以上新端點——不知道哪個是「這一步驟的那條線」,不猜
        return GuidanceResult(step.step_id, step.expected_pin_id, "uncertain", confidence=0.0, as_of_ms=now_ms)

    return GuidanceResult(step.step_id, step.expected_pin_id, "pending", confidence=0.0, as_of_ms=now_ms)
```

整段函式沒有一行做感知判斷——`in`/`==`/集合差集，是字串與集合比較，不是影像理解。`baseline_pin_ids` 由呼叫端在每次 `POST /api/guidance/step` 設定新目標時，拿當前 `occupied_now` 拍一張快照存起來。

### AI 角色——精確限定，不是「順便問一下」

**在 `evaluate_guidance_step()` 的決策路徑裡，AI 角色為零。** 不把 AI 放進打勾/打叉本身，即使只是低頻率輔助角色。

唯一被允許的窄角色，精確定義觸發條件、資料流、輸出範圍，不含糊：

- **觸發條件（全部同時成立才觸發，缺一不可）**：
  1. `status == "pending"` 已經連續超過設定門檻（例如 `guidance.ai_fallback_after_s = 5.0`，新設定，預設值需要之後跟產品一起校正）
  2. `wire_result.wires` 裡，經過 Stage A（色相）**與** Stage A'（ridge，已經是色相無關的）兩條通道都沒有找到落在 `expected_pin_id` 附近的候選端點——因為 §2.1 已經加了色相無關的 Stage A'，這個殘餘缺口比純 HSV 時期更窄，現在只剩「連形狀/邊緣線索都抓不到」的案例（例如黑線在黑桌墊上）
  3. 這個 step 還沒對這次 pending 觸發過 AI 呼叫（每個 step 最多一次，避免延遲/成本疊加，也避免把一個低召回率的訊號當成持續輪詢的依據）
- **動作**：非同步、不卡住任何回應路徑，對 `expected_pin_id` 已知像素座標裁切一個很小的 crop（邊長略大於 `SNAP_RADIUS_PX` 的正方形，不是整張畫面——這正是「已知區域二元判斷」而非「開放場景定位」的關鍵），問一個二元問題：「這個裁切畫面裡，是否看得到一條線材的端點插入/接觸中央區域」
- **輸出去向**：只填 `GuidanceResult.ai_hint = {"present_guess": bool, "note": str}`，**絕不**改寫 `status`。即使 `ai_hint.present_guess == True`，`status` 仍然停在 `pending`（UI 上呈現一個明確跟打勾/打叉視覺分開的「AI 粗略提示」徽章）。
- **為什麼不多做**：DiffSpot 局部 diff 偵測基準測到的低召回率（<41%）加上低誤報率（1.6%），意味著這個提示更可能「保守漏報」而不是「自信答錯」——這正是為什麼設計上把它硬隔在 `ai_hint` 這個獨立、非權威欄位裡，不是放寬心地讓它偶爾參與 `status` 決策。

---

## 2.3 資料流圖與 WS 訊息設計

### 端到端資料流

```
Camera frame (FrameBus.get_latest)
        │
        ├──────────────────────────────► VisionWorker (不變)
        │                                       │
        │                                       ▼
        │                                DetectionState (pins[], tracking) ── 既有
        │                                       │
        ▼                                       │
WireTraceWorker tick（既有執行緒,本次擴充內部邏輯,不新增 thread）
        │   detection = detection_state.get()  ◄──────────────┘
        │
        ├─ Stage A   (既有) segment_color() × DEFAULT_COLORS[red,yellow,green,brown]
        ├─ Stage A'  (NEW)  segment_edge_ridge() — 色相無關,見 §2.1
        │        both → Stage B skeletonize_mask() → Stage C trace_branches()
        │        （色相分支 color=實際色名；ridge 分支 color="unknown"）
        ├─ Stage D   (既有,原封不動) snap_endpoint() — 兩種來源的端點統一走同一函式
        ├─ Stage E   (既有,擴充) 組裝 WireInstance[] + 新增 _merge_cross_method_duplicates()
        │
        ▼
   WireTraceResult  (既有型別,wires[] 的元素多一個 detection_methods 欄位,additive)
        │
        ├──► WireTraceState.set(result)              既有
        ├──► publish({"type":"wire_trace", ...})      既有 WS 訊息,+detection_methods 欄位
        │
        ▼  (NEW — 同一 tick、同一執行緒,不是新 worker,成本 <1ms,跟 snap_endpoint 同量級)
   if guidance_step is not None:
        result_g = evaluate_guidance_step(guidance_step, result, baseline_pin_ids)
        guidance_state.set(result_g)
        publish({"type":"guidance_check", ...})       NEW WS 訊息型別
             │
             └─ 若觸發條件（§2.2）全部成立
                        │
                        ▼
             async, per-step 最多一次, 非阻塞
             VLM crop 二元判斷 (expected_pin_id 已知座標裁切)
                        │
                        └─ 回填 GuidanceResult.ai_hint（不改 status）
                        └─ publish 一則後續 "guidance_check" 更新（同 step_id,ai_hint 非空)
```

### WS 新訊息型別 `guidance_check`

```jsonc
{
  "type": "guidance_check",
  "board_id": "arduino-uno-q",
  "step_id": "step-3-echo",
  "frame_id": 18234,
  "ts_ms": 1721990401234.0,
  "board_tracking": "locked",
  "expected_pin_id": "D7",
  "status": "wrong_pin",          // "pending" | "correct" | "wrong_pin" | "uncertain"
  "actual_pin_id": "D8",          // 僅 status=="wrong_pin" 時出現
  "confidence": 0.84,
  "ai_hint": null                  // 僅窄復原縫觸發時非 null，格式 {"present_guess":bool,"note":str}
}
```

跟現有 `wire_trace` 訊息同一個 per-client latest-only 佇列語意，不是新的同步保證，慢連線一樣可能被下一則 `detection`/`wire_trace` 蓋掉。

### 新 REST 端點（沿用 `POST /api/calibrate` 的 200+ok 慣例，不是真錯誤碼）

```
POST /api/guidance/step   { "expected_pin_id": "D7", "expected_role": "ECHO" }
  → 200 { "ok": true, "step_id": "step-3-echo" }
  設定當前 guidance step,同時對 WireTraceState 目前的 occupied_now 拍照存成 baseline_pin_ids

GET  /api/guidance/state  → 200 <同 GuidanceResult 形狀>   （同步、便宜,跟 verdict 的讀取成本同量級)
```

### 對既有型別的重用 vs 擴充，一覽

| 型別/訊息 | 處置 |
|---|---|
| `PinDetection` / `DetectionResult`（`interface.py`） | 完全不動 |
| `WireEndpoint` / `EndpointKind`（三值） | 完全不動——沒有新增第四個 kind |
| `WireInstance` | 擴充：新增 `detection_methods: list[str]`（有預設值,additive） |
| `WireTraceResult` | 完全不動 |
| WS `wire_trace` | 擴充：`wires[].detection_methods` 新欄位,additive |
| WS `guidance_check` | **新增型別**,沿用既有 `type` 擴充點慣例 |
| `snap_endpoint()` | 完全不動,兩個新舊來源都直接重用 |

---

## 2.4 誠實失敗模式對照表

- **真的電纜（USB/電源線）恰好終止在某腳位 16px 內**：Stage A' 的 ridge 線索對「固定寬度圓柱體」這個幾何家族無法區分杜邦線跟其他電纜，只能靠 Stage D 吸附半徑的統計小機率收斂——真的發生時會被誤判成一條有效的 `WireInstance`，不是 bug，是這個技術路線本身承認的殘餘假陽性來源
- **黑線在黑桌墊上（或任何低對比度+低飽和度的組合）**：色相分色（低飽和度）跟邊緣/ridge（低對比度）兩條線索同時失效——這是任何純古典技術都無法保證解決的殘餘案例，AI 復原縫是唯一的緩解，但緩解不是解決（<41% recall）
- **兩條真的不同的物理線恰好都終止在同一組 pin pair**（例如兩條線都接 5V↔D7 做冗餘）：`_merge_cross_method_duplicates()` 的離散 key 去重邏輯會把它們錯誤合併成一條——已知限制，demo 場景少見但真實存在
- **色相通道跟 ridge 通道對同一物理端點判到不同 pin**：兩者都誠實保留、不合併、不猜——但下游 `evaluate_guidance_step()` 的 `len(new_pins) > 1` 分支會把整個 step 判成 `uncertain`，即使其中一個判斷其實是對的——誠實但保守，不是「挑一個看起來對的」
- **導引比對的 0.5s tick 節流延遲**：使用者插好線的瞬間到 UI 顯示 `correct`，最多有一個 tick（≤0.5s）+ 影格偵測延遲的落差——跟 `wire_trace` 訊息本來就有的節流延遲同一件事，使用者體感上「即時打勾」不會是零延遲
- **同一 tick 內兩個以上新端點同時出現**：一律回報 `uncertain`，不猜哪個是「這一步驟的那條線」——代價是使用者體感上「明明插對了怎麼沒打勾」，需要在 UI 文案上說明「請一次只操作一條線，或稍等重新偵測」
- **`ai_hint` 的窄復原縫本身**：DiffSpot 基準顯示的低召回率意味著它更常「沒看到」而不是「看錯」——但使用者不能因為 `ai_hint.present_guess == false` 就放心以為真的沒插；`ai_hint` 只在 `pending` 超時後才觸發、只給提示不給判決，這個誠實限制必須在 UI 文案裡講清楚，不能被誤讀成「AI 幫你確認過了」

---

## 2.5 Milestones（延續 M0-19，新增 M20-24）

**M20 — Stage A' ridge/edge 色相無關遮罩，離線驗證（無 snap、無 WS，鏡照 M15 的驗收模式）**
新增 `segment_edge_ridge()`，對照真實擷取畫面驗證。驗收：真實中性色（灰/白/黑其中一色）杜邦線，離線對真實擷取畫面跑 `segment_edge_ridge()` → 骨架端點落在真實端點附近數像素內；另外對一張完全沒有線材、只有真實桌面雜物的畫面跑同一函式，用 `tools/wire_trace_debug.py` 記錄假陽性骨架分支數量（誠實記錄下來，不是假設，不預先宣稱數字）。

**M21 — Stage D/E 跨方法去重整合 + `WireTraceWorker` 即時串接（鏡照 M17）**
`trace_wires()`/`trace()` 接上 `include_edge_agnostic` 開關與 `_merge_cross_method_duplicates()`。驗收：真實紅線（色相可偵測）+ 真實中性色線（僅 ridge 可偵測）同時入鏡 → WS `wire_trace` 顯示兩條獨立 `WireInstance`，一條 `color:"red", detection_methods:["color"]`，一條 `color:"unknown", detection_methods:["edge"]`；額外用一條色相頻段內的線，人為確認兩通道同時命中同一 pin pair 時，只輸出**一條**合併後的 `WireInstance`，`detection_methods` 為 `["color","edge"]`，confidence 高於任一單一通道的原始值。既有 88 個測試不受影響。

**M22 — 導引式單腳位打勾，純古典（100% 無 AI）**
新增 `app/vision/guidance.py`、`POST /api/guidance/step`、`GET /api/guidance/state`，接進既有 `WireTraceWorker` tick，新增 WS `guidance_check` 型別。**驗收（使用者原話給的具體場景）**：導引步驟指定 `expected_pin_id="D7"`；使用者把真線插進 D8 而非 D7 → `status` 在一個 tick 內變成 `"wrong_pin"`，`actual_pin_id:"D8"`，絕不顯示 `"correct"`。接著使用者把線從 D8 移到 D7 → 一個 tick 內變成 `"correct"`。線還沒插上時 → 一直停在 `"pending"`，不猜。

**M23 — 導引比對邊界情況：ambiguous_tie 與同時多變偵測**
驗收：人為擺出一個端點恰好等距落在 D7/D8 中間，且 `expected_pin_id="D7"` → `status` 回報 `"uncertain"`，不是 `"pending"` 也不是誤判 `"correct"`；人為在同一個節流窗口內讓兩個新端點同時出現 → `status` 回報 `"uncertain"`，不猜哪個是「這步驟的那條線」。

**M24（獨立可跳過的里程碑）— 窄復原縫 AI 提示，僅 advisory，不影響 status**
交付 §2.2 描述的非同步、每步驟最多一次、裁切限定範圍的 VLM 二元判斷，只填 `ai_hint`。驗收：刻意讓一條線同時逃過色相頻段跟 Stage A' 的 ridge 偵測，`status` 停在 `pending` 超過門檻秒數後，斷言**恰好觸發一次**非同步呼叫，結果只出現在 `ai_hint`，`status` 全程沒有被這次呼叫改成 `correct` 或 `wrong_pin`——證明 AI 角色始終是 advisory，不是 authoritative。

---

## 引用來源

- 本專案既有檔案：`backend/app/vision/wire_tracer.py`、`backend/app/wire_worker.py`、`backend/app/vision/interface.py`、`docs/api-contract.md`、`docs/wire-recognition-design.md`、`docs/wiring-verification-architecture.md`
- [VLMs Trace Without Tracking: Diagnosing Failures in Visual Path Following](https://arxiv.org/pdf/2605.15672) — arXiv 2605.15672
- [TraversalBench: Challenging Paths to Follow for Vision Language Models](https://arxiv.org/html/2604.10999)
- [Molmo and PixMo](https://arxiv.org/pdf/2409.17146), [MolmoPoint](https://arxiv.org/pdf/2603.28069), [RoboPoint](https://arxiv.org/html/2406.10721v1)
- [DiffSpot: Can VLMs Spot Fine-Grained Visual Differences in Web Interfaces?](https://arxiv.org/html/2605.29615v1) — arXiv 2605.29615
- [AgroVG: A Large-Scale Multi-Source Benchmark for Agricultural Visual Grounding](https://arxiv.org/html/2605.22034)
- [The Frangi filter — designed for vessel or tubular structures](https://medium.com/@SuriNaren/the-frangi-filter-127ea9ab27a9)
- [Ridge operators — scikit-image documentation](https://scikit-image.org/docs/dev/auto_examples/edges/plot_ridge_filter.html)
- [Robust Detection of Extremely Thin Lines Using 0.2mm Piano Wire, arXiv 2503.13473](https://arxiv.org/pdf/2503.13473)
- [OpenCV: How to Use Background Subtraction Methods](https://docs.opencv.org/3.4.15/d1/dc5/tutorial_background_subtraction.html)
- [OpenCV: cv::BackgroundSubtractorMOG2 Class Reference](https://docs.opencv.org/3.4.20/d7/d7b/classcv_1_1BackgroundSubtractorMOG2.html)
- [Adaptive Thresholding with OpenCV — PyImageSearch](https://pyimagesearch.com/2021/05/12/adaptive-thresholding-with-opencv-cv2-adaptivethreshold/)
- [Local Adaptive Thresholding — ScienceDirect Topics overview](https://www.sciencedirect.com/topics/computer-science/local-adaptive-thresholding)
- [What is Non-Max Merging? (Roboflow)](https://blog.roboflow.com/non-max-merging/)
- [A Deep Dive Into Non-Maximum Suppression (NMS) — Built In](https://builtin.com/machine-learning/non-maximum-suppression)
- [PointArena: Probing Multimodal Grounding Through Language-Guided Pointing, arXiv 2505.09990](https://arxiv.org/pdf/2505.09990)
- [Point-It-Out: Benchmarking Embodied Reasoning for VLMs in Multi-Stage Visual Grounding, arXiv 2509.25794](https://arxiv.org/html/2509.25794)

**沒有任何檔案在 `board-vision` 下被建立或修改（除本文件）。**
