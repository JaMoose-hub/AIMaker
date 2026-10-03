# 手機頁「取景」改為「串流」— 2026-10-03

手機頁籤、標題、啟動、設定、重新串流、照片頁引用、桌面手機面板與手機端錯誤提示同步更新。構圖穩定提示使用「畫面穩定」，相機本地 FPS 保留「手機相機」，避免與傳輸 FPS 混淆。僅文案改動，串流功能與 Webcam 設定維持原樣。

TypeScript / Vite build、761 語系 key 檢查、79 項既有 mobile_web / mobile_browser / mobile_capture 測試通過。既有測試的顯示 label 更新為 Stream；內部 camera 工作階段 ID 保持原值。

隔離 UI 預覽已確認「串流」「開啟串流」「串流設定」，未啟動相機或呼叫正式 AI。截圖：mobile-stream-label-2026-10-03.png。正式 8100 已送出新版 build，毋須重啟後端；現有手機頁需重新整理載入。
