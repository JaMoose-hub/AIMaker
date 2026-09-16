# Board Vision 軟體架構計畫書

**專案定位**：AI Maker Studio / AI Maker Runtime（Physical AI 平台提案）— MVP 能力①「視覺化控制板辨識」及其延伸能力
**文件版本**：v1.1（2026-07-29）——範圍聚焦版：核心範圍收斂為五項能力、**全地端**（VLM 以 Ollama 重新定義）；雲端計畫生成與電氣驗證移列後期
**狀態標記凡例**：✅ 已實作並實測 ｜ 📐 設計完成待實作 ｜ ⬜ 未開始

---

## 1. 願景與定位

AI Maker Studio 的核心主張：**用相機 + AI 把「實體電子開發」變成有即時視覺回饋的引導式體驗**。使用者把開發板放在鏡頭下，系統即時辨識板卡、標註每支腳位的能力、看懂使用者的接線、按步驟引導接線並即時打勾/糾錯，最終目標是讓初學者第一次接電路就有「有人在旁邊看著教」的體驗。

Board Vision 是這個主張的第一個落地能力，目前已在真實硬體（Arduino UNO Q + 羅技 C920 / iPhone 鏡射）上端到端運作。

### 產品能力地圖

**核心範圍（本波交付，全地端、零雲端依賴）**：

| 能力 | 內容 | 狀態 |
|---|---|---|
| **① 視覺化板卡辨識** | 即時偵測板卡姿態、標註 32 腳位、能力卡片、NL 查詢、新板校正登錄 | ✅ 完成（M0–M7） |
| **①+ 杜邦線辨識** | 線材偵測、端點吸附到腳位、即時 overlay | ✅ 完成（M15–M17） |
| **①+ 顏色無關偵測** | 不限顏色的線材偵測（ridge/平行邊緣備援通道） | 📐 已設計（M20–M21） |
| **①+ VLM 導引接線＋幾何打勾** | VLM 當「導師」逐步引導接線、即時旁述與糾錯；打勾判定由幾何引擎裁決（§6.4） | 📐 已設計（M22–M26、M28–M30） |
| **③ 地端 VLM 即時互動** | 本機 VLM（Ollama）觀看串流：旁述、元件辨識、異常提醒、問答 | 📐 已設計（M28–M30） |

**後期範圍（設計已完成，本波不實作）**：

| 能力 | 內容 | 狀態 |
|---|---|---|
| ② 接線電氣驗證 | 透過板端 firmware 做電氣層驗證（訊號注入/量測） | 📐 已設計（M8–M14），後期 |
| ③ 雲端接線計畫生成 | 使用者說目標 → 雲端 LLM 產出結構化接線計畫 | 📐 已設計（M27），後期——核心範圍先用內建範本計畫，計畫格式/驗證器不變，屆時只是換「作者」 |

---

## 2. 架構總則：三層信任/延遲模型

這是整個系統的憲法。所有元件的權責、延遲預算、部署位置都由此推導。

| | **Tier 0 — 古典幾何**（核心） | **Tier 1 — 地端 VLM**（核心，Ollama） | **Tier 2 — 雲端 LLM**（後期） |
|---|---|---|---|
| 執行者 | VisionWorker（~30Hz）、WireTraceWorker（~2Hz）、guidance 引擎 + PlanRuntime | VLMWorker + Ollama（本機獨立行程） | 雲端 Plan Service |
| 延遲 | 毫秒級 | 秒級（GPU 4B 模型 1.5–3s/幀） | 數秒（含驗證重試至 ~20s） |
| 權威性 | **唯一權威**——打勾/打叉、線材端點、電氣判定只由這層決定 | **純 advisory**——輸出永遠標示 advisory，任何條件下不能改寫 Tier 0 判定 | **從不被信任**——輸出是候選計畫，必經本地確定性驗證器全數通過 |
| 看得到什麼 | 每一張即時影格 | 本機 keyframe + Tier 0 結構化狀態（影像不出 PC） | 永遠看不到即時影像，只收文字 |
| 離線 | 完全可用 | 完全可用（本機推論） | 不可用 → 核心範圍本來就不依賴它（內建計畫） |

**核心範圍 = Tier 0 + Tier 1，一台 PC 全包**。Tier 2 是後期加法：計畫格式、驗證器、執行引擎在核心範圍就已就位，雲端上線時只是多一種計畫「作者」，本地架構一行不改。

### 為什麼這樣分層（實證依據，非直覺）

本專案在設計過程中做了大量實測與文獻查證，三層模型的每條界線都有證據：

1. **VLM 不能碰腳位級判定**：麵包板線材路徑追蹤 benchmark 最佳模型僅 71%（arXiv 2605.15672）；局部視覺差異偵測最佳 recall 40.7%（DiffSpot）；本專案實測 A/B——手機 VLM 自信宣稱藍線插在 5V，實際放大查證 5V 插座是空的。**自信、錯誤、不可追溯**。反之古典幾何的 `snap_endpoint()` 精確、免費、已在真板上驗證（吸附距離 15.8px 實測）。
2. **雲端 LLM 產計畫必須過本地驗證**：板級設計 benchmark（HWE-Bench）最佳模型單項檢查通過率 77.73%、**完全正確率 <10%**；但失敗型態（幻覺腳位、電壓違規、一腳多用）恰好全部是確定性查表 lint 可 100% 攔截的類別。
3. **哲學一句話**：LLM 生成、機器驗證、advisory 與 authoritative 在 schema 層面就分開、never guess。

---

## 3. 系統部署架構

```
┌─ Browser (React + TypeScript SPA) ──────────────────────────────┐
│  <img src="/video"> MJPEG ── WS /ws/detections ── REST /api/*   │
│  訊息類型：detection / wire_trace / wiring_check /              │
│    guidance_check / plan_progress / vlm_insight（未知型忽略）    │
└────────────────────────────┬────────────────────────────────────┘
                  127.0.0.1:8100（localhost only）
┌─ Windows PC（FastAPI 後端，單一 process）──┴─────────────────────┐
│                                                                  │
│  相機來源（FrameSource 抽象，設定切換）                            │
│    ├─ DeviceCameraSource（webcam；MSMF/DirectShow 可設定）✅      │
│    ├─ WindowCaptureSource（任意視窗如手機鏡射）✅               │
│    └─ SyntheticCameraSource（合成場景，開發/測試用）✅            │
│              │                                                   │
│              ▼                                                   │
│  CaptureService ─► FrameBus（單槽最新幀，多 reader 各自獨立）      │
│    ├─ reader① MJPEG encoder                    (Tier0) ✅        │
│    ├─ reader② VisionWorker ~30Hz 姿態+腳位     (Tier0) ✅        │
│    ├─ reader③ WireTraceWorker ~2Hz 線材+吸附   (Tier0) ✅        │
│    │     └─ guidance 引擎 + PlanRuntime         (Tier0) 📐       │
│    ├─ reader④ WiringWorker 電氣驗證（能力②）    (Tier0) 📐       │
│    └─ reader⑤ VLMWorker                         (Tier1) 📐       │
│          │ keyframe JPEG + Tier0 結構化狀態（loopback，不出機器）  │
│          ▼                                                       │
│  Ollama（本機獨立行程，127.0.0.1:11434，OpenAI 相容 API；        │
│  模型 qwen3-vl:8b / :4b；Snapdragon NPU 後期走 GenieX）(Tier1) 📐│
│                                                                  │
│  PlanValidator（確定性閘門）◄─ 內建範本計畫 profiles/plans/       │
│  profiles/（板卡 profile、計畫庫——全部本地，離線可用）             │
└──────────────────────────────────────────────────────────────────┘

（後期）┌─ Cloud ─────────────────────────────────────────────────┐
        │  Plan Service：LLM structured output      (Tier2) 📐 後期│
        │  上線時經 PlanAuthorClient outbound HTTPS 接入，          │
        │  產出仍走同一個本地 PlanValidator——架構已預留，本波不建   │
        └──────────────────────────────────────────────────────────┘
```

**資料邊界（提案的隱私底線）**：即時影像/MJPEG/任何影格**永遠不上雲**。能離開 PC 的只有：目標文字、board_id、腳位表、元件規格全文，以及使用者明確按「拍照辨識」時的單張靜態照片（送出前可預覽）。

---

## 4. Tier 0：古典幾何層（✅ 核心已實作）

### 4.1 免訓練 CV 管線（能力①，已實測）

```
擷取 720p30 → ROI 閘門 → ORB(1500) 特徵比對參考圖 → Lowe ratio
→ findHomography(RANSAC) 剔除外點 → solvePnP(IPPE) + RefineLM 6-DoF 姿態
→ LK 光流幀間追蹤 → One-Euro 姿態平滑
→ projectPoints 把 32 腳位（z=8.5mm 排針座高）+ 板框投影到影像座標
```

- **免訓練**是刻意選擇：UNO Q 是 2025 年 10 月的新板、無公開資料集；免訓練 = 新板卡零資料成本上線（一次性校正拍照即可，已做成產品內功能）。
- 狀態機遲滯：3 好幀 → LOCKED、壞幀 → STALE（overlay 凍結淡化）、15 壞幀 → SEARCHING。
- 排針座 8.5mm 高度視差用 3D pin map + PnP 解決（純 2D homography 在傾斜視角會偏差 ~2 個腳距）。

### 4.2 杜邦線偵測（已實測）

```
Stage A  HSV 分色（red/yellow/green/brown/blue 五頻段）+ 寬度過濾
         （距離變換攔截大面積色塊，於骨架化前執行）
Stage A' ridge/平行邊緣偵測（色相無關備援通道）📐 M20
Stage B  骨架化（Guo-Hall）
Stage C  骨架圖走訪 → 候選分支
Stage D  端點吸附：SNAP_RADIUS_PX=16 內取最近腳位 → pin；半徑內無腳位
         → floating；等距平手 → ambiguous_tie（絕不猜）
Stage E  組裝 WireInstance + 兩端皆未接觸腳位者不回報
```

實測校正的細節（量測數據記錄在程式註解與設計文件）：

- red / brown / blue 三頻段以真實線材採樣校正（brown 採樣 ~170px、blue 採樣 ~4,800px 並將飽和度下限 60→100）；yellow / green 為室內場景調校值，程式註解明載待真實樣本再校正。black 因桌面陰影假陽性（單幀 ~97 條假線）明確排除並記錄為已知限制。
- **寬度過濾**：距離變換量測連通區最大內部半寬——真線 6.4px、鏡頭暗角色塊 25.7–50.5px，以 14px 為界攔截大面積假陽性。
- **吸附即過濾**：只有終止在已知腳位 16px 半徑內的偵測才有意義，這把「桌面上任何細長物體都可能誤判」的開放問題收斂成封閉問題（USB 線、電源線不會恰好終止在排針上）。

### 4.3 導引式打勾引擎（📐 M22–M23）

純函式 `evaluate_guidance_step()`：字串與集合比較，零感知判斷。四種狀態刻意不是布林——`pending / correct / wrong_pin(點名實際腳位) / uncertain(證據衝突不硬猜)`。

### 4.4 能力②電氣驗證（📐 已設計）

WiringWorker 持續狀態機 + ComponentSpec 封閉操作詞彙 DSL + 診斷分類法（wiring_absent / electrical_signature_mismatch 等）。與能力③共用同一份計畫格式（見 §5.2）。

---

## 5. 計畫與導引執行層（核心範圍，全地端；📐 M25–M26）

### 5.1 流程（核心範圍版——計畫來自內建範本，不依賴雲端）

```
內建範本計畫（profiles/plans/*.plan.json，隨產品出貨；
              例：「HC-SR04 超音波感測器四步接線」）
  → 本地 PlanValidator 確定性驗證（見下）——任一 reject 級違規整份拒收
  → 通過入庫 → 使用者選擇計畫 → PlanRuntime 逐步執行（餵 Tier 0 打勾引擎）
  → VLM 導引旁述全程伴隨（§6.4）
```

計畫的「作者」是可替換的：核心範圍 = 人工編寫的內建範本；後期 = 雲端 LLM 生成（M27）或本地 Ollama 文字模型生成——**無論作者是誰，都走同一個 PlanValidator、同一個 PlanRuntime**，這是架構已預留的擴充點而非重構點。

### 5.2 GuidancePlan：一種格式服務兩個能力

`steps[]` 每步就是 GuidanceStep 的形狀（`expected_pin_id` 等契約欄位 + `tutorial_text/why` advisory 欄位，**兩種信任等級在 schema 裡就分開**）；驗證器從 steps 推導 `pin_assignment`，後期可直接作為能力②電氣驗證的輸入——作者只是「作者」，本地古典引擎才是「執行者」，不需要第二種格式。

### 5.3 PlanValidator 檢查項（全部查表/字串比較，零模型）

| 類別 | 例 |
|---|---|
| 引用存在性 | `PIN_NOT_FOUND`（幻覺腳位 D99）、`UNKNOWN_COMPONENT`、`UNKNOWN_TERMINAL` |
| 電氣安全 | `VOLTAGE_INCOMPATIBLE`：ECHO(5V)→A0 拒收（A0 不耐 5V，規則直接來自 board.json 機讀事實，非硬編碼）；ECHO→D3 拒收（3.6V 上限） |
| 能力匹配 | `CAPABILITY_MISMATCH`：要 PWM 就必須是 PWM 腳 |
| 計畫完整性 | 一腳一線、terminal 不重不漏、step_id 唯一 |

**驗證器永不放寬，寧可明確失敗**。內建範本計畫也一樣要過驗證（人也會寫錯）；後期接上 LLM 作者時，失敗的違規清單餵回 LLM 修復，最多重試 2 次。

### 5.4 PlanRuntime 多步驟狀態機

- auto-advance：current step `correct` 連續 2 tick（~1 秒穩定）才推進——防單幀抖動假推進；教學情境可切 confirm 模式
- **回頭核對**：已完成步驟的腳位持續被監看，線被拔掉 → plan 轉 `paused_regression`、引導修復、插回自動恢復
- 進度走新 WS 訊息 `plan_progress`（事件驅動），權威狀態可隨時 `GET /api/plans/current/progress` 同步讀回

---

## 6. Tier 1：地端 VLM 層——以 Ollama 定義（📐 M28–M30）

### 6.1 Runtime 定案：Ollama

核心範圍的 VLM runtime **就是 Ollama**，開發、demo、內部部署同一套：

| 項目 | 定案 | 說明 |
|---|---|---|
| Runtime | **Ollama**（Windows 原生安裝，本機獨立行程） | 自研 multimodal engine 對 vision 模型支援成熟；模型管理一行 `ollama pull`；核心 MIT 授權 |
| 模型 | **`qwen3-vl:8b`**，<8GB VRAM 機器自動降 **`qwen3-vl:4b`** | 同尺寸 OCR 最強（讀元件絲印如 "HC-SR04" 直接吃這能力）；同家族換檔 prompt 不用改 |
| API | OpenAI 相容 `POST http://127.0.0.1:11434/v1/chat/completions`（影像走 base64） | 後端用 httpx 呼叫；結構化輸出用 Ollama 的 JSON mode |
| 部署 | 安裝 Ollama + `ollama pull qwen3-vl:4b` 兩步完成 | 模型檔本地快取，之後完全離線 |
| 延遲現實 | GPU：4B 約 1.5–3s/幀、8B 約 3–6s/幀 → 旁述節奏 0.2Hz；CPU-only：15–40s/幀 → **只開放使用者主動提問**，不做連續旁述 | 誠實面對，不硬撐 |
| 後期選項 | llama-server（出貨打包、鎖版本）；Qualcomm GenieX（Snapdragon NPU，「跑在 AI PC NPU 上」的提案賣點，developer preview） | 全部 OpenAI 相容——換 runtime 只換 endpoint URL，client code 一行不改 |

### 6.2 VLMWorker 設計

- FrameBus 第五個獨立 reader，照抄 WireTraceWorker 模式：自己的執行緒、自己的節奏、Ollama 崩潰不拖垮幾何管線（獨立行程 + HTTP 隔離，`kill` Ollama 後幾何照跑、重啟自動恢復）
- 四類觸發：定時旁述（0.2Hz，CPU-only 機器預設關閉）、guidance 逾時 ai_hint（每步驟最多一次）、場景事件（訂閱 Tier 0 狀態轉變，不做像素幀差）、使用者提問
- latest-only 單槽：推論中新觸發覆蓋舊請求；結果太舊（>10s）直接丟棄不發布——寧可沉默也不用過期畫面誤導

### 6.3 鐵律：VLM 輸出永遠改不了判定

架構層面強制而非紀律約定：VLMWorker 對判定狀態**沒有任何寫入路徑**，唯二輸出是 advisory 訊息 `vlm_insight` 和獨立欄位 `ai_hint`——打勾函式的簽名裡讀不到它們，型別系統上就寫不進去。

### 6.4 VLM 導引接線體驗（核心能力「VLM導引正確打勾」的精確定義）

使用者體感是「VLM 導師帶著我接線、接對了打勾」；架構上是**兩個角色的分工**：

```
VLM  = 導師的「嘴巴」：說明步驟、旁述進度、糾錯時好好講話、回答提問
幾何 = 導師的「眼睛與裁判」：判定 correct / wrong_pin / pending / uncertain
```

運作迴圈（事件驅動，掛在 PlanRuntime 的狀態轉變上）：

1. **步驟開始**：UI 立即顯示範本計畫的 `tutorial_text`（零延遲、確定性）；VLM 同步收到「當前步驟 + Tier 0 結構化狀態」非同步產生開場旁述（「接下來把黃色線從 Trig 接到 D7，D7 在板子右上排…」）
2. **接對（幾何判定 correct 穩定 2 tick）**：打勾動畫（Tier 0 觸發，即時）；VLM 收到事件後補一句過渡旁述（「漂亮，Trig 搞定，下一步 Echo」）
3. **接錯（幾何判定 wrong_pin）**：UI 立即顯示確定性糾錯文案「插到 D8 了，目標是 D7」（**內容來自幾何事實，不是 VLM 生成**）；VLM 非同步補充友善說明（「D8 跟 D7 是鄰居，往左一格就對了」）
4. **卡住（pending 逾時）**：M24 的 ai_hint 窄縫——VLM 看目標腳位裁切圖給低信心提示，明確標示 advisory、絕不變成打勾
5. **提問**：使用者隨時問「這顆藍色的是什麼？」→ VLM 以 keyframe + 目錄封閉分類回答

**關鍵設計——VLM 的輸入以 Tier 0 結構化狀態為主、影像為輔**：旁述 prompt 直接餵幾何管線的權威事實（板子鎖定與否、哪些腳位已接、當前步驟狀態），VLM 負責把事實「說成人話」而不是自己看圖判斷事實——這把幻覺空間壓到最小（它沒有機會「看錯」已經由幾何確認的事），也讓純文字旁述在無圖情境下依然成立、延遲更低。

打勾的視覺樣式與 VLM 旁述的視覺樣式在 UI 上強制分離（advisory 徽章 vs 權威勾叉），使用者永遠分得出「誰在說話、誰在裁判」。

---

## 7. 離線與降級策略

系統核心性質：**Tier 0 CPU-only、零訓練、可完全離線**。兩個 AI 層都是可拆卸的加法。

| 情境 | 體驗 |
|---|---|
| 全配（GPU + Ollama） | 完整：即時打勾 + VLM 導引旁述 + 元件問答 |
| CPU-only 機器 | 打勾即時不變；旁述改為使用者主動提問模式（誠實面對 15–40s/幀） |
| 無 Ollama（未安裝/行程掛掉） | 打勾、計畫執行完全不受影響；旁述面板自動收起、步驟說明退回範本文案 |
| 網路 | **核心範圍完全不需要網路**——計畫是內建的、VLM 是本機的（後期雲端生成上線後，斷網也只影響「產新計畫」，既有計畫照常） |

降級為運行時自動偵測，UI 隱藏對應功能而非報錯。**demo 永遠有底線形態**：最壞情況 = 今天已實測的系統 + 內建計畫逐步打勾。

---

## 8. 開發路線圖

**已完成**：

| 階段 | 里程碑 | 內容 | 狀態 |
|---|---|---|---|
| 基礎 | M0–M6 | 擷取/MJPEG/WS、pin DB、CV 管線、前端、測試、demo 腳本 | ✅ |
| 板卡登錄 | M7 | 校正引導拍攝、一次性新板登錄（`POST /api/calibrate`） | ✅ |
| 線材辨識 | M15–M17 | HSV 管線、吸附、即時整合 | ✅ |

**核心範圍（本波，依實作順序）**：

| 波次 | 里程碑 | 內容 | 依賴 |
|---|---|---|---|
| 第一波「打勾」 | **M22–M23** | 打勾引擎 `evaluate_guidance_step()` + 邊界情況（ambiguous_tie、同 tick 多端點） | 無——立即可動工 |
| 　（並行） | **M20–M21** | ridge 色相無關通道 + 跨方法去重 | 無 |
| 第二波「計畫執行」 | **M25–M26** | GuidancePlan schema + PlanValidator（M25，零相機可開發）；PlanRuntime 多步驟狀態機 + 內建範本計畫（M26） | M22 |
| 第三波「VLM 互動」 | **M28** | VLMWorker + Ollama 接入（先 mock 後真）、`vlm_insight`、`/api/vlm/ask` | 無（可與第二波並行） |
| 　 | **M24/M29** | ai_hint 窄縫經 VLMWorker 落地 + VLM 導引旁述（§6.4 事件迴圈） | M22、M26、M28 |
| 收尾 | **M30** | 端到端 demo：選計畫 → VLM 導引 → 逐步打勾 → 現場降級演練（關 Ollama 照常打勾） | 全部 |

**後期範圍（設計就緒，本波不動工）**：M18–M19（交叉線/多色場景、能力②視覺整合）、M8–M14（能力②電氣驗證）、M27（雲端計畫生成——上線時只是給 PlanValidator 多一種輸入來源）。

每個里程碑的驗收標準都是**真實硬體 + 誠實驗證**（詳見各設計文件），例如 M28 要求量測「VLM 推論不阻塞幾何管線」而非假設、M30 要求現場拔 Ollama 演練降級。

---

## 9. 風險登記簿（含已付學費的實證教訓）

| 風險 | 對策 | 出處 |
|---|---|---|
| VLM 自信誤判接線 | 三層信任模型：VLM 無判定寫入路徑 | 實測：VLM 稱藍線在 5V、實際 5V 空著 |
| 計畫內容電氣錯誤（不論作者是人、雲端或本地 LLM） | 本地確定性驗證器把關，失敗型態 100% 在攔截射程內 | HWE-Bench 全對率 <10%（LLM 作者）；人工範本也會寫錯，同樣過驗證 |
| 光照/場景變化擊穿顏色偵測 | 逐頻段實測校正 + 色相無關備援通道 + 吸附過濾 | black 頻段單幀 ~97 條假線（仍排除）；blue 頻段曾測得 ~22,000px 假陽性（已用飽和度下限修復並重新啟用） |
| 反光/距離擊穿特徵匹配 | 架設指引（俯拍、佔畫面 1/3+、鎖 AF/AE 後重鎖） | iPhone 鏡射實測：換位置後 123→9 匹配點 |
| 相機驅動層卡死（MSMF FrameServer） | capture_api 可切 DirectShow；避免串流中做裝置列舉 | C920 實測：MSMF 卡死、DSHOW 即開 |
| 線身垂弧假吸附（drape vs plugged） | 「兩端 floating 不回報」過濾緩解一部分；**尚無完整解法**，列為開放問題 | 本輪實測（iPhone 鏡射場景）：垂弧段兩端被分別吸附到 IOREF 與 A0，形成一條實際不存在的線 |
| 黑線黑桌墊（無任何古典訊號） | 誠實列為殘餘失效案例；ai_hint 是緩解不是解決 | 設計文件明文記載 |
| 慢速 WS 連線訊息被蓋 | latest-only 語意 + 權威狀態永遠可 REST 同步讀回 | 既定設計 |

---

## 10. 技術選型一覽

| 層面 | 選擇 | 備註 |
|---|---|---|
| 後端 | Python 3.11+ / FastAPI / uv | 單一 process，執行緒 worker |
| CV | OpenCV（純 cv2+numpy，無 scikit-image 等額外依賴） | 免訓練、CPU-only |
| 前端 | Vite + React + TypeScript（strict） | SVG overlay、i18n zh-TW/en |
| 影像傳輸 | MJPEG（影像）+ WS JSON（座標/事件）分流 | overlay 前端繪製，不烙進影像 |
| 地端 VLM | **Ollama + qwen3-vl:8b/:4b**（OpenAI 相容 API） | 後期選項：llama-server 出貨打包、Snapdragon NPU 走 GenieX |
| 雲端 LLM（後期） | Anthropic structured output 首選（三家 API 皆相容的扁平 schema） | prompt caching 省 30–50%；本波不建 |
| 板卡資料 | board.json（JSON Schema 驗證）+ ComponentSpec DSL | 新板卡 = 新資料夾零程式修改 |

---

## 引用文件

| 文件 | 內容 |
|---|---|
| [api-contract.md](api-contract.md) | REST/WS 完整契約 |
| [wire-recognition-design.md](wire-recognition-design.md) | 杜邦線辨識調研+設計（M15–M19） |
| [wiring-verification-architecture.md](wiring-verification-architecture.md) | 能力②電氣驗證架構 |
| [color-agnostic-wire-and-guidance-design.md](color-agnostic-wire-and-guidance-design.md) | 顏色無關偵測 + 導引打勾（M20–M24） |
| [cloud-plan-and-edge-vlm-architecture.md](cloud-plan-and-edge-vlm-architecture.md) | 能力③雲端+VLM 完整設計（M25–M30）+ 兩份研究附錄 |
