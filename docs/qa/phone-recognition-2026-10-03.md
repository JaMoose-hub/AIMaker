# 手機主畫面即時 YOLO 疊圖

2026-10-03。僅擴充既有手機樣本與共用疊圖，保留現有 Webcam、GPIO 照片、接線確認、聊天及 Pi 流程；不提交或覆蓋其他未提交修改。

## 實作

- `mobile_photo.preview` 複用同次筆電 YOLO 結果，依目錄投影 Pi 40 GPIO 與 HC-SR04／MRD-TFT240 腳位；Pi 使用共用四角合理性、邊界、J8 helper，不讀 Webcam 相機或 tracker 狀態。
- `MobileService` 將辨識結果透過既有手機 session 推送；綁定配對、世代、context、樣本及尺寸，獨立保存辨識期限。拍照未 Locked 不抹除當前有效物件；逾時、切換作品、停止或斷線清除舊結果。
- 同作品即時辨識可跟隨最新接線步驟，但不自動變更手機凍結的聊天／照片上下文或解除擷取保護。
- `MobileRecognitionOverlay` 重用既有 PinOverlay、ComponentPinOverlay、GuideConnectionOverlay 及 joint label placement；依實際解碼尺寸與 contain letterbox 顯示，不套用 Webcam 鏡像／手動偏移。淺色模式影像文字仍為白色描邊。
- React 品質檢查：保持 RTC effect 僅依 session／generation／transport availability／重試變更；辨識 props 或接線目標更新不重開 peer，疊圖只做顯示，不訂閱 Webcam detection 作為座標。資料期限由桌面控制器保存，同一樣本重開畫面不重新續期。

## 自動化

- 後端：`pytest tests/test_mobile_recognition.py tests/test_mobile_photo_analyzer.py -q`：17 通過。
- 既有後端回歸：`pytest tests/test_mobile.py -q -k 'actual_workspace_changes or preview_requires_unique or state_event_queue or slow_drift'`：9 通過。
- 最後後端確認：新增檔案 `-k 'live_analysis_follows or live_recognition_survives'`：2 通過（重跑）。
- 前端：`node --test tools/mobile_recognition.test.mjs tools/mobile.test.mjs`：52 通過。
- 前端最後檢查：`--test-name-pattern='board and every component'`：1 通過（重跑，包含空值／非有限座標防護）。
- 合計 78 個不同自動案例、81 次執行。未執行超過 100 案例的完整套件。
- 建置共 5 次：首次發現手機 component packet 的 runtime revision 型別缺失，修正後其餘 4 次通過。最終仍有既有 bundle-size warning，不當作失敗或速度測量。

## 隔離瀏覽器

使用 `frontend/tools/gpio-photo-preview.mjs`，127.0.0.1:18794，無 API proxy；影片為合成 Canvas，模型／RTC 及作品均為 fixture。瀏覽器技能要求在啟動後立即核對載入、截圖、互動快照與 errors。

11 個驗證情境（包含最終建置重新載入確認）：

1. 初始页面正常載入，沒有 error overlay／瀏覽器例外。
2. 手機主畫面有三份共用板／零件疊圖，Pi 40 GPIO 顯示。
3. 開始接線：`GND_P6:GND`。
4. 下一步：`GPIO17:TRIG`；viewer opened=1、closed=0，不重新連線。
5. 偽造直立辨識尺寸而解碼仍橫向時，疊圖=0；尺寸恢復後=3。
6. 停止產生新樣本超過期限，疊圖=0；恢復後=3，viewer 不重開。
7. 返回 Webcam 時手機疊圖=0，桌面 viewer 關閉；切回手機只開一份 viewer。
8. 390×844：無水平溢出，疊圖寬353px與影片區一致；桌面另涵蓋1651×871。
9. 斷線時疊圖=0；世代更新／重新連線後=3，先前 viewer 清理。
10. 1413×871、繁中淺色畫面：影像文字不應受亮色頁面染黑。
11. 最終 CSS 與空值保護建置後，重新載入淺色手機畫面，確認白色描邊與三份疊圖／無例外。

自動案例81次＋瀏覽器11情境＋建置5次＋後端恢復smoke1次，合計98次，包含重跑與失敗建置，低於100。Fixture沒有 AI 生成、部署、Pi 測試或 stop 請求。

圖片：`phone-recognition-initial.png`、`phone-recognition-live.png`、`phone-recognition-wiring.png`、`phone-recognition-narrow.png`、`phone-recognition-light.png`；最後一張為最終重驗更新版本。

## 服務與限制

使用者明確同意重啟。重啟前只讀確認 Pi jobs空、component test無active、AI不忙、debug/trial無active；核對8100為現有Tinkro supervisor的uvicorn，再停止指定子程序79184，由原supervisor恢復為90472。保留原啟動參數，沒有建立第二份正式相機服務；讀取 `/api/config` 恢復成功。手機需重新配對。

沒有用實際手機、實際 YOLO GPU 串流、實體 GPIO、電氣或功能測試驗證；所有前端／模型輸入測試均為模擬。WebRTC 與辨識資料仍非同步，3Hz樣本上限未改；目前是最近有效樣本的即時引導，不宣稱每個播放影格與座標同步，亦不把投影腳位當成已接線／已通過證據。
