# Tinkro iPhone Safari prototype

iPhone 使用 Safari 網頁作為獨立影像來源，透過 WebRTC 傳影片給現有 Tinkro 後端，並沿用配對、共用聊天、取景提示、照片分析與 GPIO／Pin 檢視。不需 Expo Go、EAS 建置或 Apple 開發者會員。手機網頁不能呼叫 Pi 部署、電氣測試或桌面相機控制。

## 啟動筆電

沿用唯一的 Tinkro 後端 `8100`。HTTPS gateway `8443` 只轉送手機 API 與 WebSocket，不載入 `app.main`，也不建立另一份相機／模型工作者。

```powershell
cd C:\Project\PnP\board-vision
# 先完成 backend 的 uv sync 與 frontend 的 npm run build。
# 保留現有 8100 後端；更新程式時由原終端關閉後再啟動，避免重複相機。
.\scripts\setup-mobile-web-https.ps1
.\scripts\start-mobile-web.ps1
```

`setup-mobile-web-https.ps1` 自動找有 gateway 的 Wi-Fi IPv4；也可明確指定：

```powershell
.\scripts\setup-mobile-web-https.ps1 -LanAddress 192.168.50.141
```

本機以 Python `cryptography` 建立 Tinkro LAN Development CA，並簽發含目前 Wi-Fi IP SAN 的伺服器憑證。檔案位於 `backend/runs/mobile-web-https`，已被既有 `runs/` 規則排除於 Git。這些工具不修改 Windows 憑證信任或防火牆。

`connection.json` 記錄 `{base_url, backend_url, port}`，供桌面配對面板取得可用 HTTPS 網址。CA 私鑰為 `rootCA-key.pem`，HTTPS 私鑰為 `server-key.pem`，只保留在筆電；手機只取得公開 `rootCA.der` 或 `rootCA.mobileconfig`。

若需要重新啟動既有後端，使用其原本虛擬環境與配置，並接受**僅來自 loopback** 的代理 client IP：

```powershell
cd C:\Project\PnP\board-vision\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8100 --proxy-headers --forwarded-allow-ips '127.0.0.1,::1' --timeout-graceful-shutdown 3
```

gateway 對上游傳 `X-Forwarded-For` 與 `X-Forwarded-Proto: https`，IP 取自實際 socket；gateway 不信任使用者輸入的 forwarded headers。這讓後端仍將手機辨識成區網手機，不能因 proxy 來源是 loopback 就取得桌面控制權。不要把後端 `forwarded-allow-ips` 設為 `*`。

## iPhone 第一次安裝公開 CA

Safari 相機需要可信任 HTTPS；目前 `http://192.168.50.141:8100` 可以下載公開憑證，但不能當作網頁直播的相機入口。第一次操作：

1. 確认 iPhone 與筆電同 Wi-Fi。
2. 在 Safari 開 `http://192.168.50.141:8100/api/mobile/web-ca-profile`，下載 **Tinkro LAN Development CA** 描述檔；實際 IP 以 setup 工具輸出為準。
3. 到「設定」的「已下載描述檔」安裝該描述檔；亦可在「一般 → VPN 與裝置管理」找到它。
4. 到「設定 → 一般 → 關於本機 → 憑證信任設定」，開啟 **Tinkro LAN Development CA** 的完全信任。
5. 回 Safari 開 `https://192.168.50.141:8443/mobile`，應沒有憑證警告，再允許相機權限。

安裝描述檔不會自動啟用 TLS 信任，必須完成第 4 步。[Apple 官方操作說明](https://support.apple.com/en-us/102390) 單純略過瀏覽器憑證警告不能替代可信任 HTTPS。[相機 API 要求](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)

也可下載 `http://192.168.50.141:8100/api/mobile/web-ca` 的 DER 證書。HTTPS gateway 另提供 `/mobile-ca.crt`、`/mobile-ca.mobileconfig`，但尚未信任 CA 時，先使用上述 HTTP 下載入口。

Wi-Fi IP 改變時重新執行 setup，重啟 gateway。工具沿用同一 CA，只更新含新 IP 的葉憑證，所以不需每次重新安裝 CA。刪除 CA 或更換筆電後則必須重新安裝新的公開 CA。測試結束可在 iPhone 的「VPN 與裝置管理」刪除此描述檔。

## 配對與使用

1. 桌面確認目前作品；在頂部 Pi 連線左邊按「連接手機」。三階段共用同一個連線入口。
2. 用 iPhone 相機／Safari 掃描手機網頁 QR，或在 `/mobile` 輸入六位配對碼。
3. 手機加入同一份作品與聊天，允許後鏡頭取景。橫放與直立都能串流；1080p 的相機請求分別為 **1920×1080／1080×1920**，實際輸出由相機決定。30 FPS 為目標而非保證；相機來源尺寸、實際上傳尺寸、影片 FPS 與辨識 FPS 分開顯示。
4. 手機「拍照問 AI／除錯」不需要 Locked，將本地取景照片加入聊天草稿，輸入問題後送出。「GPIO 引導拍照」則等待 Locked，再保存正式照片並重新執行 YOLO 與 GPIO／Pin 定位。筆電也可按「截取手機影像」建立正式照片。照片和選取線路同步，兩端縮放各自保存。傳輸畫質可選最高目標 3／8／12 Mbps；這是上限設定，實際傳輸另行顯示。
5. 問照片或核對接線的結果保存在同一份聊天。新照片獨立分析，不能沿用前一張照片的腳位座標。

02 在「本步驟 2D 接線圖」同排按「手機取景」，透過既有相機來源切換將完整手機影格送入 FrameBus，使用原本 Webcam／2D 的主畫面；按「返回 Webcam」恢復原鏡頭。同排「GPIO 照片」開啟既有照片面板，沒有照片時停用，不自行拍照。手機面板保留配對及 GPIO 照片檢視，AI 收合後仍可從頂部手機入口開啟。主畫面顯示手機時不在面板開第二份影片接收器；返回 Webcam 不停止手機發布串流。

手機作為主畫面來源時，桌面 Webcam 的拍攝倒數、板型校正及切換鏡頭暫停使用；改用主畫面的「截取手機影像」。手機有獨立的來源與追蹤生命週期，不套用 Webcam 校正；保存照片後使用該照片自己的定位資料。正在校正、照片倒數、照片接線 POC 或智慧眼鏡切換時，先完成目前操作再進入手機主畫面。來源切換沿用現有交易與復原流程，不修改 Webcam 參數，相關說明見 [相機來源整合](camera-source-integration.md)。

手機上下文保留作品版本、接線目標、輪次、程式與原有影像快照，但不帶桌面暫時的 `debug_session_id`。桌面啟停除錯不再被誤判為更換手機作品；手機純文字問題使用共用聊天的文字建議，照片問題沿用 media 分析，桌面原除錯流程不變。真正切換作品或接線步驟時，手機仍顯示「加入目前作品」。

筆電截圖保存後端剛收到的完整手機影格為 PNG，不截取網頁或已縮放的桌面預覽。尚未 Locked 也可手動截圖；沒有新影格、作品已切換或串流已停止時會顯示原因。同一次失敗重試讀取原本那張照片，不另抓新畫面或重複推論。

兩種手機拍照都保存本地 `<video>` 的完整原始尺寸影格，JPEG 品質 95，不經 WebRTC 影片壓縮；保存期間不釋放相機。照片與聊天分頁也保留串流。一般除錯照片先保存在聊天草稿，按送出後才上傳並請 AI 回答；GPIO 正式照片上傳成功後來源旁顯示「已保存至筆電」，失敗的照片保留為可重試草稿。1080p 目標為 1920×1080 或 1080×1920，720p 為 1280×720 或 720×1280，**不是手機感光元件的原始 12MP 照片**。相簿與系統相機附件仍保留原尺寸，可用於一般聊天。

### 橫直向串流與除錯拍照（2026-10-03）

取景頁預設只顯示完整相機畫面、開啟／停止、兩種拍照按鈕與簡短 GPIO 提示。「取景設定」預設收合，內有解析度、畫質及套用；FPS、碼率、尺寸與 RTT 收在內層「串流資訊」。展開資訊不重連或取得另一份相機；修改設定後按套用才重連。

橫向且畫面寬度至少 560px 時，同一份取景元件改成左右配置：左側完整影片佔滿安全區內高度，右側放工作區、開始／停止、拍照、提示與導覽。右側設定可獨立捲動，展開後不壓縮或蓋住左側影片；長寬比不同時等比例留黑邊。直向保留上下配置。這是版面重排，不因 CSS 方向改變另開相機。

手機取景穩定判斷改以候選 Pi 板面的對角線作共同尺度，不再分別除以影片寬高。因此同樣構圖旋轉 90 度後，位置、尺度與角度的判斷一致。初始容許量為中心位移 8%、角點最大位移 12%、角度 8 度及尺度比 1/1.12 到 1.12；四角的方向順序也必須一致。基準固定，避免逐步移動仍累积鎖定。

最近 1.4 秒內需至少三張合格且不同的影格，跨度至少一秒，合格影格間隔不得超過 0.7 秒。單張漏辨識或模糊立即取消可拍照，但候選最多短暫保留 0.7 秒；恢復時仍須最新影格合格。連續失效、明顯移動、方向重連、作品切換或過期會清除候選。找不到 Pi、找不到指定零件、未完整入鏡、距離過遠及清晰度不足分別顯示一個簡短原因。這些是初始取景門檻，需要實機校準；Locked 不代表實體 GPIO 接點已確認。新版軟體與版面驗證见 [鎖定與橫向取景 QA](qa/mobile-lock-landscape-2026-10-03.md)。

橫向、直向與方形原相機影格均能傳送。發布端依手機方向請求對應的長短邊，但始終以解碼後的 `videoWidth/videoHeight` 為準；不交換尺寸、旋轉 CSS、裁切或放大來冒充解析度。直接使用相機原始 MediaStream／track，Canvas 只在明確拍照時擷取一張 JPEG 95。來源只有 720p 時就如實顯示與傳送 720p。

手機方向或原影格尺寸改變時，先撤銷舊 Locked、關閉舊串流並釋放相機；待伺服器確認關閉，再為新方向重連。重新連接使用新的 generation，清除舊追蹤與腳位。已選擇手機主畫面的筆電在收到新影格後跟隨新 generation；正在使用 Webcam 時不自動切換來源。鍵盤或同方向的頁面尺寸變化不重開相機；停止、背景、作品切換會取消待執行的重連。

「拍照問 AI／除錯」只需本地相機正在傳送且有完整影格，不等待 YOLO、Locked 或筆電接收提示。成功加入同一作品的草稿後切到聊天；使用者可補充問題、刪除或重試附件，沿用既有上傳與共用對話。這個按鈕不建立 GPIO 正式照片或把未確認定位當作已確認腳位。

「GPIO 引導拍照」保留 Locked、提示新鮮度與正式拍照請求，對新照片重新定位。兩種拍照均核對拍攝前後的作品與串流身分；切換作品或方向時，不把完成較晚的舊照片加入新工作區。

更新後停止舊取景並重新整理手機及桌面，再以任何方向開啟取景。實際 FPS、Safari 方向切換與硬體照片品質仍需實機驗證。桌面保持等比例完整顯示，允許留白以保留全部接線。新版驗證見 [橫直向與除錯拍照 QA](qa/mobile-portrait-debug-2026-10-03.md)，舊版歷史結果見 [橫向取景 QA](qa/mobile-orientation-2026-10-03.md)。

手機本地拍照／筆電截取手機影像共用被動照片檢視，不呼叫會鎖定 Webcam 的 Photo Wiring 工作階段入口，也不變更 Webcam 來源、校正、追蹤或設定。02 現在將這些照片交給主畫面的「GPIO 照片」，與明確擷取的 Webcam GPIO 照片共用檢視；照片與自己的尺寸／定位綁定，不混用即時座標。Webcam 明確擷取會短暫取得及釋放原 Photo Wiring 工作階段；只看照片不取得工作階段。「可拍照」只表示取景合適，GPIO 是否完成精細定位由照片分析另行顯示。

切到背景、鎖屏、失聯或相機中斷時停止取景並撤銷可拍照提示；返回網頁後重新連線。本版不支援背景直播。

按「離線」會停止串流並撤銷目前配對，桌面可重新產生 QR；伺服器保留照片與聊天。下載描述檔後，請在 iPhone「設定」首頁帳號下方點「已下載描述檔」安裝；下載後 8 分鐘仍未安裝會被 iOS 刪除，需重新下載。[Apple 安裝說明](https://support.apple.com/zh-tw/102400)

### 原相機串流優化（2026-10-03）

手機預設 1080p／30 FPS 目標、12 Mbps 上限；筆電 H.264 初始 target 跟隨選擇，保留網路自適應。實際相機來源、上傳與接收尺寸分別顯示，不承諾固定 30 FPS 或固定 12 Mbps。

新收到的影片影格有獨立時間與序號。停收超過 1.5 秒撤銷取景鎖定、清除舊的影片／辨識 FPS；聊天或診斷 heartbeat 不代表影片正常。手機在前景、同本次啟動工作區、沒有拍照或上傳作業時，超過五秒未收影格可受控重連一次；第一次沒有收到影格亦有期限。停止、背景或切作品取消恢復，避免反覆啟動。

手機送出影格已取消 Canvas 逐幀重畫，但筆電桌面預覽仍經 aiortc 解碼後重新編碼，沒有 SFU 封包直接轉送。測試及實機範圍見 [原相機串流優化 QA](qa/mobile-native-stream-2026-10-03.md)。

## 網路與排查

Windows 必須允許相應 Python 程式在目前網路類別接受區網連入：TCP `8100` 用於初次 CA 下載、TCP `8443` 用於手機 HTTPS、UDP 用於 WebRTC ICE。來源可限制為 `LocalSubnet`。此處沒有自動修改防火牆或網路類別；一般 PowerShell 權限無法新增防火牆規則。

- 連 HTTP 都失敗：檢查 IP、同 Wi-Fi、Windows firewall、VPN 或路由器用戶端隔離。
- HTTPS 有憑證警告：確認 CA 已安裝及完全信任，並且網址 IP 包含在目前伺服器憑證 SAN。
- 沒有相機權限提示：用 Safari 直接開可信任 HTTPS 手機入口，確認 `window.isSecureContext`，檢查 Safari 網站相機權限。
- 聊天可用、影片不通：WebRTC 另需同網段 UDP；檢查 ICE 狀態及 firewall。第一版沒有公網 TURN relay。
- proxy 回 `502`：確認唯一的 `8100` 後端仍在運行。
- setup 後 QR 仍是 HTTP：確認 `8443` gateway 已啟動，再重新開配對面板。

gateway 首頁重新導向 `/mobile`，只提供 Vite `/assets`、固定的 `/theme.js` 與 `/brand/tinkro-symbol.svg`、公開 CA 與列出的手機 API；`/api/pi/*`、桌面 `/api/mobile/context`／`pairings`／`desktop-session`／`web-config` 不會經此 gateway 公開。WebRTC 媒體仍由原本 aiortc 接收與轉送；HTTPS proxy 處理協商、上傳與狀態通道，沒有轉碼直播。

## 驗證範圍

自動測試驗證路由白名單、真正 client IP 轉發、Bearer／上傳資料保留、WebSocket 清理、憑證簽章與 SAN、公開 CA 不含私鑰、CA 重用與前端靜態檔隔離。這些測試不會啟動相機、Codex、Pi 或改 OS 信任。

iPhone Safari 的接收 FPS 已有短程實測，詳見 `docs/qa/mobile-web-2026-10-02.md`；雙拍照、端到端延遲、GPIO 精度與背景回復的實機範圍亦逐項記錄於該文件。設定目標不代表實測速度；畫面與模型條件不足時仍保持未確認狀態。
