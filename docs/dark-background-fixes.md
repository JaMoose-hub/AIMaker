# 深灰背景修正紀錄（2026-09-11）

## 已修改並載入

- PlanarFlow 初始化／更新模板前，拒絕越界四角，避免把裁切後仍有紋理的錯誤大框當成有效模板；失敗刷新不覆蓋舊模板。
- Feature PoseTracker 對 PnP 的原始投影再檢查有限值、凸形、影像邊界與既有面積要求，不只檢查前段 homography。平滑後投影若越界，重置平滑器並採用已驗證原始 pose。
- 膚色遮擋遮罩增加 3×3 opening，排除反光上的零散色彩雜訊；未調低 8% 遮擋門檻，仍擋連續手部色塊。
- 清空追蹤時同步清空 confirmation 診斷，避免顯示前一段確認資料。

## 驗證

- 後端完整測試：881 passed，1 項既有 Starlette 相依套件警告。
- 新增 `backend/tests/test_dark_background_regressions.py`：越界模板原子刷新、不同方向越界、零散膚色雜訊／連續皮膚色塊、保存 HC 圖重播。
- `tools/probe_dark_components.py` 使用保存圖與 CUDA component models，可重複執行。
- HC 保存圖原始模型 confidence 0.4139，有候選；舊膚色比例 0.08203，新比例 0.05330。固定候選連續重播可 locked。照片為原取樣後另拍，不是失敗序列所有影格，也不能取代現場復測。
- Pi 保存圖使用 feature fallback 重複 30 幀：2 searching、28 locked、0 越界鎖定。並未重現原失敗動態序列，故只確認防護與重播結果，未宣稱根因全部解決。
- HW 保存圖在既有 CUDA 模型／門檻下仍沒有原始候選；未調低門檻，未移除方向驗證。HW 候選缺失與方向問題仍未修完。
- 重啟後 PID 2904；`/api/inference/status` 四類模型 available、actual_backend=cuda、preprocessing_backend=cuda，無 fallback。LK 仍使用 CPU。
- 重啟後 TFT 取樣 `runs/acceptance/2026-09-11/S02-TFT-dark-after-fix-01/`：10.016 秒 215 幀四類全 searching。瀏覽器見場景幾乎全黑，與修前明亮場景不一致；不能算通過或直接判定定位修正退步。是否照明改變或相機曝光重啟差異尚待確認。

## 尚未完成

- [x] 使用者回覆「開燈了」，畫面亮度恢復；開燈後 TFT 10 秒 252/252 locked、其他類 searching（`S02-TFT-dark-after-fix-light-on-01`）。先前近黑取樣不作同光線比較，不宣稱已量測曝光或恢復時間。
- [x] HC 深灰背景開燈後靜態複測：10.031 秒 230/230 locked，其他類 searching，22.93Hz（`S02-HC-dark-after-fix-01`）。重新擺放及照明非精確影像 A/B，不直接推定所有因果。
- [ ] HC 仍需真實手部遮擋、多膚色、距離與多次重新定位案例；單輪成功不結案。
- [ ] Pi 越界完整序列重現、修改後現場重新定位與換背景回歸。現場 `S02-Pi-dark-after-fix-01` 239/264 locked、25 stale（90.53%，未達 95%），本輪無 outside_frame；25 stale 均 awaiting_model_confirmation，首幀來源 locked 但角點差 48.73px > 45.59px，語意確認逾 2 秒。需繼續查幾何不一致，不能宣布 Pi 已修好。
- [ ] HW 候選缺失與方向失敗的處理；候選不足不能偽造外框或 Pin。新增現場 `S02-HW-dark-after-fix-diagnostic-01`：10 秒 239 幀全 searching，上游全 pin_orientation_unverified、首個來源 confidence 0.6439；目前擺位下有候選但方向驗證拒絕，已保存事後來源圖供四方向重播，不以此解除先前候選缺失缺陷。
- [ ] TFT/Pi 混淆、白纸、深灰、空背景完整回歸；四類都未正式驗收。

不新增操作確認門檻、不變更限定零件、不以合成圖或單張重播冒充硬體驗收。
