# 三層接線驗證 MVP

目前光敏電阻導引把三種不同證據分開顯示，再由後端保守融合：

| 層級 | 實作 | 能證明 | 不能證明 |
|---|---|---|---|
| 幾何定位 | YOLO Pose/Profile + 線頭吸附 | 線頭靠近指定 Pin | 接頭確實插入、導通 |
| 插入外觀 | 雙端 ROI + 本機 `qwen3-vl:8b` | 兩端接頭外觀看似插入目標 | 電壓、導通、安全性 |
| 電氣驗證 | UNO Q 韌體 + USB Serial A0 光照挑戰 | Sensor AO 到 A0 的功能性響應 | 只靠單次靜態讀值不能證明線路正確 |

每層 evidence 都是 `pass | fail | uncertain | unavailable`，包含分數、品質、原因、時間與方法。硬衝突先於分數計算：錯 Pin、未插入或電氣失敗不會被其他高分平均掉。

信心度上限：只有幾何最高 49；幾何加插入外觀最高 79；三層都通過最高 99。視覺兩層彼此相關，先用 harmonic mean 合併；電氣層獨立性較高，三層通過時權重為相機 35%、電氣 65%。

## 啟動

一般相機 + YOLO + VLM：

```powershell
.\scripts\camera-yolo.ps1
```

啟用 Serial 電氣層前，需要先燒錄 v0.3.0 驗證韌體並啟動 UNO Q Debian proxy：

```powershell
.\scripts\flash-wiring-test.ps1 -Port COM3
.\scripts\start-wiring-serial-proxy.ps1
.\scripts\serial-gpio-test.ps1 -Port COM3 -AnalogA0
.\scripts\camera-yolo.ps1 -ElectricalVerification
```

只編譯、不燒錄：

```powershell
.\scripts\flash-wiring-test.ps1 -CompileOnly
```

## 光敏電阻驗收動作

1. `UNO Q 3.3V -> Sensor VCC`
2. `UNO Q GND -> Sensor GND`
3. `UNO Q A0 -> Sensor AO`
4. 在最後一步用手遮住再移開光敏電阻。

背景 worker 每 250ms 讀取 A0，使用 6 秒窗口；至少六筆資料且去除單一極端值後，ADC 變化達 full-scale 的 8% 才產生 `a0_response_confirmed`。沒有變化只保持 `uncertain`，不直接判定接錯。Serial 或韌體不存在時顯示 `unavailable`，相機與 VLM 流程仍可繼續。

安全限制：Sensor VCC 必須使用 3.3V。UNO Q 的 A0 是 3.3V ADC 輸入，不可接 5V 或 5.5V。

## 推播格式

同一個 `/ws/detections` 會發布 `verification_update`：

```json
{
  "type": "verification_update",
  "target": {"step_id": "photoresistor-ao", "board_pin": "A0", "component_pin": "AO"},
  "evidence": {
    "geometry": {"status": "pass", "score": 0.84, "reason": "target_endpoint_near_pin"},
    "visual": {"status": "pass", "score": 0.82, "reason": "vlm_both_endpoints_inserted"},
    "electrical": {"status": "pass", "score": 0.93, "reason": "a0_response_confirmed"}
  },
  "fusion": {
    "verdict": "verified",
    "verification_level": "electrical",
    "overall_confidence": 89,
    "score_cap": 99
  }
}
```

REST `GET /api/guidance/state` 也包含同一份最新 `verification` 快照，避免 latest-only WebSocket 在慢連線上遺失中間訊息。
