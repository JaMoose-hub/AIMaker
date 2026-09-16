# BoardVision AI 作品工作台

## 使用方式

沿用既有啟動方式，開啟 http://127.0.0.1:8100 ，控制器選 Raspberry Pi 5。

頂部將「設計作品／Blueprint／Pin 接線引導／部署與測試」與控制器、Pose 狀態、語言整合在同一工具列，窄視窗在同一區塊內換行；不顯示「全部／PWM／I²C／SPI／UART／類比 ADC／電源／中斷」篩選按鈕。點選 Pin 查看能力、文字查詢與接線引導維持原有行為。

1. 「設計作品」為獨立頁：左側持續雲端對話，右側產生真正的 AI 點陣作品組裝圖片，不混入接線圖或材料表。輸入需求，選「設計／修改作品」後送出。電子模組仍限 Pi 5、HC-SR04、HW-123、MRD-TF240，每種最多一個。允許輪子、輪軸、銅柱、壓克力板、支架與螺絲等被動結構配件，不增加馬達、驅動或電池。車型作品是組裝示意，不代表可自行行駛。
2. AI 使用本機 Codex App Server 與 Codex 管理的 ChatGPT 登入。已有登入可直接使用；否則按「登入 ChatGPT」並開啟回傳的官方登入網址。
3. 按「確認作品 → Blueprint」才套用設計並進入獨立 Blueprint 頁；新作品未確認時 Blueprint 導覽停用。此頁不放對話框：左側為可縮放、可點選的 SVG 零件／接線圖，右側為「材料與導購／製作步驟」分頁，左右寬度仍可拖曳。點選「逐線接法」會同步高亮圖中同一條線路，點圖也會選取側欄步驟；只供查看，不建立人工接線確認。AI 製作說明保留原文，不猜測它與單條線路的對應。材料價格與本機商品頁都是示範，沒有賣家或付款。若已有手動程式草稿，替換前另行確認；取消不套用。
4. Blueprint 的「開始 Pin 接線引導 →」開啟原有鏡頭＋Pin UI。按模組完成準備與逐線人工確認；完成後自行選擇下一模組。收合卡片不會取消目標。
   作品接線引導預設為畫面中下方的兩行字幕：接線兩端、短狀態與上／下一步。按「接線準備／詳細」向上展開安全確認、說明及進度；步驟變更後自動收起詳細內容。斷電／分壓準備與有效定位仍為確認條件；ECHO 分壓與未確認模組禁止上電的短提示不會藏起。
   精簡介面已在隔離的合成定位頁確認：準備條件、GND→TRIG→ECHO、上一步、定位 stale／恢復、展開與收合都保留原狀態；收合卡片不清除高亮。這些是 UI 測試，不是實體接線或電氣驗證。
5. 接線卡已移除「2D 人工引導」切換入口，保留鏡頭 Pin 引導。沒有相機或定位不足時需等待有效定位才能確認接線；右側 2D 接線總覽仍可查看，不取代定位或接線確認。
6. 「部署與測試」可編輯單一 main.py，按「連線 Pi」「部署並執行」。不要求先完成視覺辨識或人工確認；硬體規格不明則阻擋作品部署。
7. 人工硬體測試結果獨立記錄，不能以服務正在執行或接線已勾選代替。

設計與部署階段保留同一個雲端 AI 對話入口；Blueprint 透過「返回設計修改」回到原對話。作品接線引導移除右側對話區、讓鏡頭使用全寬，仍保留頂部模型選擇與「AI 檢查本步」。需要對話時切回「設計作品」；作品、對話、程式草稿及人工接線進度均保留，背景 AI 工作不受側欄移除影響。原有獨立接線／部署與其他控制板的資訊側欄不變。
「詢問 AI」只回覆文字，不生成或套用作品；「設計／修改作品」產生待確認預覽。
例如：「保留這些零件，改成 10 公分才警告」或「為什麼這一步 ECHO 需要分壓？」。
在 Blueprint／接線／部署階段收到新版時顯示「有新版作品待確認」，不跳頁、不覆寫草稿；Blueprint 移除對話框不會中斷背景 AI 工作。
生成方式提供「自由版 · 重新設計造型」（預設）與「固定版 · 保留造型微調」，跨頁與重新整理皆保存選擇。
自由版僅沿用功能參數與限定零件，不把舊造型、舊圖片、對話或程式草稿送入設計提示；請在需求中描述新外形，例如「改成小恐龍」。
固定版的修改追問參照最新預覽（沒有預覽時參照已確認作品），保留未修改的外形與配置；第一次使用沒有基底圖片時會建立初版。
兩種模式都先產生未確認的新版本，不覆蓋已確認的作品、接線與手動程式。模式切換不清除對話或預覽；「詢問 AI」仍保有完整作品對話脈絡，不受生成方式限制。
在接線／部署詢問問題時，參照目前已採用的作品。
相同接線的新版保留步驟與確認，變更接線時移除受影響的確認。

作品圖片使用 Codex 原生 image generation，由 App Server `imageGeneration` 完成事件取得 PNG，
不接受文字訊息宣稱的圖片路徑，也不用固定 SVG／示範圖冒充成功。只有固定版將前版圖片
以 `localImage` 傳入，要求保留未修改的構圖和模組；自由版不帶參考圖片。文字與圖片使用同一模式，
並保存於工作和作品的 `generation.design_mode`；僅重試圖片時沿用原工作模式，不因目前 UI 選項而改變。
圖片只表達組裝外觀，比例／細節可能
失真；不作尺寸、接線、硬體可用性或電氣驗證的依據。HW-123 的 prompt 明確排除 PIR 圓罩。
`assembly.parts` 使用被動配件 enum、數量限制，Blueprint 將其與原有電子 BOM 分開。
舊作品／預覽不會自动生圖扣額度；左側重新送出後生成。舊的已採用 Blueprint 可繼續查看，
新 AI 預覽有圖片後才能確認。生成失敗保留文字方案，提供「只重試生圖」，不重跑文字模型。

瀏覽器使用 `boardvision.maker.v1` 保存作品、預覽、對話、草稿、AI job ID 與人工接線紀錄，圖片只存 URL 與 ID，不塞入 base64。PNG 與生圖 metadata／工作結果存於 `runs/project-images`，每版有獨立 ID、不覆寫前圖。切換四階段不打斷生成；重新整理後可接續輪詢同一工作。已完成圖片工作在後端重啟後仍可讀取；執行中斷的工作明確報錯，不自動重送扣額度。重新整理後要重做接線準備；舊確認標示為歷史人工紀錄，不是現況證據。測試結果重新整理後回到未測試。

## 本機 Codex 接入

後端直接使用官方 JSONL stdio `codex app-server` 協定，不需要 OpenClaw、Hermes、第三方 OAuth 轉接或額外 Python AI SDK。前端不持有 OAuth token，Pi 設定和密碼不會放入 AI prompt。

Codex 必須可從後端程序的 PATH 找到。必要時在啟動後端前設定：

```powershell
$env:BOARDVISION_CODEX_BIN = 'C:\absolute\path\codex.exe'
# 選填；未設定時沿用 Codex 預設模型
$env:BOARDVISION_CODEX_MODEL = 'your-available-codex-model'
```

生成工作串行、背景執行，不阻塞相機事件迴圈；文字回合 180 秒、圖片回合 360 秒逾時後中止。圖片使用獨立 read-only ephemeral 回合，停用 shell、apps、plugins、多代理與 web search，只請求原生生圖。未登入、額度不足、程序中斷、格式錯誤不會偷偷改用示範結果或 API Key 計費。

### 模型、推理強度與送出前費用預估

- 設計頁可選擇本機 Codex `model/list` 回傳的模型及該模型支援的推理強度，選擇保存在瀏覽器。未指定模型時使用 `BOARDVISION_CODEX_MODEL` 或目錄預設；初始推理強度保留 `low`。已失效的選擇必須重新選，不會靜默換模型。
- 本工作台不提供會自動委派其他 AI 的 `ultra`。設計使用文字回合＋原生圖片回合，詢問只使用文字；保存 model/effort，不改 Codex 全域設定或 Pi 上已部署的程式。
- 原生生圖使用 Codex 額度。現有 USD／credits 預估僅包含文字設計，**不包含圖片生成／修改及其額外模型用量**，UI 與 API 都明確標示，無法預估的圖片費用為 null，不當成免費。[官方圖片說明](https://learn.chatgpt.com/docs/image-generation)
- `GET /api/ai/models` 讀取模型清單（後端快取 5 分鐘）；`POST /api/ai/estimate` 與 `/api/design/generate` 使用相同需求結構，新增 `model`、`effort`、選填 `expected_output_tokens`。估算不建立生成工作、不呼叫模型推論，也不讀取 Pi。
- 估算與生成共用 `build_design_prompt`，包含需求、允許的作品欄位、零件摘要及 JSON 輸出 schema；不將 SSH 帳密／後端設定傳給 AI。
- 價目表 `backend/app/ai_pricing.json` 為 2026-09-07 官方 Standard 短上下文單價快照，含來源連結。未知模型、超過 30 天的單價或長上下文顯示「無法估算」，不當成零元。更新時必須重新核對官方來源和日期。
- 顯示美元 **API 等值參考** 與標準速率 credits 參考；目前是 ChatGPT 登入，不能將 API 等值成本當成本次訂閱扣款，實際金額欄位固定為未知。credits 的實際適用費率、內含額度、購買價格與折扣以帳戶／合約為準。不購買額度、不切換 API Key。
- Token 預估以完整已知 payload 的 UTF-8 bytes ÷ 4～2，加上 1,000～6,000 系統 token 假設；不是精確 tokenizer。依推理強度使用明示的輸出＋推理情境值，或使用者自行輸入 256～128,000 tokens；區間為情境值 0.5～1.5 倍（最高 128,000）。不是保證區間或花費上限，實際可超出。
- 公式為 `(輸入 tokens × 每百萬輸入單價 + 輸出 tokens × 每百萬輸出單價) / 1,000,000`。不假設快取折扣，不含工具、稅、重試；工作明確選 Standard（`serviceTier: default`），不沿用 Fast 加價。估算值不送入 AI prompt、不作為 max output 限制。

AI 產生作品構想、參數、說明與 `on_sample(readings, settings)` 純決策／文字函式。系統使用經驗證的目錄接線與 GPIO runtime 包裝函式。第一版不接受 AI 自行安裝驅動、任意依賴或另寫 GPIO 初始化；編輯區仍可由使用者自由修改。

## 資料與硬體邊界

- `profiles/component-catalog.json` 是既有三種模組教學的共用來源。原有固定引導、作品引導、SVG、材料表和程式腳位都由此整理，不另外維護 AI 腳位表。
- 板卡／模組 Pin 能力與電壓仍讀取原有 `board.json`、`component.json`。沿用相容性檢查，另檢查跨模組 GPIO 衝突、SPI 角色與 ECHO 分壓。設計包含 Profile 版本與 SHA-256；部署時可偵測已更新的 Profile。修改目錄後需提升目錄版本並重建前端。
- HC-SR04：GND Pin 6、TRIG GPIO17/Pin 11、ECHO 經 330Ω／470Ω 分壓到 GPIO18/Pin 12、VCC 5V/Pin 2。分壓不是單顆串聯电阻；接線保持斷電。
- HW-123：實際晶片及驅動待核對。TFT：供電、背光、驅動待核對。可以設計預覽及引導已知訊號，但包含這些模組的作品程式只會報明確 pending 錯誤，不初始化 GPIO，部署按鈕及後端均阻擋。
- 可先使用 HC-SR04 子作品，其 GPIOZero/lgpio 程式讀取真實距離，不使用假讀值。缺回波、超過一秒未更新、超量程時輸出 UNAVAILABLE，不重複使用過期的平均值。實體功能驗收仍需正確接線與實測。
- Pi 保持 `/home/pet/Desktop/Pi_deployer`、系統套件 venv、單一 `main.py`、`boardvision-pi.service`。語法／GPIO 套件檢查在停止舊程式前；缺套件時顯示準備步驟，不自動安裝。
- I²C/SPI 準備裝置需求顯示在部署頁；目前相關模組因規格未確認而不能進入上電執行。確認規格後仍需在目錄實作對應 runtime／裝置 preflight，不能只將 supported 改成 true。
- SSH 斷線不會停止服務；服務不設開機自啟。部署成功、程式狀態、人工接線和硬體測試分開呈現。

## API

| Endpoint | 用途 |
| --- | --- |
| GET `/api/ai/status` | App Server 與 ChatGPT 登入狀態 |
| POST `/api/ai/login` | 啟動登入，回傳 auth_url |
| GET `/api/ai/models` | 可用模型、支援推理強度與預設模型；refresh=true 強制重讀 |
| POST `/api/ai/estimate` | 與生成相同輸入，僅本機估算 token／USD 等值／credits，不呼叫模型生成 |
| POST `/api/design/generate` | prompt、component_ids、current、locale、model、effort、expected_output_tokens；intent=design/ask、design_mode=free/fixed（預設 free）、generate_image（設計 UI 固定 true、舊 API 預設 false）、conversation（最多 20 則）、workflow（stage、active_wire、manual_confirmations、code_draft）；回傳 job_id |
| GET `/api/design/jobs/{id}` | generating / completed / failed；設計回傳 design，詢問回傳 answer 且 design=null；失敗回傳 error |
| GET `/api/design/images/{id}` | 讀取本機已保存 PNG；UUID 路徑，不提供任意檔案讀取 |
| POST `/api/design/jobs/{id}/retry-image` | 只重試生圖失敗的方案；同模型／強度，不重跑文字設計 |
| GET `/api/design/catalog` | 共用零件目錄 |
| GET `/api/design/demo?sensor_only=true` | 明確標示的內建示範 |
| POST `/api/pi/connect` | 連接固定 Pi |
| POST `/api/pi/deploy` | code，以及選填的作品 component_ids、catalog_version、profile_versions |
| GET `/api/pi/status` | 部署狀態、程序 PID／退出碼與最近輸出 |

## 驗證

2026-09-08 Blueprint 側欄改版：43 項前端測試、587 個語系鍵檢查與 TypeScript/Vite 建置通過。
瀏覽器確認 Blueprint 沒有對話框，左圖右側欄、材料／步驟分頁、鍵盤操作、示範商品開關、
TRIG／ECHO 分壓與跨模組同名腳位選取、圖與側欄雙向高亮、寬度調整均正常。
900px 保持左右欄，390px 堆疊且無橫向溢出；返回設計保留對話、需求及未確認預覽，
接線入口仍進原有 Pin 引導且未建立人工確認。本次沒有 AI 生成、部署或實體接線操作。

2026-09-08 固定版／自由版：698 項後端測試、40 項前端測試、587 個語系鍵檢查及建置通過。
測試涵蓋兩種文字提示、參考圖分流、模式保存、舊資料遷移、圖片失敗後重啟／重試、
詢問模式保留脈絡、零件限制、已確認版本與手動草稿不被覆蓋。
正式瀏覽器已驗證模式選擇、重新整理保存與詢問切換；原作品、對話及小恐龍需求保留。
此輪使用替身驗證生成接口，沒有新增雲端生圖、沒有操作 Pi；實際新造型生圖效果待使用者送出確認。

2026-09-08 真實生圖改版：689 項後端測試、34 項前端測試、語系與建置通過。
以真實雲端模型驗證車型組裝圖片、保留構圖改色、IMU 外觀修正、跨頁／重整／
後端重啟保存、確認後 Blueprint 結構配件與原有 Pin 引導；未操作實體 GPIO。
生圖提示、圖片與完整紀錄見 `runs/diagnostics/maker-images-20260908/RESULTS.md`。

2026-09-08 四階段改版：671 項後端測試、33 項前端測試、語系檢查與建置通過。
隔離頁以真實 GPT-5.6-Luna 驗證概念生成、確認後進 Blueprint、跨頁提問、
生成中重新整理、修改預覽以及取消／確認取代手動草稿；相機為合成測試，
Pi 寫入接口在該測試頁停用。正式使用者的既有作品與未確認預覽均保留。
詳見 `runs/diagnostics/maker-blueprint-20260908/RESULTS.md`。

```powershell
cd backend
.venv\Scripts\python.exe -m pytest -q
cd ..\frontend
npm test
```

合成定位頁（不等於硬體測試）：從 backend 執行 `.venv\Scripts\python.exe -m tests.wiring_guide_preview`，開啟 http://127.0.0.1:18761 。測試專用 POST `/__test/scenario/{locked|stale|missing|silent}` 不存在於正式後端。

選用實機驗收工具：正式後端啟動後，從 backend 執行 `.venv\Scripts\python.exe -m tools.verify_maker_pi`。**會暫停／替換目前 Pi 程式**，先備份 main.py／run.log，再以無 GPIO 的程式測試重部署、單實例、語法錯誤及執行例外；最後還原原程式。此工具不在一般 pytest 自動執行。

2026-09-07 驗收紀錄：

- 後端全套 552 項測試通過；前端 12 項測試、581 個既有語系鍵檢查及 TypeScript/Vite 正式建置通過。
- 本機 ChatGPT 真實登入狀態及真實 AI 生成成功；四零件設計追問移除 HW-123/TFT、20→10 公分成功。
- 瀏覽器：採用作品直接進入原 Pin UI；HC-SR04 TRIG 同步 GPIO17/Pin 11；定位 stale 禁止確認並移除精準標記；2D 明確切換、ECHO 分壓、收合／展開、模組完成後手動切換、草稿／预览刷新保存、示範商品頁與放大圖已檢查。
- 實際 Pi：部署 A PID 9519 → B PID 9561，程序數 1；語法錯誤維持 B；RuntimeError 使程式失敗但部署結果仍為成功。原光敏程式已還原，持續讀取 `GPIO17: 0 (LOW)`。
- 正式瀏覽器頁面已實際按連線與部署，收到 Pi 輸出 `BOARDVISION_BROWSER_DEPLOY_OK`；語法錯誤顯示 Python SyntaxError；執行例外顯示 `BOARDVISION_UI_EXPECTED_ERROR` 與退出碼 1，部署完成和程式失敗分開呈現。這些測試程式不操作 GPIO；最後再次還原原光敏程式。
- 原檔備份：Pi 桌面 `Pi_deployer/main.before-maker-20260907-112205.py` 及對應 `run.before-maker-20260907-112205.log`。
- **未完成實體驗收**：HC-SR04 遠近測試、HW-123 實際晶片與傾斜測試、TFT 規格與顯示。UI 合成確認不是實體接線證據；沒有以假距離／姿態值冒充成功。

### 2026-09-07 模型與費用功能補充驗收

- 後端全套 568 項測試通過，包含模型／推理強度傳遞、Standard tier、拒絕模型替換、費用公式、未知／過期價目、無付費生成的估算、模型分頁快取及錯誤。
- 前端 22 項測試、581 個語系鍵檢查及 TypeScript/Vite 建置通過；舊草稿可遷移，模型／推理強度／自訂 token 假設保存在瀏覽器。
- 真實 App Server 回傳 7 個模型；以 `gpt-5.6-luna`／`low` 完成 HC-SR04 設計工作 `f83cb0b4-4a38-4c62-b667-c96612e10dfc`。這是一次真實生成，不是估算呼叫；沒有取得帳戶實際扣款資料。
- 瀏覽器實測模型切換、high 估價增加、自訂 2,000 tokens、重新整理保存、Spark 無單價提示；切換時舊估價消失並暫停送出，直到新估算完成。測試後還原 Codex 預設／low／自動 token 假設。
- 本次未採用測試生成作品、未覆蓋手動程式，未操作 Pi 部署或硬體。
