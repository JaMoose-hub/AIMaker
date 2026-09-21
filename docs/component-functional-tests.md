# 接線引導：零件功能測試 v1

狀態：軟體實作與模擬驗證；**實體硬體驗收尚未完成**。

## 使用方式

1. 進入 Pin 接線引導，逐腳確認本零件全部必要接線。
2. 同一張卡片按「連線 Pi」（若尚未連線），再按「測試 HC-SR04+」或「測試 MRD-TFT240」。不需要鏡頭定位或 AI 登入。
3. 先檢查 Pi 環境。若原 Board Vision 作品還在執行，按鈕會要求使用者確認停止；拒絕時可停止本次測試或繼續接線。
4. HC：擺近目標 → 準備好了 → 取樣 5 秒 → 移遠目標 → 準備好了 → 再取樣 5 秒。
5. TFT：看紅、綠、藍與本次四位碼，選對測試碼且確認顏色正常，才記錄目視通過。全黑、白屏與異常有獨立除錯選項。
6. 可重新測試、查看接線，或稍後測試繼續下一零件。不會把略過或失敗改成通過。
7. 最後到「部署與測試」部署整體作品；原作品不會在測試後自動重啟。

略過後要補測，可直接點接線卡上方的零件型號切換，保留原接線紀錄，不必重新開始。

改接線前斷電，接好再上電測試。功能通過不表示已驗證所有線路、電壓或測距精度。

## 判定與邊界

- HC 每段至少 5 個不同時間的新有效回波；遠段中位数至少比近段增加 5 cm。舊快取、無回波與超出本測試有效範圍的值不會替代成正常距離。不足或移動差異不成立為「無法判定」。
- TFT 成功寫入 SPI 並退出只表示程式已送出畫面；尚未證明螢幕亮起。須完成本次人工確認。
- 測試使用現有 catalog 的 HC 3.3V、TFT 3.3V / BLK 留空方案，不調整任何模型、GPIO 對應或供電配置。
- 系統只能從可觀測錯誤指出套件、裝置權限、SPI 或資源衝突；不能由無回應推斷某一條線必然插錯。
- SPI 額外檢查 `/proc/*/fd` 中可存取的佔用資訊，GPIO 依 lgpio 的資源申請錯誤辨識衝突。無權檢視的第三方 SPI 程式無法全面偵測；不強制終止其他程式。
- 遠端執行期限 180 秒，停止寬限 5 秒；準備超過 165 秒會由 runner 提前結束。TFT 目視確認最多保留 5 分鐘，不佔用 GPIO/SPI 等待。

## 執行架構

`ProjectGuidePanel → useComponentTests → /api/pi/component-tests → ComponentTests → 既有 PiDeployer SSH → systemd-run 一次性 runner`

- 固定模板：`backend/app/runtime/component_test.py`，版本 `component-test-v3`；TFT 重用 `ili9341_display.py`。
- 獨立遠端目錄：`<remote_dir>/component-tests/<run_id>/`，不覆蓋 `main.py`、正式 service 或部署檔案。
- 狀態使用原子 JSON 寫入。回報 run_id、階段、心跳、最新有效讀值時間、段落樣本摘要與結構化錯誤。
- 後端保存 `backend/runs/component-tests.json`（已由 gitignore 排除）。每筆綁定 Pi 目標雜湊、作品與 revision、零件、接線雜湊、人工確認時間與模板版本。
- 同一後端管理的 Pi 使用共享執行互斥鎖，防止多分頁重複啟動或正式部署衝突；遠端 runner 再用 flock 防止測試程序重疊。部署請維持單一 Board Vision 後端管理，這不是跨多台管理伺服器的分散式鎖。
- 狀態不明時保留控制與鎖，重新連線查詢原服務，不重新啟動。只有確認服務 inactive／failed 或明確不存在時才釋放。
- 重新整理不會重跑。回看修改、重新開始會使原結果失效；仍執行中的測試保留停止控制。舊分頁的被動輪詢不會取消其他分頁的新測試。
- 接線頁不再掛載照片檢查 hook 或結果元件；其他 AI 設計及正式部署端點保留。
- 診斷複製遮蔽密碼、API key、權杖、Authorization 和 PEM 私鑰；真實測試碼答案不經狀態 API 回傳（只有候選選項）。

## API

| 方法 | 端點 | 用途 |
|---|---|---|
| GET | `/api/pi/component-tests?project_id=...` | 最近結果、目前執行、連線狀態；不啟動新測試 |
| POST | `/api/pi/component-tests` | 驗證 catalog/Profile/接線後建立唯一測試 |
| POST | `/api/pi/component-tests/{id}/action` | `near`、`far`、`stop_project`、`visual`、`stop`、`invalidate` |

啟動輸入包含 project_id、revision、component_id、catalog_version、profile_versions、guide_key、wires。不接受程式碼或套件名稱。確認動作必須匹配本次 guide_key；停止及失效動作仍可處理舊測試。

## 環境準備

先使用已設定的 Pi SSH 帳號。需要 systemd 使用者服務，以及 `<remote_dir>/.venv/bin/python`；測試不自動建立虛擬環境、安裝套件或修改系統。

使用「部署與測試 → 執行環境與硬體準備」的手動命令：gpiozero、lgpio；TFT 另需 spidev、Pillow、luma.lcd 2.13.0。使用 raspi-config 啟用 SPI0，核對登入帳號對 gpiochip 與 spidev0.0 的權限。

## 軟體驗證

- [x] 最後必要接線確認前不顯示測試；暫停總覽不當成完成。
- [x] 未測、失敗、略過、返回與重新開始的進度/結果分開。
- [x] 連線中斷、依賴缺漏、資源衝突、無回波、程式錯誤、逾時、停止與重測的模擬測試。
- [x] 近遠準備階段、5 秒收集參數、舊樣本去重及資料不足判定。
- [x] TFT RGB、測試碼、資源清理、人工確認與舊碼/舊設定拒絕。
- [x] 多分頁互斥、正式部署互斥、原作品停止前確認與不自動重啟。
- [x] 斷線保留鎖、後端重開重新核對服務、不重複啟動。
- [x] 前端編譯、i18n、既有設計/部署/顯示驅動回歸測試。
- [x] 隔離瀏覽器：逐腳完成門檻、停止原作品確認、HC 近遠、TFT 錯碼失敗／重測新碼／目視確認、重新整理保留結果。

重跑：

```powershell
# 在 frontend
npm test
# 在 backend
.\.venv\Scripts\python.exe -m pytest tests/test_component_testing.py tests/test_pi_deploy.py tests/test_maker.py tests/test_maker_workflow.py tests/test_ili9341_runtime.py -q
```

隔離 UI 驗證：在 backend 執行 `python -m tests.component_test_preview`，開 `http://127.0.0.1:18763/`。此測試使用合成畫面及模擬 SSH，與 8100 的使用者草稿分開，**不代表實體測試通過**。

## 集中現場驗收（待使用者操作）

- [ ] HC 近遠兩段均取得足夠新回波，結果通過。
- [ ] HC 沒有目標物時不假裝成功，重新擺放後可重測。
- [ ] TFT 實際看到 RGB 與本次測試碼，確認後通過；舊碼不通過。
- [ ] 確認停止原作品、測試後不自動恢復；遠端檔案保留。
- [ ] 執行中短暫斷線，恢復後核對同一 run，不出現第二份測試。
- [ ] 最後正式部署距離同步顯示的整體作品，觀察距離改變時螢幕數值同步更新。

現場記錄：日期、Pi 目標、本次 run_id、接線設定、現象與結果。尚未實測的項目保留未完成。

## 2026-09-21：HC 近遠切換讀取修正

- 實際紀錄 `b229bc8e8dad4767b23f4cb7eafc2879`：近段 77 筆／10.7 cm，遠段 0 筆。Pi journal 在開始遠段時記錄 lgpio callback 的 `NoneType & int` 背景執行緒異常；舊 runner 仍正常退出並誤歸類為 `no_echo`，不代表接線錯誤。
- v2 在近、遠兩段及等待移動期間共用同一個 GPIO factory／感測器，只在整次測試結束時釋放；不更改接腳、供電或測距通過條件。
- 每段只接受該段開始後新觸發的讀取；段落切換清除目前數值、最後有效時間及筆數，保留已完成段落摘要。
- 背景執行緒失敗會中止測試並回報 `reader_error` 與失敗階段，而非 `no_echo`；完整 traceback 仍留在該次服務 journal。
- 本次修正的實體近／遠重測仍待使用者操作，不沿用舊紀錄宣稱通過。
- 本次 108 項後端回歸、151 項前端測試與正式編譯通過。新版背景錯誤含真實執行緒異常注入測試，不只模擬結果 JSON。
- 當前後端重啟指令受執行環境限制，原服務保留。每次新測試會從磁碟讀取並上傳修正版 runner；已執行的測試不熱換程式。管理端 `template_version` 需在下次後端重啟後才由 v1 更新為 v2，過渡期間請以本次 run 的實際 runner 檔案核對，不單憑版本欄判斷。

## 2026-09-21：TFT 測試環境修復

- 實際失敗紀錄 `c3a270d6fe2d4f049fe093f1f6484412`、`a90615b7ecc74db6b2edff1422fa54a8` 均在 preflight 回報 `ModuleNotFoundError: No module named 'luma'`。硬體測試尚未啟動，不能用這兩筆紀錄判定螢幕或接線故障。
- 經使用者明確允許，僅在既有 `Pi_deployer/.venv` 補裝 `luma.lcd 2.13.0`、`luma.core 2.6.0`、`cbor2 6.1.4`。原有 gpiozero 2.0.1、lgpio 0.2.2.0、Pillow 9.4.0、spidev 3.5、smbus2 0.4.2 保持不變。
- Pi 連套件站有 DNS／下載逾時，因此由電腦從 PyPI 下載對應 Python 3.11／aarch64 wheel，核對 PyPI SHA-256 後透過 SSH 傳送，並在 Pi 再驗證雜湊後離線安裝。沒有改 Pi 網路設定或使用 system Python 安裝套件。
- 已在 Pi 驗證所有 TFT／HC imports 成功，`pip check` 通過。未啟動螢幕測試、未停止作品、未改供電／BLK。
- 使用者確認「啟用」後，先核對沒有執行中或切換中的 Board Vision 作品／測試服務，再使用 Pi 既有 `raspi-config nonint do_spi 0` 啟用 SPI0。`/boot/firmware/config.txt` 僅將 `#dtparam=spi=on` 改為 `dtparam=spi=on`；原檔備份至 `/boot/firmware/config.txt.boardvision-before-spi-20260921-1049`。
- 啟用後 `raspi-config nonint get_spi` 回傳 `0`，`/dev/spidev0.0` 已存在且既有 `pet` 使用者具讀寫權限；TFT／HC imports 與 `pip check` 再次通過。設定立即生效，boot ID 未變，因此沒有重啟 Pi。沒有啟動測試或作品，也未改接線、供電或 BLK；這只確認測試環境就緒，螢幕顏色與本次測試碼仍待實體驗收。
- UI 主卡現在直接列出已知的缺少套件及「尚未啟動硬體測試」，不再只顯示籠統環境錯誤；不從任意日誌文字產生安裝指令。153 項前端測試、i18n 檢查與正式編譯通過。

## 2026-09-21：TFT 有 RGB、看不到測試碼

- 使用者回報紅／綠／藍有出現，但沒有數字。`30dad316f3784a94b50b6541a1693f58` 的軟體紀錄雖為 `passed / user_visual_confirmation`，本次人工回報與之不符；該筆不得當作實體驗收完成，原始紀錄保留，需重新測試。
- 核對 Pi 實際 runner／driver 與本機來源相同：RGB 各停 1 秒，數字寫入後卻立即 cleanup。gpiozero 2.0.1 的 `LGPIOPin.close()` 會改為 input／PULL_NONE，factory 關閉時還會再次 close；Pi 讀回 `GPIO25 = input / pn / lo`，可能使接至 RES 的螢幕重設。Pi 上的 DejaVuSans.ttf 已存在，並非缺少數字字型。
- 修正後數字有固定 15 秒顯示期，期間持續回報 `display_code`／心跳、維持互斥鎖，停止及遠端期限仍有效；顯示完才釋放硬體並進入人工確認，不自動通過，也不一直占用 GPIO 等待使用者。
- RES 改用獨立 lgpio handle，僅操作接線資料指定的 RES 腳；結束時設為 input／PULL_UP 後關閉 handle，使 gpiozero 的 DC／factory 清理不再把 RES 改成無上拉。正常、初始化失敗、釋放失敗及重複 close 都有資源釋放測試；不使用常駐 GPIO 程序、不碰 ECHO／GPIO18 或 BLK、不改供電／接線。
- 前端加入看實體螢幕／至少 15 秒的提示，並明示沒看到數字不得猜選通過。121 項相關後端回歸、154 項前端測試、i18n 與正式編譯通過；瀏覽器載入 `index-C9pWlhKd.js`、無 console error，原有 11/11 人工接線進度保留。
- 磁碟模板版本更新為 `component-test-v3`。目前後端未重啟，記憶體中的管理端版本欄仍可能是 v1；新測試仍會從磁碟即時讀取、上傳上述修正版 runner／driver。不要用舊管理端版本欄代替實際測試程式核對。
- 本輪未自動啟動硬體測試。待現場重測：確認 RGB 後數字可見至少 15 秒、釋放後 RES 偏壓及測試卡保留情況、依本次實體數字完成確認。軟體回歸通過不代表已完成這些實體項目。
