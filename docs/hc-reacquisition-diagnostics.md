# HC 重新定位診斷（2026-09-11）

本輪為診斷能力與回歸測試更新，不宣稱修復首次左側失敗。

- 舊失敗期間只有 motion 的 `template_expired`，缺少配對模型來源狀態，不能判定是哪一段停止更新。
- 保存的失敗取樣後照片可由 CUDA 模型及 ComponentPoseTracker 鎖定；它不是失敗期間同幀證據。重複靜態圖片也不能代替真實影片。
- 拆分過期原因：frame_gap、clock_reversed、semantic_lease_expired、frame_shape_changed、recovery_timeout。
- 每個 motion 輸出附帶 model_source：配對是否存在、來源影格／年齡、上游 tracking／quality、已消費 seed。無新增推論、無修改門檻、無延長舊框期限。
- 新增過期後新 seed 可重新鎖定、舊 seed 不復活及缺來源診斷測試；相關 67 項測試通過。
- 重啟 PID 6800，現場取樣 `runs/acceptance/2026-09-11/HC-source-diagnostics/`：10.015 秒 222/222 HC locked，其他三件 searching，22.17Hz，capture-to-response p95 47ms。
- 上游在 31 個顯示影格為 stale / awaiting_consensus，motion 仍全部 locked。這是上游／快速追蹤狀態差異，不等於 31 次模型失敗；重複來源會出現在多個顯示影格中。

下一步：記錄空桌後重新放入左側的來源狀態，若重現失敗可分辨模型缺失、材質／手部檢查、共識等待、配對延遲、光流失敗。不要憑此次成功宣稱原問題消失。HW stale 仍待查。

空桌複驗 `HC-empty-source-diagnostics`：10.016 秒 226 幀四件全 searching，HC 上游 model_missing，快速追蹤最後原因 recovery_timeout，畫面無殘留板框／Pin。符合取樣時空桌狀態，但沒有記錄移出瞬間，不能推算清除延遲。下一步放回左側。

放回左側 `HC-return-source-diagnostics`：10.031 秒 HC 241/241 locked，其他三件 searching，24.03Hz。上游 199 個顯示影格 locked/deadband、42 個 stale/awaiting_consensus；配對來源年齡 47～469ms，快速追蹤全程 locked。顯示影格重複使用來源，不能把 42 算成獨立模型失敗次數。此輪未重現原問題，也未量到入鏡至鎖定延遲；保留 HC 未結案，先收集 HW stale 診斷，不繼續只重複相同靜止取樣。
