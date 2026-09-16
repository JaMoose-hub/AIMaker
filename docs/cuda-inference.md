# CUDA 辨識推論

Pi 5、HC-SR04、HW-123、MRD-TF240-8P-CS 的既有 ONNX Pose 模型共用
`CudaYoloPoseLocator`，由 ONNX Runtime CUDA Execution Provider 執行。
模型檔、輸入解析度、信心門檻、FP32 輸入、輸出解碼及 Profile 座標規則不變。
不啟用 FP16／TF32，不用模型加速結果替代接線或電氣驗證。

目前 Windows 主機為 RTX 4070 Laptop GPU，**CUDA device 0**。
DirectML 的顯示卡索引是另一個命名空間，不可直接照搬。
已安裝的 OpenCV 5.0.0.93 不含 CUDA，因此 LK、ORB、局部排針與幾何運算仍在 CPU。
停用中的零件分割／VLM 功能沒有因這次修改而啟用。

2026-09-08 的第二輪優化把 letterbox 縮放、補邊、BGR→RGB、HWC→NCHW 與
float32 正規化合併為 CuPy CUDA kernel。輸入只上傳原始 uint8 畫面，輸出以
ORT I/O binding 直接使用 GPU buffer，不把大張量複製回 CPU 再重新上傳。
每個模型有自己的 buffer／CUDA stream，交給 ORT 前明確同步，避免跨幀混用。
目前 1080p→768／960／1280 的像素輸入與原 OpenCV 完全一致；特殊奇數尺寸
另測邊界與補邊，容許 OpenCV 平台 SIMD 尾端的最多一階 uint8 色差。

剩餘 CPU 部分也做了縮減：J8 靜止檢查只處理板卡＋排針的 ROI（64px halo、
原始像素、相同雙向 LK／遮擋門檻），不再對整張 1080p 建金字塔；OpenCV
執行緒池預設 2，可用 `BOARDVISION_OPENCV_NUM_THREADS` 調整（1–32）；MJPEG
解析保留掃描游標，不再於每個小 pipe chunk 重掃整張尚未完整的 JPEG。
相機仍是 C920 原生 1920×1080 MJPEG、30fps 設定；解碼、USB、UI 與小型幾何
檢查仍需要 CPU。這不代表整套程式能做到零 CPU。

## 安裝與設定

```powershell
cd backend
uv sync --locked
uv run uvicorn app.main:app --host 127.0.0.1 --port 8100
```

`cuda` 是預設依賴群組，鎖定 ONNX Runtime GPU 1.24.4 與 CUDA 12 / cuDNN 9
的 NVIDIA runtime wheels。不需要 PyTorch 或系統級 CUDA Toolkit；第一次同步
會下載約 1.8 GB。不要在同一環境安裝 `onnxruntime-directml` 和
`onnxruntime-gpu`，兩者會覆寫相同 Python 套件；依賴設定已宣告互斥。

`yolo_pose` 和 `component_vision` 均設定 `runtime_backend: cuda`、`cuda_device_id: 0`。
`scripts/camera-yolo.ps1` 也預設 CUDA，並接受 `-RuntimeBackend opencv` 或
`-RuntimeBackend directml`，自行選用對應依賴群組。
一般 `uv run` 依 YAML 設定，不會覆寫相機、鏡像或校正。

CPU 環境可用 `uv sync --no-group cuda`，再將上述兩處後端設為 `opencv`，
並用 `uv run --no-group cuda ...` 啟動。DirectML 則用
`uv sync --no-group cuda --group directml` 和相同 `uv run` 群組參數，設定兩處
後端為 `directml` 與該主機正確的 `directml_device_id`。

Windows 的 ORT 1.24 預載清單沒有新版 cuDNN 的 tensor-IR DLL；本專案在預載
後從已安裝 NVIDIA wheel 的絕對路徑載入該 DLL，不變更系統 PATH 或顯卡驅動。
實作依據：[ONNX Runtime CUDA](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html)
與 [上游 DLL 預載清單](https://github.com/microsoft/onnxruntime/blob/main/onnxruntime/__init__.py)。
前處理另外鎖定 `cupy-cuda12x==14.2.0`（Windows wheel 約 94 MiB）。參考
[CuPy 安裝](https://docs.cupy.dev/en/stable/install.html)、
[ORT I/O binding](https://onnxruntime.ai/docs/performance/tune-performance/iobinding.html)
與 [OpenCV resize 插值規則](https://github.com/opencv/opencv/blob/5.0.0/modules/imgproc/src/resize.cpp)。

## 執行與回退

每個模型初始化都先用丟棄輸出的張量預熱，驗證 DLL 與顯存配置；這不是辨識結果。
每個 session 的 CUDA 記憶體 arena 上限 1 GiB（不包含所有驅動／cuDNN 配置），
使用 heuristic 卷積選擇、按需 arena 成長、1 個 CPU intra/inter-op 執行緒。

沒有 CUDA、初始化失敗或執行中出錯時，該模型改走既有 OpenCV CPU，記錄原因。
不會因為「畫面中未偵測到物件」而回退，也不回傳舊框冒充當前定位。
若只有 CUDA 前處理失敗，先回退成 CPU 前處理＋CUDA 模型，另行回報原因；
不因缺少 CuPy 就放棄已正常運作的 CUDA 推論。

```powershell
Invoke-RestMethod http://127.0.0.1:8100/api/inference/status | ConvertTo-Json -Depth 6
```

每個模型回報 requested/actual backend、available、device_id、providers、
fallback_reason、成功 CUDA locate 次數與累積平均耗時（包含前後處理，不等於 FPS）。
新增 `preprocessing_backend`、`preprocessing_fallback_reason` 及全域
`opencv_num_threads`，可分開查模型與前處理的實際執行位置。
`providers` 也列出 CPU 作為備援，不表示卷積正使用 CPU；要查每個算子的實際
執行位置請使用下面的 profile 驗證。混合 CPU shape 運算本身不代表 CUDA 失效。

## 驗證

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe ..\tools\verify_cuda_inference.py --image <包含四個模組的實拍照片> --out ..\runs\diagnostics\cuda-check
.\.venv\Scripts\python.exe ..\tools\benchmark_cuda_preprocess.py --image <實拍照片> --out ..\runs\diagnostics\cuda-preprocess-benchmark.json
.\.venv\Scripts\python.exe ..\tools\verify_motion_tracking.py --seconds 20 --out ..\runs\diagnostics\cuda-live
```

CUDA 驗證使用同一實拍照片與已知旋轉，逐模型比較 CPU/CUDA 是否偵測及全部
landmark 座標，要求至少有辨識可比較、差異 <1 px、CUDA 卷積實際執行且無 CPU
卷積。算子 profile 會增加耗時，該表不是完整產品 FPS，也不是實際手持／遮擋測試。
正式服務不開 profile；實拍性能、瀏覽器與本次結果位於
`runs/diagnostics/cuda-inference-20260908/RESULTS.md`。
第二輪結果見 `runs/diagnostics/cuda-preprocess-20260908/RESULTS.md`。
注意：`verify_motion_tracking.py` 會請求追蹤影格、喚醒追蹤 worker；量測「追蹤
關閉」CPU 時不要執行它。模型辨識與必要的靜止檢查仍會持續執行。
