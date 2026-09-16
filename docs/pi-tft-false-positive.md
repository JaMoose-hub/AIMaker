# Pi / TFT 假陽性修正（2026-09-10）

## 已確認原因與範圍

直接以 CUDA Pi 模型重跑 S01 保存圖片，TFT 左／右均產生 Pi observation，信心約 0.310／0.315；真 Pi 中央／右約 0.345／0.385。真 Pi 左側該張模型回傳 None，因此不能直接提高全域信心門檻或宣稱模型全位置皆成功。

TFT 的 Pi 原始四角位於外框中很小的區域。原程式仍進入同時接受藍色與綠色 PCB 的輪廓細化，之後產生 Pi Profile 投影並持續追蹤。模型假陽性已重現；不是僅前端標籤問題。

## 本次修改

- 僅 Pi 四角路徑在輪廓細化前檢查有限數值、凸四邊形與 quad / bbox 面積比（暫定 0.18～1.5）。8-landmark 路徑、其他模組與全域信心門檻不變。
- 不一致 observation 清除 primary 時序狀態、回傳 `corner_box_inconsistent`，不延長旧 Pi 定位。
- Hybrid 允許真正 locked 的特徵 fallback，但不能以 stale fallback 覆蓋拒絕理由；快速追蹤收到拒絕時撤銷舊 template。
- 這是可解釋的幾何篩選，不是新分類模型，也不保證所有 TFT／背景皆不誤認。極端斜角可能被拒絕；手持角度驗收前不得宣稱無退步。

## 驗證

- 87 項相關後端測試通過（新增保存 raw observation 正反例及追蹤撤銷測試）。
- 服務重啟 PID 30852。現場 TFT 右側 10 秒 239 幀：TFT 239 locked、Pi 239 searching，約 23.9Hz，capture-to-response p95 47ms。
- 瀏覽器實看 TFT 框／腳位仍在，額外 Pi 框／腳號未出現。
- 證據：`runs/acceptance/2026-09-10/S01-TFT-right-corner-guard/`。
- 原右側對照曾 Pi 250/250 locked；本輪未宣稱完整九階段驗收完成。
- 真 Pi 中央現場複驗：`S01-Pi-center-corner-guard`，10.015 秒 247/247 locked、其他三件全 searching，24.66Hz。此姿態未被擋掉，左右側與手持角度仍待測。

## 待完成

空桌後重新放回 TFT 中央 `S01-TFT-return-corner-guard`：10.047 秒 235/235 locked、其他三件全 searching，23.39Hz；瀏覽器未見 Pi 標記。一次移出／放回後定位可恢復，未量測恢復時間，多次循環與角度仍待驗。

空桌現場複驗 `S01-empty-after-TFT-corner-guard`：10 秒 226 幀四件全 searching，22.6Hz，瀏覽器無板框／Pin 殘留。取樣在移出後才開始，不作移出至清除延遲證據；放回後定位待驗。

TFT 中央現場複驗 `S01-TFT-center-corner-guard`：10.016 秒 TFT 243/243 locked，其他三件全 searching，24.26Hz；畫面未見 Pi 標記。至此真 Pi 與 TFT 三位置靜止複驗完成；重新取得定位與角度仍待測。

TFT 左側現場複驗 `S01-TFT-left-corner-guard`：10.015 秒 TFT 242/242 locked，Pi 全部 searching，24.16Hz；瀏覽器未見額外 Pi 標記。中央／重新取得定位仍待複驗。

真 Pi 右側現場複驗 `S01-Pi-right-corner-guard`：10.015 秒 254/254 locked、其他三件全 searching，25.36Hz。修正後三位置此姿態靜止均未被擋掉；角度與動態回歸仍未完成。

真 Pi 左側現場複驗 `S01-Pi-left-corner-guard`：10 秒 235/235 locked、其他三件全 searching，23.5Hz。另行合成變形回放 20 幀有 1 幀 lost；不混為現場丟失，仍需動態測試。

- [ ] 真 Pi 現場重新辨識、三位置與角度回歸；原始兩張正例幾何檢查通過不能代替現場測試。
- [ ] TFT 左側／中央複驗與反覆移入／移出；其他負例回歸。
- [ ] HC 左側重定位不一致與 HW stale 根因修正。
- [ ] 更多影像／視角檢驗面積比門檻，避免以單批案例當通用準確率。
