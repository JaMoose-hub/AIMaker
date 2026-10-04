# 接線拍照與即時辨識隔離

## 問題與證據

工作區上方的「擷取接線照片」先前使用 `GpioPhotoCapture.capture()` 取得 `/api/photo-wiring/sessions` 暫停租約。`PhotoWiringService.start()` 會停止即時辨識 worker、清空 detection/component/motion 狀態；拍照時又對即時零件 worker 執行 `reset_tracking()`，完成後才恢復。這條程式路徑會中斷追蹤並讓零件重新定位。

聊天中逐張取證的 `capture_debug_evidence()` 本身只讀既有 FrameBus 並編碼，沒有上述暫停租約。沒有把截圖中某次定位變化當作這條舊路徑的實機重現證據。

## 修正

- 新增 `POST /api/photo-wiring/snapshot`，工作區拍照改為單次提交，不取得暫停租約。
- 從既有 FrameBus 取得請求後的一個新影格並複製；所有模型結果、原圖及來源 metadata 使用同一影格。
- Pi 沿用獨立照片 detector；零件的 `ComponentPhotoContext` 借用現有模型與固定 profile/reference，保持自己的照片搜尋 cursor。既有模型擁有者鎖序列化 forward，照片不 reset、停止、關閉或發布即時 worker。
- 沿用原 PhotoGeometry、模型、門檻與保守的定位證據；沒有將快照結果寫回即時追蹤。
- 舊 POC 的 `/sessions` 暫停／恢復介面保留。

## 軟體验证

累計執行 **11 項，11 通過，0 失敗，0 重跑**：

- `backend/.venv/Scripts/python.exe -m pytest tests/test_photo_snapshot.py -q`：5 項。
- `node --test --test-name-pattern='viewing is passive|double-click|capture failure|source and runtime binding|late source' tools/gpio_photo_workspace.test.mjs`：6 項。

涵蓋 worker／追蹤保留、單一影格與原圖雜湊、獨立搜尋狀態、共用模型序列化、来源或結果不一致拒絕、錯誤後釋放相機控制鎖、舊 POC 生命週期、連點及桌面／手機來源綁定。Python 編譯與相關差異空白檢查通過。

測試使用合成影格及假模型，沒有開啟相機、雲端、SSH、Pi 或 GPIO。尚未測量實體相機的 FPS、拍照前後追蹤表現或真實接線辨識準確度。照片分析仍可能短暫競爭 CPU/GPU；修正的是不必要的停機／清空追蹤，沒有宣稱零資源影響。

整體建置、服務重啟及聊天分析時間／輸入鎖定由本輪主流程驗證另行記錄。
