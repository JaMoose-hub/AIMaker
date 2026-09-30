# 02 接線引導中的測試與除錯

2026-09-21 實作；2026-09-27 統一雲端看圖除錯入口。支援 Raspberry Pi 5、HC-SR04+、MRD-TFT240；照片觀察提供除錯引導，不能認證接線正確或電氣安全。

## 使用流程

01 設計與藍圖（作品概念／製作藍圖）→ **02 接線引導＋AI 除錯** → 03 部署與執行。

2026-09-29 整合：測試與除錯收進 02，同頁共用對話、設計圖快照及照片來源。按需看圖不要求 Pi 上電，也不授權硬體工作。逐腳引導、相機與 2D 操作保留；原唯讀診斷、零件測試、修復與試跑可由同頁手動工具開啟。完整規格、功能保留基準及各輪驗證見 [接線與 AI 圖解整合](wiring-ai-integration.md)。

1. 02 每個零件接完仍可做原有小測試；異常時從結果開啟同頁除錯，帶入零件、測試編號與現象。
2. 在 02 展開 AI 對話，先用文字詢問目前接線，需要新畫面時按「拍攝這一步」。準備好測試時明確開始 AI 除錯，系統才讀取 Pi／程式／測試紀錄與新照片，交給上方選擇的 Codex 雲端模型分析並安排受限測試。
3. 在同一對話框查看各輪文字、送出的照片、模型觀察、判斷原因與一個下一步。直接輸入回覆並送出；Enter 送出、Shift+Enter 換行，中文輸入法選字時不送出。文字追問沿用已有觀察與目前 Pi 狀態，需要新視角時再拍目前畫面，需要確認接腳時查看同頁接線引導。對話區獨立捲動，按下檢查不自動捲動整個頁面。
4. 雲端建議的固定測試在核對接線及環境後執行。需要自行操作時展開「手動測試與程式工具」，結果和重測按鈕在同一張零件卡片。亦可在同頁查看指定接腳；單純查看不清除接線確認／結果，按「我要修改此零件接線」才使該零件結果失效。
5. 程式邏輯問題可按「請 Agent 分析」，查看候選差異與離線執行測試，確認後才套用草稿並排入試跑。
6. 60 秒試跑需觀察新距離與實體畫面是否同步，程式退出或 SPI 寫入成功不是實體通過。
7. 可隨時前往 03 啟動作品。未測試／未通過不會因此變成通過。03 的「診斷目前程式」保存當下執行編號、版本、退出碼及最近日誌，帶回 02 除錯，與後續讀取的服務狀態分開。

手動工具中的「檢查 Pi 與程式紀錄」只查 Pi 連線、指定環境、服務／佇列、草稿語法、實際版本與零件結果，不呼叫雲端。無作品時仍可使用此檢查；雲端工作階段、零件測試、Agent 修復與整合試跑需先有作品。既有 `deploy` 儲存識別值不變；舊草稿的 `debug` 識別值相容還原至 02，保留原問題與確認紀錄。

## AI 協作除錯（第一版）

### 對話與回覆速度

預設「快速引導」沿用上方所選模型，以該模型支援的較低推理強度回覆；每輪送出前可改選「深入分析」，沿用建立案件時選定的推理強度。此設定限於本次除錯，不修改全域模型設定。等待時顯示實際經過秒數，完成後保留模型回覆耗時；沒有把進度訊息當成模型逐字串流。

每輪訊息由後端保留，重新整理及多分頁查詢可取得同一份對話。文字回覆不重新拍照或重跑完整 SSH 環境檢查，提供有時間標記的歷史觀察與目前 Pi 狀態供模型回答；只有明確要求新畫面時才拍照。文字模型回覆不能根據舊照片直接啟動硬體工作。每案六次模型呼叫上限仍適用於文字與看圖的合計。

停止後重新開始時，以新案件的綁定為準。相機變更會透過共用 WebSocket 更新前端設定；若新案件已使用較新的相機版本且後端確認仍有效，前端尚未同步的舊版本不會將它誤判過期。真正更換相機、修改接線或程式時仍會失效。程式雜湊須對應目前文字，接線鍵以內容比對，舊輪詢回覆不能覆蓋新案件。

取景框已放大：全景涵蓋影像寬度 92%，零件及接頭約 80–84%；使用同一套鏡像與影像縮放座標。框是取景提示，保存的原始證據不含框線。

02 的 AI 對話在明確開始除錯後建立或升級 AI 協作除錯工作階段。模型收到新的 Webcam 照片與經遮蔽、限制長度的 Pi 狀態、程式、版本及測試摘要，回傳觀察、原因、具體操作引導及受限動作。一般看圖傳送長邊最多 1920 px 的等比例縮圖，原始證據保留，紀錄原圖與送入影像的雜湊及大小；TFT 測試階段讀碼仍使用原始照片。畫面顯示實際回覆與證據，不把模型建議換成固定的「重測」文案。缺少接線確認時可先看圖；伺服器在提交硬體工作前核對確認與環境條件，阻擋原因留在目前引導中。

01 的作品目的、所選零件的電氣規格、參數與藍圖預期接線，以及 02 的逐腳確認與既有測試都沿用於同頁除錯；同一案件也保留最初問題和後續回覆。HC-SR04+ 使用作品 catalog 指定的 `variants/plus-3v3.json`，不是同一識別碼下保留的標準 5V profile。已選規格作為作品既知條件，不能只因照片絲印是 HC-SR04、照片看不到型號或紀錄未測試，就反覆要求確認規格。只有實際矛盾或使用者更換零件時，才提出明確的差異問題。實物接線是否完成仍由各步驟的有效確認與測試證據判斷。

下一步優先針對使用者正在查的零件。例如 HC 畫面與先前接線確認不一致，先詢問目前是否拔除接線；TFT 未確認可作為硬體執行限制，不能取代 HC 的唯讀追查。相同人工拍攝指示再次出現時改為文字追問，避免繼續拍相同畫面。停止或過期案件不再把舊的取景指示疊到目前鏡頭。

這是對即時視訊取出新照片後的逐輪雲端分析，沒有把整段視訊持續串流給模型。使用者在 HC 近段、遠段各按一次「準備好了」；補拍時依指示調整鏡頭，再請 AI 看新的照片，也可手動拍照。工作階段內已允許的固定測試會連續進行。停止現有作品仍走執行交接確認。

畫面分別標示「AI 看見畫面」、「零件測試結果」、「整體試跑結果」；影像觀察不能代替 Pi 新讀值。HC 遠段中位數須比近段增加至少 5 cm，兩段各有至少 5 個新有效回波。TFT 相機協作測試保留各 RGB 階段與當次測試碼的獨立取證；AI 只能說明照片實際可讀的顏色或文字，後端核對當次碼與測試階段。最後的 TFT 實體通過仍由使用者選碼與確認顏色，AI 不代填。

完成零件測試後可安排 60 秒整體試跑；程式與 Pi 資料可自動核對，實體螢幕和距離是否同步仍由使用者確認。程式修復沿用既有差異預覽、離線測試、明確套用與還原。第一版只使用 Webcam 與共用的 `VideoView`；Eye 除錯取景留待後續。工作階段支援重新整理接回、重複操作去重、單 Pi 單活躍案例。後端重啟後，舊案只有摘要可查，必須核對／停止舊工作並建立新案，不重播工作。模型最多呼叫 6 次、每零件最多測試 2 次，照片快取最多 24 張／64 MiB；超限時說明原因並保留手動工具。

設計依據與實體驗收方法見 [AI 實體協作除錯設計](ai-physical-debug-design.md)。軟體模擬通過不代表已在 Pi、相機及 TFT 上完成現場驗收。

## 執行隔離與恢復

- 02 零件小測試與整體試跑、03 正式部署共用 `PiExecution` FIFO、SSH 連線與遠端 `component-tests/hardware.lock`。
- 若硬體正在被使用，先顯示交接確認；確認的服務身分若改變，必須重新確認。查明前一份程式已停止後才啟動下一份。不終止非 Board Vision 程式。
- 試跑使用不可變草稿快照，寫入 `Pi_deployer/trials/<run-id>/`，獨立 `boardvision-test-trial-<run-id>.service`。
- runner 在 60 秒發出結束訊號，systemd `RuntimeMaxSec=65` 是第二道遠端期限；關閉瀏覽器／SSH 不會取消期限。停止只針對本次服務，`KillMode=control-group`。
- 不改正式 `main.py`、正式服務或 `run.log`。正式部署另有 `deployments/<run-id>/`、`deployment.json`，以執行編號、程式雜湊、systemd InvocationID 核對真實版本。
- 狀態未知／斷線時保留控制與硬體預留，不再次啟動。重新整理只查詢；後端重啟核對遠端服務，不重播排隊工作或 Agent 請求。
- 測試／交接停止的原作品不自動重啟。還原僅還原草稿，不停止或啟動 Pi。

## 證據與通過規則

02 的接線引導、AI 操作卡與手動工具共用 `useComponentTests`、`ComponentTestCard` 與同一個後端 `ComponentTests`。近遠測距、TFT RGB／本次測試碼的既有判定不變。

生成作品的固定硬體框架可加入結構化觀測：執行編號、程式雜湊、心跳、不同時間的新樣本序號、最後有效資料時間、顯示送出次數、退出碼與讀取執行緒例外。

### 部署與試跑的觀測修正（2026-09-30）

03 正式部署與 02 整合試跑共用 `observed_source` 和 `project_runner`。觀測函式統一使用 `_bv_emit`；避免雙底線名稱在 `FreshDistanceSensor` 類別內被 Python 改寫，導致背景讀取執行緒發生 `NameError`。原作品草稿、GPIO 設定及邏輯不變。背景讀取失敗時，日誌列出原始例外，不再只顯示主執行緒當時被中斷的螢幕寫入位置。

已從失敗部署的 `runtime.json` 核對這次原因是 `_FreshDistanceSensor__bv_emit` 未定義；單看主執行緒的 `KeyboardInterrupt` 不能判定螢幕未接或 SPI 故障。`PWMSoftwareFallback` 警告及沒有新回波仍分開處理。

後續部署另確認新舊版本混用：舊後端記憶體仍產生 `__bv_emit`，卻從磁碟上傳新版 runner。runner 對 `structured=true` 的既有快照相容 `__bv_emit` 及 `_FreshDistanceSensor__bv_emit`，指向同一個有效新讀值檢查；不改寫來源及其雜湊，也不對自訂程式增加舊版入口。`build_runtime_bundle` 在觀測器模組載入時固定 runner，正式部署與整合試跑一律取得同一套來源／觀測標記／runner，避免之後只讀取部分新檔案。共用套件固定機制在後端下次重啟後載入；目前舊後端可透過相容 runner 完成部署。

相關自動化測試共 66 項通過（`test_project_runner.py`、`test_runtime_instrumentation.py`、`test_runtime_bundle.py`、`test_debugging.py`、`test_pi_deploy.py`），包含實際執行新舊類別內的紀錄呼叫、首次讀取、無回波、顯示寫入失敗不得增加成功紀錄、原始背景錯誤輸出，以及載入後磁碟換版不造成套件混用。Pi 上已保存的舊部署不會自動改寫，須透過 03 的部署流程建立新版本。

本次已經由既有 `/api/pi/deploy` 與 `PiExecution` 將同一份作品重新部署，執行編號 `a1630aa110604a1fa4fcf63aa4cef89d`。原作品雜湊保持不變，核對同一 systemd InvocationID：觀察間隔 83.14 秒，新有效距離增加 1,280 筆、畫面送出增加 314 次；程式在啟動後 99.22 秒仍為 running，沒有例外，最後距離為 30.3 cm。這證明本次完整部署的程式與讀取／送出持續運作；尚未核對實體 TFT 畫面、距離精度或移動同步，不據此記錄零件／整合實體通過。原始與修正證據保存在本機 `runs/diagnostics/deploy-reader-20260930/mixed-version/`。

### 整合驗收

整合結果須同時滿足：

- 本次程式正常結束，有可核對的結構化資料。
- 若含 HC：至少 5 筆新樣本、距離變化至少 5 cm，結束前 5 秒內仍有有效距離。
- 若含 TFT：確實送過畫面；含 HC 時結束前 5 秒內仍有畫面送出。
- 使用者確認本次實體反應／畫面同步。

這些是基本整合反應的驗收，不是絕對距離精度、接線正確性或電壓驗證。試跑不是 TFT 小測試的替代品。
舊／手寫硬體程式仍能試跑與看日誌，但無法識別的框架不插入感測器觀測，也不會自動判定整合通過。
沒有回波只代表沒有有效資料；讀取例外、依賴、權限、連線及無回波分開處理，不能猜某條線接錯。

## Agent 修復範圍

- 沿用模型選單及 Codex bridge，另建除錯請求，不變更設計對話或作品候選。
- 點擊後才傳送經遮蔽的必要程式與證據；關閉工具能力，沒有 SSH 或任意命令工具。
- 以 AST 比對完整硬體框架，只有當前系統生成版本可修復 `on_sample(readings, settings)`。固定驅動、GPIO、供電、設定參數均不得修改。
- 手寫／已變更硬體框架只提供診斷，不重建或覆蓋草稿。
- 沿用邏輯驗證器，加上輸入不可修改、大小／昂貴運算限制；隔離 Python 程序以 3 秒期限執行 7 組測例。離線測試只證明可執行與輸出形式，不宣稱使用者預期邏輯或硬體已正確。
- 每個案例最多兩輪有效候選，每輪需確認。草稿、Pi、接線、手動接線確認版本或模板改變，舊候選拒絕套用。
- 每次套用保存前一版草稿；還原亦核對目前草稿，避免覆蓋使用者後續編輯。
- AI 未登入／忙碌／失敗不妨礙固定診斷、接線與小測試。

## API 與資料

| API | 用途 |
|---|---|
| `POST /api/debug/cases` | 建立／更新唯讀診斷，立即取得案例編號 |
| `GET /api/debug/cases/{id}` | 查詢進度、問題與候選 |
| `POST /api/debug/cases/{id}/actions` | `analyse`、明確確認的 `apply`／`restore` |
| `POST /api/debug/trials` | 草稿快照加入共用 FIFO，回傳工作編號 |
| `GET /api/debug/trials` | 活躍控制與歷史結果，可按作品篩選 |
| `POST /api/debug/trials/{id}/actions` | `stop`／綁定本次的 `visual` |
| `POST /api/debug/sessions` | 建立或接回 AI 協作除錯工作階段 |
| `GET /api/debug/sessions/{id}` | 查詢指示、進度、工作與證據摘要 |
| `POST /api/debug/sessions/{id}/actions` | 本次工作階段的補充、準備、拍照、繼續及停止 |
| `GET /api/debug/sessions/{id}/evidence/{capture_id}` | 取得本次仍有效的照片 |
| `GET /api/debug/sessions/{id}/evidence/{capture_id}?view={name}` | 取得同一取證的原圖／局部圖，回傳實際 JPEG 或 PNG 類型 |
| `GET /api/debug/conversations?project_id={id}` | 02 接線問答與功能除錯共用的作品對話歷史 |
| `POST /api/debug/conversations/restart` | 重新開始接線時建立空白協作對話；需先停止本案檢查並核對硬體工作 |
| `GET /api/debug/conversations/{id}` | 取得指定對話與照片、圖解索引 |
| `POST /api/debug/conversations/{id}/diagrams` | 保存經核對的設計圖快照 |
| `GET /api/debug/conversations/{id}/diagrams/{snapshot_id}` | 讀取歷史版本接線圖 |

交接仍用既有 `/api/pi/execution` 相關 API；沒有新增另一套零件測試 API。
診斷與試跑儲存在本機 `backend/runs/debug-cases.json`、`backend/runs/integration-trials.json`，由既有 `.gitignore` 排除。
跨頁對話、圖解快照保存於 `debug-sessions-conversations.json`；一次檢查仍由 `DebugSession` 管理版本、工作與額度。`purpose=wiring_review` 只看圖／對話，`start_debug` 才開放固定硬體動作；切頁與正常逐腳進度不重開檢查或重置額度。新增 `prepare_wiring` 只處理本案工作，不能代停其他工作。

「重新開始」接線會先停止本作品的 AI 檢查、核對 Pi 工作與測試保留狀態，再失效舊接線測試綁定，建立新協作對話並回到第一步。右側 AI 訊息、照片／圖解引用、輸入草稿與本輪檢查入口同步清空；重新整理或重啟後端也不會重載舊對話。作品、程式、設計頁對話、其他作品，以及既有測試／執行紀錄保留。舊協作對話以 `archived` 保存供歷史追溯，不再用於新一輪 AI 上下文；延遲回覆與舊頁面的明確對話 ID 不能將它重新啟用。單獨修改一個零件的接線仍保留協作對話。

重設 API 使用 `project_id`、`request_id` 與可選的 `expected_conversation_id`；重試同一要求不會重複建立新對話。停止、狀態核對、失效或重設失敗時，不提交新的接線進度。前端回歸測試：`tools/wiring_restart.test.mjs`、`tools/debug_session_binding.test.mjs`；後端：`tests/test_wiring_conversation_restart.py`；隔離 UI：`node tools/wiring-restart.qa.mjs`（模擬 API／資料，不操作正式紀錄或硬體）。
綁定 Pi 目標、作品、接線簽章、Profile、手動接線確認、程式雜湊與模板版本。只改作品邏輯不使固定零件測試失效。
複製摘要／API 公開結果／Agent 輸入均遮蔽已知 Pi 密碼、常見權杖與私鑰；本機完整草稿仍須視為私人檔案，不加入 Git。

## 歷史驗證紀錄（獨立除錯頁版本）

以下保留早期五階段版的測試數字及頁面編號；其中 04 為當時的測試與除錯、05 為部署。這些紀錄不代表已驗收目前三頁導覽；本次整合的驗證另列於 [接線與 AI 圖解整合](wiring-ai-integration.md#本次驗證紀錄)。

### 自動化與模擬（非實體驗收）

- [x] 後端相關回歸 185 項通過（包含原有部署、零件測試、FIFO、驅動、Maker、AI 選項）。
- [x] 前端 165 項測試與 TypeScript／正式建置通過，涵蓋五階段、舊資料還原、查看接線不修改確認、唯讀輪詢與固定狀態區。
- [x] 套用確認、兩輪上限、過期草稿／接線／目標／測試結果拒絕、草稿還原。
- [x] 試跑獨立目錄／服務、遠端期限設定、共用鎖、重複點擊、交接、斷線保留與重啟不重播。
- [x] 舊部署 InvocationID／hash／run-id 不能成為本次版本證據；程式成功退出不等於實體通過。
- [x] 診斷公開結果、API 錯誤、Agent 輸入的敏感資料遮蔽。
- [x] 隔離瀏覽器驗證五階段、ECHO 指定腳位跳轉、11/11 接線紀錄保留、候選差異／確認、FIFO 交接、模擬試跑等待目視、草稿還原、重新整理不重跑、05 回到 04。

隔離入口：從 `backend` 執行 `.venv\Scripts\python.exe -m tests.debug_preview`，使用 `127.0.0.1:18764`。SSH／Agent 都是替身、影像為合成；模擬服務約 3 秒結束以縮短 UI 驗證，不能冒充真實 60 秒期限、雲端分析或硬體驗收。與正式 8100 的儲存及服務分開。

### 現場驗收（待新版後端啟動後集中進行）

- [ ] HC 異常引導、近遠測距重測。
- [ ] TFT RGB／本次測試碼與實體畫面確認。
- [ ] 真實 Agent 對可修復邏輯的候選、套用及草稿還原。
- [ ] Pi 上實際 60 秒試跑、自行提前停止、斷線後遠端到期、恢復連線核對。
- [ ] 多分頁與部署／零件測試交接沒有 GPIO 重疊占用。
- [ ] 距離與 TFT 同步人工確認，再正式部署，核對執行版本及輸出。

本次開發不啟動實體 Pi 測試、不停止原作品，也不提前勾選上述現場項目。更新後須重啟本機 Board Vision 後端並重新整理頁面，僅重新整理不足以載入新的後端 API。

### 重測入口操作修正

「選中此零件重測」改為「前往此零件重測」。點擊後選中對應零件，捲動並聚焦／高亮單項測試卡；同一零件重複點擊仍有反應。首次載入與背景輪詢不捲動，導覽不自動啟動測試，也不清除接線紀錄。當前選擇與原始問題來源分開保存，切換到 TFT 不會改寫 HC 的測試編號或現象。

此修正僅涉及前端，建置後重新整理即可；前端回歸增加至 168 項，TypeScript／正式建置通過。實體測試入口沒有被自動觸發。

### Stop a running project without starting another task

Use **Execution → Stop project → Confirm stop** to stop only the current
`boardvision-pi.service` invocation. This preserves the project, draft code,
wiring confirmations, AI conversations and test history; it neither shuts down
the Pi nor starts a test/deployment. Remote inactive state and an empty PID must
be confirmed before reporting success. Stopping software is not power isolation:
turn hardware power off before changing physical wiring.

Cancel queued work first; active tests/trials must be stopped from their own
cards. The standalone stop endpoint requires the displayed program owner and
holds the FIFO lock while reserving the Pi client. A changed invocation, unknown
state, remote test service, busy operation or unconfirmed stop blocks the action.
Failed mutating requests are never retried automatically. If `/api/pi/stop` is
missing, restart the backend rather than bypassing the execution coordinator.
