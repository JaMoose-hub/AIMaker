# Tinkro iPhone prototype

目前優先使用 **iPhone Safari 網頁版**：不需要 Expo、Apple 開發者會員或安裝 App。啟動、HTTPS 憑證與拍照步驟請看 [手機網頁版操作說明](mobile-web-prototype.md)。下面保留原生 Expo 版本的操作與共用後端契約。

手機是獨立影像來源，可在沒有 webcam 影格時使用聊天、WebRTC 取景與固定照片 GPIO 引導。桌面的「連接手機」位於共用 AI 對話區，手機以 Expo 自訂開發版使用；不能使用 Expo Go。相機、實際畫質、GPIO 對位及原生模組相容性仍需 iPhone 實機驗收。

## 啟動

現有本機設定保持原樣。新增後端依賴後執行：

```powershell
cd C:\Project\PnP\board-vision\backend
uv sync
cd ..\frontend
npm ci
npm run build
cd ..
.\scripts\start-mobile-prototype.ps1
```

此工具在前景監聽 `0.0.0.0:8100`，既有埠正在使用時會報錯，不會停止其他後端。桌面開啟 `http://127.0.0.1:8100`；手機須連上相同 Wi-Fi，並使用桌面 QR 中的筆電區網位址。Windows 防火牆需允許這個 Python 後端在私人網路連線；WebRTC 另使用同網段 UDP。AP 用戶端隔離、VPN 或防火牆封鎖可能導致聊天成功而影片失敗。配對面板可手動指定正確網卡 IP。

CUDA 環境沿用目前 `backend/config.yaml` 及 `uv` 的 CUDA 群組，未覆蓋相機設定。無 NVIDIA GPU 的另一台電腦請依現有 [CUDA 文件](cuda-inference.md) 選擇環境，不把設定為 CUDA 視為推論已在 CUDA 執行。

## iPhone 安裝

```powershell
cd C:\Project\PnP\board-vision\mobile
npm ci
npm run typecheck
npm test
npx eas-cli login
npx eas-cli build:configure
npx eas-cli device:create
npx eas-cli build --profile development --platform ios
npm start
```

Windows 使用 EAS 雲端原生建置，需 Expo 帳號、Apple 開發者會員及註冊 iPhone。EAS 會建立帳號專屬 project ID 與簽章資料；本次沒有代填、登入或派送建置。安裝 internal development build 後啟用 iPhone 開發者模式，連接 Metro，再在 Tinkro App 掃描配對 QR。這不是上架流程。[Expo 實機建置](https://docs.expo.dev/tutorial/eas/ios-development-build-for-devices/)

詳細手機設定、測試及原生相容性限制見 [mobile/README](../mobile/README.md)。

## 操作

1. 桌面確認目前作品，按「連接手機」，手機掃描 QR 或輸入位址與六位碼。
2. 兩端加入同一份伺服器聊天。手機可以傳文字、最多四張照片或一支 60 秒／200 MiB 影片；上傳與送出失敗保留原 request ID、附件引用與作品快照，手動重試。輸入區明示目前引用照片，送出後不會因後來新增的照片而改變。影片只擷取最多八張時間戳影格，不分析音訊。
3. 手機開啟取景引導。後置相機要求 1080p30，取得失敗可改用 720p。兩端顯示收到的尺寸、影片速度及辨識速度；設定目標不是實測達成值。
4. 筆電以目前 Pi 與目標零件的局部品質及 YOLO 位置回傳「尋找中／請穩住／可以拍照」。至少三張不同影格且一秒穩定才鎖定，提示最長有效 1.5 秒。提示不是精確 GPIO 定位結果。
5. 拍照前先取得 capture ticket，再關閉 WebRTC 相機、啟動 Expo Camera 拍攝新的高解析度照片。票與作品綁定，上傳期限 120 秒，與預覽 TTL 分開。照片逾時保留為附件，但需重新取景拍攝才能完成 GPIO 定位。
6. 正式照片保存原檔與方向校正後的分析 JPEG；超過 12MP 的分析副本等比例縮小。YOLO、板面／排針／Pin 幾何全部在此照片重新計算，預覽座標不會傳入定位。
7. 手機原生圖片＋SVG、桌面被動照片檢視顯示同一照片、尺寸、框與已確認幾何的腳位。選線、上一步／下一步同步，縮放各自保留。可以詢問照片、核對一條或全部接線，回答進入同一對話。照片幾何不足保持未確認原因。

新作品／工作區需手機選擇加入。既有照片及聊天保持原歸屬；舊照片不能套用到新照片或不同作品版本。App 背景或取景關閉時停止相機；返回前景後重新開啟。

## 實作契約

| 通道 | 用途 |
|---|---|
| `/api/mobile/context`, `pairings`, `pair`, `session`, `join` | 桌面版本化快照、短期配對、目前作品 |
| `conversation`, `messages`, `assets` | 沿用 AssistantService durable history；HTTP 附件與 AI 請求去重 |
| `stream`, `stream/offer` | 手機 publisher，桌面 recvonly viewer；同區網 ICE，沒有公共 TURN |
| `events` | WebSocket 最新狀態、取景 TTL 與共用照片／選線 |
| `capture-ticket`, `captures`, `view` | 正式照片一次分析、保存、查詢、選線同步 |

手機只讀自己的影像工作階段，不讀 webcam FrameBus、不套用 webcam 校正，也不改其 live tracker。模型持有者統一鎖定 locate／close；手機借用模型不會關閉借用的 owner。每次照片建立新的 PhotoGeometry。影像轉送使用 aiortc 的 unbuffered MediaRelay，抽樣辨識最多三次／秒，影片收取及計數獨立；待辨識內容保留最新影格。[aiortc MediaRelay](https://aiortc.readthedocs.io/en/latest/helpers.html)

`video_fps` 來自輸入影片影格計數；`recognition_fps` 與 `recognition_ms` 來自抽樣推論。`model_runtime` 回報每個 owner 的實際 provider／fallback，不能以要求 CUDA 推斷成功。桌面解碼顯示 FPS 另外由 WebRTC stats 計算。

媒體保存在 `backend/runs/mobile/assets`，照片定位保存在 `backend/runs/mobile/captures`，上下文快照保存在 `backend/runs/mobile/contexts`；共用聊天仍在 `backend/runs/assistant`。這些資料不進 Git。重啟後聊天、附件與照片保持；WebRTC 與配對憑證需重新建立，未完成 AI 工作顯示結果未知，不自動重送。

## 驗證邊界

軟體測試使用保存的測試照片、假模型／假 AI、合成影片與隔離桌面預覽。它們驗證來源隔離、版本／座標契約、去重、過期提示撤銷、WebRTC 與介面流程，不代表真實模型準確率或 iPhone 原生能力。

尚待實機：iPhone 開發版安裝、1080p30 實際接收與延遲、相機交接、背景返回、橫直拍照、Pi 排針行列與 HC／TFT 方向、附件中斷恢復、拔除 webcam 的完整實際操作與 webcam 硬體回歸。未進行上架、遠端網路、模型訓練、Pi 部署或電氣測試。

本次完整軟體檢查與兩項既有本機設定測試的失敗原因，見 [驗證紀錄](qa/mobile-prototype-2026-10-02.md)。
