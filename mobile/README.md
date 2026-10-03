# Tinkro 手機原型

這是獨立的 Expo TypeScript **development build**。WebRTC 使用原生模組，不能以 Expo Go 驗證。

## 開發

```powershell
cd C:\Project\PnP\board-vision\mobile
npm ci
npm run typecheck
npm test
npm run check
npm start
```

Android：裝妥 Android Studio/JDK、連接實機後執行 `npm run android`。iOS 原生編譯需 macOS/Xcode；Windows 可在具備 Expo / Apple 開發者帳號與實機簽章後自行執行 `npx eas-cli build --profile development --platform ios`。本次未登入帳號、未派送 EAS 建置、未發布 App Store。`development-simulator` 僅供 macOS 模擬器；相機與 WebRTC 接線流程須實機驗證。

電腦後端須監聽 LAN，手機與電腦須同一網路。桌面產生配對碼與 QR 後，掃描或填入完整 `http://電腦IP:後端port` 和配對碼。不要輸入手機自己的 localhost。Android cleartext 與 iOS 本機網路/ATS 是此區域網路原型設定；正式遠端部署應使用 HTTPS 與對應服務設定。

## 已實作的流程

- 掃描 `{type:"tinkro-mobile",base_url,code}` / 手動配對；SecureStore 儲存憑證。
- 同一 conversation 每 1.5 秒輪詢、較早歷史分頁、WebSocket 狀態與選線同步。
- 純文字追問在輸入框顯示將沿用的最近照片名稱／數量或影片名稱／秒數；新附件優先。新拍攝的定位照片取代舊媒體引用，瀏覽舊照片本身不會更換引用。
- 新待送訊息凍結送出時的媒體 ID／照片 ID 與 `inherit_media:false`，沒有媒體也凍結為空；重試不改成另一張照片。舊待送資料不補這個欄位，保留原本 request 指紋。
- 草稿以電腦位址＋conversation ID 保存，重新配對同一段對話會恢復；會先嘗試遷移目前舊配對的 session 檔。跨專案「加入」先保存原草稿再載入目標對話的草稿，原附件與待送訊息不改綁到新專案，也不會自動重送。新 token 僅保存在 SecureStore。
- iOS 相簿要求 Compatible 格式；若仍回傳 HEIC／HEIF／AVIF，使用 Expo ImageManipulator 原生轉換為 JPEG 後上傳，並更新真實輸出尺寸與檔案大小。這條原生轉換分支仍需 iPhone 實測。
- 文字、最多四張照片或一支 60 秒／200 MiB 影片。檔案複製到 App 文件目錄、草稿與送出佇列保存；重試保留 request_id / upload_id。附件上傳顯示進度。
- 後置 WebRTC 預設要求 1920×1080 / 30 FPS，取得相機失敗時重試 1280×720。RTCView 顯示本機串流，顯示軌道實際回報尺寸。接收端使用同網段 ICE，不依賴公共 TURN。
- 最新且未逾時的定位可取得 capture ticket；**先拿票、再關閉 RTC、再啟動 ExpoCamera**。高畫質照片上傳後 finalize，取得原生照片標記封包。若票逾時保留照片並要求重新定位拍攝，不把舊照片冒充新畫面。
- SVG 標記與照片共用原始像素座標、contain 比例、縮放與平移。只對同 frame 且已校正的 pose 顯示腳位；虛線本體表達未確認。雙指縮放、倍率按鈕、前後選線、問照片／檢查此線／全部均使用同一對話。
- App 進入背景會立即停止相機 tracks、關閉 peer 和預覽。返回後需手動重新開啟串流，定位 TTL 不延續。

## 仍需實機驗證

本機型別、純函式測試、Expo 設定與 JS 打包不代表原生相機已可用。需分別在 Android/iPhone 開發版驗證 QR 權限、區網連線、WebRTC 1080p／720p 實際協商、RTC→拍照相機交接、背景返回、附件中斷重試、橫直照片座標、桌面同步與實際模型定位。沒有實機／簽章時不能聲稱端到端硬體驗證完成。

目前驗證：TypeScript、14 個純函式與 API 測試、Expo SDK 依賴檢查、prebuild 設定讀取及 Android / iOS Hermes JS 打包通過。Expo Doctor 為 20/21；未通過項目是 `react-native-webrtc` 在 React Native Directory 的「Untested on New Architecture」註記，未隱藏這項結果。`npm audit` 的 13 項報告位於上游 Expo / CLI 的 node-forge、uuid 相依鏈；其 force 建議會降級 Expo 至舊主版，因此本原型未套用。

API 採 `/api/mobile`：pair/session/join/conversation/messages/assets/stream/stream/offer/capture-ticket/captures/view/events；HTTP 使用 bearer，圖片 header 附帶 bearer，WebSocket 使用 token query。Token 不寫入普通草稿檔。

版本選擇依 npm stable Expo 與 `expo install` 相容清單；套件精確版本以 lockfile 為準。官方說明：[Expo development builds](https://docs.expo.dev/develop/development-builds/introduction/)、[WebRTC config plugin](https://github.com/expo/config-plugins/tree/main/packages/react-native-webrtc)、[Expo Camera](https://docs.expo.dev/versions/latest/sdk/camera/)。
