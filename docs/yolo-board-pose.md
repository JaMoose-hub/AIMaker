# YOLO Pose + Board Profile GPIO 定位

## 目前狀態

執行端已支援 `detector: hybrid`：OpenCV DNN 讀取四點 YOLO Pose ONNX，
以板卡 Profile 的實體外框解 6-DoF，再投影 `board.json` 內所有 GPIO。
模型不存在、四點信心不足、四邊形不合法或 PnP 重投影誤差超標時，會回退到
原本的 ORB/SIFT `PipelineDetector`，不會讓相機服務停止。

目前 repository **沒有** checked-in 模型權重；下一個實機 gate 是收集與標註資料。

## 四點契約

四個 keypoint 是板卡座標系的語意角點，不是畫面當下的上／下／左／右：

1. `profile_TL` = `(0, 0)`
2. `profile_TR` = `(W, 0)`
3. `profile_BR` = `(W, H)`
4. `profile_BL` = `(0, H)`

UNO Q 正面朝上且 USB-C 朝左時，這四點看起來就是一般 TL/TR/BR/BL；板子旋轉後，
仍要追蹤同一個實體角，不能依螢幕位置重新排序。Runtime 依賴這個順序辨別板子方向與 GPIO 編號。

## 收集資料

先啟動一般相機 pipeline：

```powershell
.\scripts\camera.ps1 -DeviceIndex 1
```

另開 PowerShell，在 live `/video` 上收集 train：

```powershell
backend\.venv\Scripts\python.exe tools\capture_yolo_board_pose.py `
  --out datasets\board-pose --split train
```

再用不同擺位、光線或另一個拍攝 session 收集 val，避免把同一段連續影格隨機拆到
train/val，造成資料洩漏：

```powershell
backend\.venv\Scripts\python.exe tools\capture_yolo_board_pose.py `
  --out datasets\board-pose --split val
```

起始目標可先做 300--500 張 train、60--100 張 val，包含：

- 0/90/180/270 度旋轉；
- 0--30 度斜視；
- 畫面中央與四周；
- 均勻亮、偏暗、局部反光；
- 空板、少量杜邦線、手短暫遮擋；
- 不同背景，但 GPIO pitch 仍至少 18px。

## 訓練與匯出

資料格式是 Ultralytics YOLO Pose：一類別、`kpt_shape: [4, 3]`。設定在
`training/board-pose.yaml`。Runtime 不依賴 Ultralytics；訓練腳本才會 import 它。

Ultralytics 官方目前提供 AGPL-3.0 與 Enterprise 路徑，訓練前需要先確認本專案的
授權策略：<https://www.ultralytics.com/license>。

在獨立訓練環境安裝套件後：

```powershell
python tools\train_yolo_board_pose.py `
  --model <你的-pose-base-model.pt> `
  --data training\board-pose.yaml `
  --output models\board-pose.onnx `
  --epochs 150 --imgsz 960 `
  --accept-ultralytics-license
```

腳本固定輸出 `nms=False`、opset 12 的 raw ONNX，符合 OpenCV parser 契約。官方 Pose
資料格式與 ONNX 匯出說明：

- <https://docs.ultralytics.com/datasets/pose/>
- <https://docs.ultralytics.com/modes/export/>

## 執行 Hybrid

```powershell
.\scripts\camera-yolo.ps1 -DeviceIndex 1
```

預設模型為 `models/board-pose.onnx`。可用 `-ModelPath` 指定其他模型。模型未就緒時
腳本會警告，後端仍可啟動並使用既有 Pipeline fallback。

YOLO 成功定位的 WS detection 會帶：

```json
{ "tracking": "locked", "pose_path": "yolo", "pose_inliers": 4 }
```

最終驗收不只看 YOLO mAP；主要指標應是投影 GPIO 對人工真值的 px/pitch 誤差、
不同旋轉角的 pin identity，以及杜邦線端點吸附是否仍通過 physical scale gate。

