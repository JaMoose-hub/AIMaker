# GPIO 照片標記 POC

獨立 Python 工具，把真實照片轉成可操作的離線網頁，以及送給視覺 AI 的 PNG／JSON／提示詞素材。`poc.py` 與網頁本身不呼叫雲端；另有需明確 `--run` 才執行的單次雲端 runner。不使用攝影機，也不啟動 Board Vision 或操作 Pi。

## 已實作

- 一或兩張照片；保留原始照片檔，使用 Pillow 校正 EXIF 方向，依 ICC 一次轉成 sRGB 供網頁及雲端素材共用。
- 本次兩張照片已由助理看圖預標：板內側 10 個、板外側 8 個線材與接頭交界；位置 ID 為 I01–I10／S01–S08。
- 可拖曳座標、候選實體 Pin、人工核對腳號狀態。
- 未調色接頭特寫；局部 HSV 色票估計，混色時回報未知。
- 可下載標記 JSON、原圖／標記／特寫素材和 AI 提示詞。
- JSON 匯入與 Python 重放均核對照片 SHA-256、尺寸與座標。
- 可選 `--detect`：重用目前 Pi 5 模型與板型投影，提供候選腳位診斷。結果不是接線確認；失敗保留手動位置標記。
- 可選 `run_cloud_joint.py --run`：透過既有 CodexBridge，在同一請求裡看兩張未標記照片、回傳出線區域座標＋線色。標記依雲端線色上色，與本機像素取色分开保存。

## 單次雲端聯合判讀

```powershell
& 'C:\Project\PnP\board-vision\backend\.venv\Scripts\python.exe' -X utf8 `
  'C:\Project\PnP\board-vision\tools\gpio_photo_poc\run_cloud_joint.py' `
  --run --model gpt-6.1-sol --effort low `
  --out 'C:\Project\PnP\board-vision\runs\gpio-photo-poc\cloud-joint-new-run'
```

需要已登入 ChatGPT 的 Codex CLI；沿用登入，不讀取 token，也不需要新增 API key。模型與推理設定須在當下模型清單中支援圖片；不提供 `--model`／`--effort` 時使用該清單的預設。雲端通道是一次性、禁用工具的照片分析，沒有別的照片分析子請求或模型替換。

本次 runner 讀取既有 POC 保存的兩張原始照片，以 SHA-256 核對；只使用照片名稱、尺寸和原始像素，不提供舊預標點、舊線色或預期數量。EXIF／ICC 校正後的未標記 PNG 送入同一請求；雲端 normalized 0–1000 座標轉回原圖像素。腳號全留空；程式不修正雲端點位、不用本機取色覆寫雲端線色。

輸出包含 `cloud-response.json` 原始回覆、`cloud-markers.json` 座標轉換結果、`timing.json` 分段時間、`cloud-annotated-N.png`，以及 `viewer/index.html`。雲端線色是候選觀察；彩色圈的 RGB 是固定顯示調色盤，不代表精確實測 RGB。`wire_roi` 可為 null。

雲端時間包含傳送、排隊、判讀與回傳，無法當作純推論時間。總時間包含圖片準備、連線／模型清單、驗證、PNG 存檔與完整網頁產生；它是單次測試，並非平均延遲或真實場景準確率。

## 執行本次照片示範

這個 Git 版本只包含工具原始碼；本次私有照片、`assistant-prelabels.json` 與 `runs/` 內的產出不會上傳。`run-demo.ps1` 需要原工作站上的那些素材；其他工作站請使用下方「使用自己的照片」指令。

在 PowerShell 執行：

```powershell
& 'C:\Project\PnP\board-vision\tools\gpio_photo_poc\run-demo.ps1'
```

腳本輸出新資料夾並列出 `index.html` 的位置，用瀏覽器開啟即可操作。網頁自帶照片，無需伺服器、網路或金鑰；只在瀏覽器記憶體編輯，請用「匯出 JSON」保存。

`assistant-prelabels.json` 保存助理預標座標，以照片 SHA-256 與尺寸綁定。這次預標是助理先檢查原照片、找出可見接頭的出線位置，再由程式疊圖。所有實體腳號先留空；遮住的入口不猜點。它沒有實作對任意新照片自動推論接頭位置的模型。

若要同時測試現有模型的候選定位：

```powershell
& 'C:\Project\PnP\board-vision\tools\gpio_photo_poc\run-demo.ps1' -Detect
```

## 使用自己的照片

```powershell
& 'C:\Project\PnP\board-vision\backend\.venv\Scripts\python.exe' -X utf8 `
  'C:\Project\PnP\board-vision\tools\gpio_photo_poc\poc.py' `
  --image 'C:\path\photo.jpg' `
  --out 'C:\Project\PnP\board-vision\runs\gpio-photo-poc\my-photo'
```

自己的照片預設不放任何猜測標記。點照片新增位置，拖曳標記到線材與接頭交界；候選腳號可留空。`--demo` 保留初版每張 3 個示範起點，但本次執行腳本已改用完整預標 JSON，全部腳號未確認。

下載網頁的 JSON 後，可用 `--markers 'C:\path\markers.json'` 重建 PNG；搭配同一張原始照片。輸出資料夾必須為空，工具不覆蓋已有結果。

## 輸出

| 檔案 | 用途 |
| --- | --- |
| `index.html` | 可編輯的離線網頁，內嵌照片 |
| `source-original-N.jpg/png` | 逐位元組保留的原始照片與其色彩設定 |
| `raw-N.png` | EXIF 方向校正、依 ICC 轉成 sRGB 後的無標記圖片 |
| `annotated-N.png` | 在照片副本畫位置 ID／候選 Pin |
| `crop-N-M.png` | `raw-N.png` 指定區域的逐像素裁切 |
| `markers.json` | 原圖雜湊、尺寸、座標、來源、候選腳號 |
| `ai-prompt.txt` | 要求從照片判讀、允許未知的提示詞 |
| `preview.png` | 初始狀態的靜態概覽 |

給雲端 AI 時提供原圖、標記圖與未調色特寫，附上提示詞。位置 ID 是參照；候選 Pin 與人工核對不能直接當作 AI 的觀察答案。兩張圖出現同一 ID 也不保證同一條線。

## 驗證邊界

初版能驗證標記、座標、色彩管理後的逐像素裁切與輸出流程，沒有量測雲端 AI 的腳號辨識提升。Display P3 等照片依原始 ICC 轉成 sRGB 一次，沒有增強對比、銳化或重新生成細節；原始檔另行完整保留。局部色票不證明線路連續、插接正確、導通、電壓或元件功能。斜拍時板面座標與高起的接頭有視差，模型投影需人工或局部幾何再核對。

測試：`python -X utf8 -m unittest discover -s tools/gpio_photo_poc -p test_poc.py -v`。
