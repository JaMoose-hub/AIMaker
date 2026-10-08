# TFT 新照片盲測 — 2026-10-06

## 範圍與輸入

使用者要求以新 TFT 接頭照片替換零件照，Pi 內／外排沿用原照片，先以現有
程式檢查是否能發現漏接。僅建立隔離 replay 與測試紀錄，未修改 production
演算法、現場工作階段、人工確認或接線，未操作 Pi。

- 來源工作階段：`64d3e0319c80433696d33940161d41d8`。
- Pi 內排 capture：`fabfc3b945d4452fb136194f90771992`。
- Pi 外排 capture：`b620c9e9ca4a42c2b3de61e6f7eb4eb2`。
- 兩張 Pi 原照 SHA-256 與原工作階段及先前凍結實驗照片一致。
- 新零件圖：使用者附件 `1-照片-1.jpg`，2880 × 3840。
- 實際分析圖：Pi 各 2048 × 1536，零件圖 1536 × 2048；無額外裁切或圖上提示。

沿用正式 `inspect_wiring_photos`、`_canonical_candidates`、`compare_candidates`
與 `_review_summary`。TFT 接線來自正式 `wiring_for`，同時包含 HC 與 TFT 的
既有組合。冷啟動本次分析，不重用舊模型觀察；未將使用者指出的漏接答案或
本次人工判讀寫入任何模型提示。

## 執行結果

- Pipeline：`poc-exit-pin-demo-2048-v8-candidate-seat`。
- 實際模型：GPT-6.1-Sol，effort low。
- 一輪分析，2 次模型呼叫，無重試。
- 出線盤點：51.687 秒，辨識出 6 條零件接線。
- 腳位判讀：120.484 秒。
- 程式分析總耗時：172.843 秒；不含先前取回來源照片的準備時間。

模型原始 `header_observation`：

```json
{
  "state": "housings_visible",
  "evidence": "六個外殼可見；RES 與 BLK 印字上方各有完整裸露針尖。"
}
```

六個接頭的零件標字分別為 GND、VCC、SCL、SDA、DC、CS。
模型已在自由文字中指出 RES 和 BLK 的裸露針尖。

正式後處理最終摘要卻是：

> RES 這條線還需要確認。
>
> 補拍零件接頭，讓 RES 標字與插頭底部一起入鏡。

RES 結果為 `comparison=unknown`、`diagnosis.status=uncertain`，要求補拍
`component_header`。完整裸針觀察仍保存在 summary.observation，未成為主要疑點。

## 判定與原因

**本輪未通過「直接指出必接腳漏接，避免要求不必要補拍」的使用流程驗收。**
這不是模型完全看不到：原始回覆已辨識到 RES 裸露。主要缺口在資料結構與
後處理：裸露腳位沒有逐 pin 的結構化記錄；沒有導線出口的 RES 沒有接頭
candidate，因而落入缺少端點、要求補拍的分支。整個視角的單一 state 又被
選為 `housings_visible`，沒有觸發 `uncovered_pins` 的摘要分支。

從既有零件 Profile、catalog 與保存設計核對：RES 是必接端子；BLK 是選用
端子，本作品明確留空。因此合適的使用者提示是：

> **螢幕 RES 腳位沒有接線。**
> 它在 SDA 與 DC 中間；請對照接線圖補上這條線。
> 最右邊的 BLK 本作品原本就留空。

以上是測後對照原始模型觀察與設計要求的結論，不是現行程式成功輸出的摘要。
照片與這次測試不能證明其他線路正確或螢幕已通過功能測試。

## 保存證據

- 原圖、來源雜湊、接線快照、提示、schema、原始回覆、模型收據、逐線結果：
  `runs/tft-photo-check-20261006/attempt-1/`。
- 完整輸出：`result.json`。
- 原始雲端回覆：`pin_review-response.json`。
- 受兩次呼叫上限約束的隔離程式：`runs/tft-photo-check-20261006/replay.py`。

本次是一組已知現場案例的開發測試，沒有重新取景、修改圖片、反覆調 prompt，
也不是辨識準確率或硬體驗收統計。
